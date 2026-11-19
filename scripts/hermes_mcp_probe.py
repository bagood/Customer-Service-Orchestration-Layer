"""Run INSIDE the existing Hermes v0.23.0 installation, using its own MCP bridge.

This is a deterministic protocol/registry probe, separate from the model-driven
CLI journey. It reads the persisted Hermes config and secret, never a test stub.
"""

import json
import uuid

from agent.secret_scope import get_secret
from tools.mcp_tool_config import _interpolate_env_vars, _load_mcp_config, _require_rendered_remote
from tools.mcp_tool_discovery import discover_mcp_tools
from tools.mcp_tool_lifecycle import shutdown_mcp_servers
from tools.mcp_tool_registration import _make_tool_filter
from tools.registry import registry


def main() -> None:
    cfg = _load_mcp_config()["csol"]
    assert cfg["url"] == "http://csol:8000/mcp"
    token = get_secret("CSOL_BEARER_TOKEN", None)
    assert token and str(cfg["headers"]["Authorization"]) == f"Bearer {token}"
    _require_rendered_remote("csol", cfg)
    print("Persisted config and Authorization interpolation: PASS (secret redacted)")
    try:
        _require_rendered_remote("missing-test", _interpolate_env_vars({
            "url": "http://csol:8000/mcp",
            "headers": {"Authorization": "Bearer ${CSOL_STAGE06_DELIBERATELY_UNSET}"},
        }))
    except ValueError:
        print("Unset remote credential fails closed: PASS")
    else:
        raise AssertionError("Missing environment variable was accepted")
    predicate = _make_tool_filter("csol", cfg)
    assert predicate("csol_process_turn")
    assert not predicate("_mock_buy_package") and not predicate("set_state")
    assert cfg["supports_parallel_tool_calls"] is False
    assert cfg["tools"]["resources"] is False and cfg["tools"]["prompts"] is False
    try:
        names = discover_mcp_tools(allowed_mcp_names=["csol"])
        expected = "mcp__csol__csol_process_turn"
        assert names == [expected], names
        assert registry.get_tool_names_for_toolset("mcp-csol") == [expected]
        # Check actual model definitions for the CLI allowlist, including any core tools.
        from model_tools import get_tool_definitions
        definitions = get_tool_definitions(enabled_toolsets=["csol"], quiet_mode=True)
        offered = sorted(d["function"]["name"] for d in definitions)
        assert offered == [expected], offered
        print("Hermes discovery/CLI tool surface:", json.dumps(offered))
        session_ref = "demo-hermes-probe-" + uuid.uuid4().hex
        result = registry.dispatch(expected, {
            "session_ref": session_ref, "message_id": "probe-01", "message": "hello",
        })
        if isinstance(result, str):
            result = json.loads(result)
        # Hermes retains the text JSON when the server dual-emits structured content.
        payload = result.get("structuredContent") or result.get("structured_content") or result["result"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        assert payload["session_ref"] == session_ref
        assert payload["state"] == "IDLE" and payload["transaction"] is None
        print("Hermes tools/call: PASS; synthetic session:", session_ref)
        print("Hermes MCP probe: PASS")
    finally:
        shutdown_mcp_servers()


if __name__ == "__main__":
    main()
