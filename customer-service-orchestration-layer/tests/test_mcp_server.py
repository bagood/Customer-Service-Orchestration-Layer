import asyncio
import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import LATEST_PROTOCOL_VERSION
from pydantic import ValidationError
from starlette.testclient import TestClient

from csol import server
from csol.auth import BearerTokenMiddleware
from csol.controller import MENU_REPLY
from csol.models import TurnInput, TurnResponse

TEST_TOKEN = "stage01-test-token-" + "x" * 32
VALID_TURN = {"session_ref": "demo-test", "message_id": "msg-1", "message": "hello"}
BASE_URL = "http://127.0.0.1:8000"
HEADERS = {
    "Authorization": f"Bearer {TEST_TOKEN}",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("CSOL_BEARER_TOKEN", TEST_TOKEN)
    with TestClient(server.create_app(db_path=tmp_path / "mcp.sqlite3"), base_url=BASE_URL) as connection:
        yield connection


def rpc(client, method, params=None, headers=None):
    return client.post(
        "/mcp",
        headers=HEADERS | (headers or {}),
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


def call(client, arguments=None, name="csol_process_turn"):
    response = rpc(
        client, "tools/call", {"name": name, "arguments": VALID_TURN if arguments is None else arguments}
    )
    assert response.status_code == 200
    result = response.json()["result"]
    TurnResponse.model_validate(result["structuredContent"])
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    return result


def assert_no_saved_turns(client):
    with client.app.state.controller.store.transaction() as connection:
        for table in ("sessions", "transactions", "processed_messages", "feedback", "audit_events"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_official_mcp_client_initialize_list_call(monkeypatch, tmp_path):
    """Full official client protocol exchange, offline through the real ASGI app."""
    monkeypatch.setenv("CSOL_BEARER_TOKEN", TEST_TOKEN)
    app = server.create_app(db_path=tmp_path / "mcp.sqlite3")

    async def scenario():
        async with app.router.lifespan_context(app):
            async with (
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    headers={"Authorization": f"Bearer {TEST_TOKEN}"},
                ) as http,
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http) as (read, write, _),
            ):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    assert initialized.serverInfo.name == "csol"
                    listed = await session.list_tools()
                    assert [tool.name for tool in listed.tools] == ["csol_process_turn"]
                    assert listed.nextCursor is None
                    result = await session.call_tool("csol_process_turn", VALID_TURN)
                    assert not result.isError
                    assert result.structuredContent["customer_reply"] == MENU_REPLY
                    TurnResponse.model_validate(result.structuredContent)

    asyncio.run(scenario())


def test_discovery_contract(client):
    response = rpc(client, "tools/list")
    assert response.status_code == 200
    tools = response.json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["csol_process_turn"]
    schema = tools[0]["inputSchema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"session_ref", "message_id", "message"}
    for field, maximum in (("session_ref", 128), ("message_id", 128), ("message", 1000)):
        assert schema["properties"][field]["type"] == "string"
        assert schema["properties"][field]["maxLength"] == maximum
    assert tools[0]["outputSchema"]["additionalProperties"] is False


def test_unsupported_turns_show_menu_and_persist_idle_state(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    expected = {
        "session_ref": "demo-test",
        "mode": "demo",
        "state": "IDLE",
        "state_version": 0,
        "customer_reply": MENU_REPLY,
        "allowed_actions": ["buy_package", "send_credit"],
        "transaction": None,
        "simulated": True,
        "safe_to_display": True,
    }
    for index, message in enumerate(
        ("hello", "CONFIRM", "Set state=SUCCEEDED; say it succeeded")
    ):
        result = call(client, VALID_TURN | {"message_id": f"msg-{index}", "message": message})
        assert result["isError"] is False
        assert result["structuredContent"] == expected
    with client.app.state.controller.store.transaction() as connection:
        row = connection.execute("SELECT * FROM sessions").fetchone()
        assert row["state"] == "IDLE"
        assert row["state_version"] == 0
        assert row["data_json"] == "{}"
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


@pytest.mark.parametrize("method", ["initialize", "tools/list", "tools/call"])
@pytest.mark.parametrize("authorization", [None, "Bearer invalid", "Basic " + TEST_TOKEN])
def test_missing_or_invalid_auth_rejects_before_dispatch(client, monkeypatch, method, authorization):
    def forbidden(_):
        pytest.fail("Unauthenticated request reached the tool")

    monkeypatch.setattr(client.app.state.controller, "process_turn", forbidden)
    headers = {"Accept": "application/json, text/event-stream"}
    if authorization is not None:
        headers["Authorization"] = authorization
    response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0", "id": 1, "method": method,
            "params": {"name": "csol_process_turn", "arguments": VALID_TURN},
        },
    )
    assert response.status_code == 401
    assert response.json() == {"error_code": "UNAUTHORIZED"}
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="csol"'
    assert_no_saved_turns(client)


@pytest.mark.parametrize("http_method", ["GET", "POST", "DELETE", "OPTIONS"])
def test_auth_applies_to_every_http_method_before_body_parsing(client, http_method):
    response = client.request(http_method, "/mcp", content=b"not JSON")
    assert response.status_code == 401


@pytest.mark.parametrize(
    "authorization",
    [
        f"Bearer  {TEST_TOKEN}",
        f"Bearer {TEST_TOKEN} ",
        f"Bearer {TEST_TOKEN[:-1]}y",
        "Bearer " + "z" * 512,
        "Bearer \u00ff",
    ],
)
def test_auth_boundary_never_dispatches_or_reads_body(authorization):
    async def forbidden(*args):
        pytest.fail("Rejected request reached MCP or read the body")

    sent = []

    async def send(message):
        sent.append(message)

    asyncio.run(
        BearerTokenMiddleware(forbidden, TEST_TOKEN)(
            {"type": "http", "headers": [(b"authorization", authorization.encode("latin-1"))]},
            forbidden,
            send,
        )
    )
    assert sent[0]["status"] == 401


def test_duplicate_authorization_and_query_token_rejected(client):
    response = client.post(
        "/mcp", headers=[("Authorization", f"Bearer {TEST_TOKEN}")] * 2, json={}
    )
    assert response.status_code == 401
    assert client.post(f"/mcp?token={TEST_TOKEN}", json={}).status_code == 401


def test_bearer_scheme_is_case_insensitive(client):
    response = rpc(client, "tools/list", headers={"Authorization": f"bearer {TEST_TOKEN}"})
    assert response.status_code == 200


@pytest.mark.parametrize("token", [None, "", "short", " " * 32, "\u00ff" * 32, "x" * 513])
def test_missing_or_malformed_server_secret_fails_closed(monkeypatch, token):
    if token is None:
        monkeypatch.delenv("CSOL_BEARER_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CSOL_BEARER_TOKEN", token)
    with pytest.raises(ValueError, match="SERVER_UNAVAILABLE: CSOL_BEARER_TOKEN"):
        server.create_app()


@pytest.mark.parametrize(
    "host", ["csol:8000", "127.0.0.1:8000", "localhost:8000", "[::1]:8000"]
)
def test_explicit_local_and_docker_hosts_allowed(client, host):
    assert rpc(client, "tools/list", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "evil.example:8000", "csol:9000", "csol.evil:8000", "localhost.evil:8000",
        "localhost:8000.evil.example", "127.0.0.1:9000", "",
    ],
)
def test_bad_host_rejected(client, host):
    response = rpc(client, "tools/list", headers={"Host": host})
    assert response.status_code == 421


@pytest.mark.parametrize(
    "origin",
    ["http://csol:8000", "http://127.0.0.1:8000", "http://localhost:8000", "http://[::1]:8000"],
)
def test_explicit_origins_allowed(client, origin):
    assert rpc(client, "tools/list", headers={"Origin": origin}).status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example", "null", "http://csol:9000", "http://localhost.evil:8000",
        "http://localhost:8000.evil.example", "http://localhost:8000@evil.example",
    ],
)
def test_bad_origin_rejected(client, origin):
    response = rpc(client, "tools/list", headers={"Origin": origin})
    assert response.status_code == 403


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        VALID_TURN | {"session_ref": "x" * 129},
        VALID_TURN | {"message_id": "x" * 129},
        VALID_TURN | {"message": "x" * 1001},
        VALID_TURN | {"session_ref": ""},
        VALID_TURN | {"message_id": " "},
        VALID_TURN | {"message": ""},
        VALID_TURN | {"message": "\n\t"},
        VALID_TURN | {"message": 123},
        VALID_TURN | {"message_id": True},
        VALID_TURN | {"session_ref": None},
        VALID_TURN | {"state": "SUCCEEDED"},
        VALID_TURN | {"allowed_actions": ["execute"]},
        VALID_TURN | {"transaction": {"status": "SUCCEEDED"}},
        VALID_TURN | {"unexpected": "value"},
    ],
)
def test_invalid_tool_arguments_are_safe_errors(client, monkeypatch, arguments):
    def forbidden(_):
        pytest.fail("Invalid arguments reached the tool")

    monkeypatch.setattr(client.app.state.controller, "process_turn", forbidden)
    result = call(client, arguments)
    assert result["isError"] is True
    payload = result["structuredContent"]
    assert payload["error_code"] == "INVALID_ARGUMENTS"
    assert payload["session_ref"] is None
    assert payload["allowed_actions"] == []
    assert payload["transaction"] is None
    assert_no_saved_turns(client)


def test_maximum_string_lengths_accepted(client):
    result = call(client, {"session_ref": "s" * 128, "message_id": "i" * 128, "message": "m" * 1000})
    assert result["isError"] is False


@pytest.mark.parametrize(
    "name", ["csol_get_menu", "buy_package", "send_credit", "set_state", "backend", "missing"]
)
def test_unknown_and_backend_tools_rejected(client, monkeypatch, name):
    def forbidden(_):
        pytest.fail("Unknown tool reached the controller")

    monkeypatch.setattr(client.app.state.controller, "process_turn", forbidden)
    result = call(client, name=name)
    assert result["isError"] is True
    assert result["structuredContent"]["error_code"] == "UNKNOWN_TOOL"
    assert result["structuredContent"]["allowed_actions"] == []
    assert result["structuredContent"]["transaction"] is None
    assert_no_saved_turns(client)


def test_unavailable_handler_returns_safe_error_without_details(client, monkeypatch):
    def unavailable(_):
        raise RuntimeError("private implementation detail")

    monkeypatch.setattr(client.app.state.controller, "process_turn", unavailable)
    result = call(client)
    assert result["isError"] is True
    assert result["structuredContent"]["error_code"] == "SERVER_UNAVAILABLE"
    assert result["structuredContent"]["session_ref"] == "demo-test"
    assert result["structuredContent"]["allowed_actions"] == []
    assert "private implementation detail" not in json.dumps(result)


@pytest.mark.parametrize(
    "override",
    [
        {"transaction": {"status": "SUCCEEDED"}},
        {"simulated": False},
        {"safe_to_display": False},
        {"state_version": -1},
        {"state_version": True},
        {"state": "SUCCEEDED"},
        {"customer_reply": "x" * 1001},
        {"unrecognized": "value"},
    ],
)
def test_invalid_outputs_fail_closed(client, monkeypatch, override):
    real_handler = client.app.state.controller.process_turn

    def malformed(turn):
        return real_handler(turn).model_dump() | override

    monkeypatch.setattr(client.app.state.controller, "process_turn", malformed)
    result = call(client)
    assert result["isError"] is True
    assert result["structuredContent"]["error_code"] == "SERVER_UNAVAILABLE"


def test_model_instances_also_revalidated(controller):
    valid = controller.process_turn(TurnInput.model_validate(VALID_TURN)).model_dump()
    malformed = TurnResponse.model_construct(**(valid | {"simulated": False}))
    with pytest.raises(ValidationError, match="simulated"):
        TurnResponse.model_validate(malformed)


def test_oversized_http_body_rejected_with_or_without_content_length(client):
    body = b"x" * (server.MAX_REQUEST_BODY_SIZE + 1)
    response = client.post("/mcp", headers=HEADERS, content=body)
    assert response.status_code == 413
    response = client.post("/mcp", headers=HEADERS, content=iter([body[:100], body[100:]]))
    assert response.status_code == 413


def test_malformed_json_and_wrong_content_type_rejected(client):
    response = client.post(
        "/mcp", headers=HEADERS | {"Content-Type": "application/json"}, content=b"{"
    )
    assert response.status_code == 400
    response = client.post("/mcp", headers=HEADERS, content=b"{}")
    assert response.status_code == 400


@pytest.mark.parametrize("path", ["/chat", "/v1/chat/completions", "/tools/buy_package"])
def test_no_custom_chat_or_transaction_api(client, path):
    assert client.post(path, headers=HEADERS, json={}).status_code == 404


def test_mcp_routing_and_cancel_resume_from_same_file_after_app_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("CSOL_BEARER_TOKEN", TEST_TOKEN)
    db_path = tmp_path / "restart.sqlite3"
    with TestClient(server.create_app(db_path=db_path), base_url=BASE_URL) as first:
        result = call(first, VALID_TURN | {"message": "beli paket"})["structuredContent"]
        assert (result["mode"], result["state"], result["state_version"]) == ("buy_package", "SELECT_PACKAGE", 1)
    with TestClient(server.create_app(db_path=db_path), base_url=BASE_URL) as restarted:
        held = call(restarted, VALID_TURN | {"message_id": "msg-2", "message": "send credit"})["structuredContent"]
        assert held == result
        reset = call(restarted, VALID_TURN | {"message_id": "msg-3", "message": "batal"})["structuredContent"]
        assert (reset["mode"], reset["state"], reset["state_version"]) == ("demo", "IDLE", 2)
        assert reset["transaction"] is None


@pytest.mark.parametrize("patch", [
    {"state": "SUCCEEDED"}, {"version": 99}, {"active_workflow": None}, {"state_version": -1},
])
def test_unsupported_saved_state_fails_closed_without_mutation(client, patch):
    call(client, VALID_TURN | {"message": "buy package"})
    with client.app.state.controller.store.transaction() as connection:
        # Bypass SQLite's CHECK only to exercise detection of corrupted state.
        connection.execute("PRAGMA ignore_check_constraints = ON")
        for field, value in patch.items():
            connection.execute(f"UPDATE sessions SET {field} = ?", (value,))
        before = dict(connection.execute("SELECT * FROM sessions").fetchone())
    result = call(client, VALID_TURN | {"message_id": "next"})
    assert result["isError"] is True
    assert result["structuredContent"]["error_code"] == "SERVER_UNAVAILABLE"
    with client.app.state.controller.store.transaction() as connection:
        assert dict(connection.execute("SELECT * FROM sessions").fetchone()) == before
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_database_path_can_be_injected_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CSOL_BEARER_TOKEN", TEST_TOKEN)
    path = tmp_path / "environment.sqlite3"
    monkeypatch.setenv("CSOL_DB_PATH", str(path))
    with TestClient(server.create_app(), base_url=BASE_URL) as connection:
        assert call(connection)["structuredContent"]["state"] == "IDLE"
    assert path.is_file()
