"""Run with the pinned Hermes interpreter and the dedicated 20-credit test wallet."""
import json
import os
import time
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from openai.types.chat import ChatCompletion
from hermes_cli.config import load_config
from hermes_cli.plugins import discover_plugins
from run_agent import AIAgent
from tools.mcp_tool_discovery import register_mcp_servers

PREFIX = "mcp__csol__"
GLOBAL = {"request_return_to_landing", "resolve_return_to_landing"}
START = ("identification_instruction", "record_name")
MENU = ("menu_instruction", "select_service")
MATCH = ("preference_instruction", "match_package")
BUY = ("purchase_instruction", "confirm_package")
DETOUR = ("detour_instruction", "confirm_credit_detour")
CREDIT = ("credit_instruction", "add_credits")


class Chat:
    """Use the real Hermes agent loop with deterministic provider responses."""
    def __init__(self):
        self.session = "acceptance-" + uuid4().hex
        self.history = []
        self.agent = AIAgent(
            api_key="fixture-only", base_url="http://127.0.0.1:1/v1", model="fixture",
            provider="custom", api_mode="chat_completions", quiet_mode=True, skip_memory=True,
            skip_background_review=True, enabled_toolsets=["mcp-csol"], max_iterations=8,
            platform="cli", session_id=self.session, load_soul_identity=True,
        )

    def turn(self, message, script):
        replies = iter(script)
        observed = []

        def provider(request, **kwargs):
            pair, tool, arguments = next(replies)
            schemas = {item["function"]["name"].removeprefix(PREFIX): item["function"]
                       for item in request["tools"]}
            assert set(schemas) == {*pair, *GLOBAL}, list(schemas)
            assert all("binding" not in schema["parameters"]["properties"] for schema in schemas.values())
            if not observed:
                assert request["tool_choice"]["function"]["name"] == PREFIX + pair[0]
            if observed and observed[-1] == "tool_search":
                bridge = next(m for m in reversed(request["messages"]) if m["role"] == "tool")
                assert "currently presented CSOL tools" in bridge["content"]
                assert "confirm_package" not in bridge["content"]
            assistant = {"role": "assistant", "content": "Asked the current CSOL question."}
            if tool:
                assistant.update(content=None, tool_calls=[{
                    "id": "call_" + uuid4().hex, "type": "function",
                    "function": {"name": tool if tool == "tool_search" else PREFIX + tool,
                                 "arguments": json.dumps(arguments)},
                }])
            observed.append(tool)
            return ChatCompletion(id=uuid4().hex, model="fixture", object="chat.completion", created=int(time.time()),
                                  choices=[{"index": 0, "message": assistant,
                                            "finish_reason": "tool_calls" if tool else "stop"}])

        self.agent._interruptible_api_call = provider
        self.agent._interruptible_streaming_api_call = provider
        raw_results = []
        self.agent.tool_complete_callback = lambda call_id, name, args, result: raw_results.append(result)
        result = self.agent.run_conversation(message, conversation_history=self.history)
        assert result["completed"] and len(observed) == len(script), (result.get("error"), observed)
        self.history = result["messages"]
        tool_results = []
        for raw in raw_results:
            wrapper = json.loads(raw)
            tool_results.append(json.loads(wrapper["result"]) if "result" in wrapper else wrapper)
        return tool_results


def main():
    load_dotenv(Path(os.environ["HERMES_HOME"]) / ".env")
    discover_plugins()
    assert register_mcp_servers(load_config()["mcp_servers"]), "CSOL discovery failed"
    first, second = Chat(), Chat()
    result = first.turn("Hello", [(START, START[0], {}), (START, None, {})])
    assert result[-1]["step"] == "identification"
    result = first.turn("Call me Ari", [(START, START[0], {}), (START, START[1], {"revision": 0, "name": "Ari"}),
                                        (MENU, None, {})])
    assert result[-1]["step"] == "intent_classification"
    other = second.turn("Hello", [(START, START[0], {}), (START, "tool_search", {"query": "purchase"}),
                                  (START, None, {})])
    assert other[0]["revision"] == 0

    route = [
        ("I want a package", MENU, {"service": "buy_package"}, MATCH, "service_selected"),
        ("I want streaming", MATCH, {"benefit": os.getenv("CSOL_TEST_BENEFIT", "streaming")}, BUY, "offer_selected"),
        ("Yes, buy it", BUY, {"answer": "yes"}, DETOUR, "insufficient_funds"),
        ("Yes, add credits", DETOUR, {"answer": "yes"}, CREDIT, "top_up_selected"),
        ("Add 30", CREDIT, {"amount": 30}, BUY, "credited"),
        ("Yes, buy that package now", BUY, {"answer": "yes"}, MENU, "purchased"),
    ]
    for revision, (message, before, args, after, outcome) in enumerate(route, 1):
        results = first.turn(message, [(before, before[0], {}), (before, before[1], {"revision": revision, **args}),
                                       (after, None, {})])
        assert results[0]["revision"] == revision
        action = results[-1]
        assert action["outcome"] == outcome and action["revision"] == revision + 1, action
        if outcome == "credited":
            assert action["receipt"]["balance"] == 50 and action["instruction"]["action"] == "confirm_package"
        if outcome == "purchased":
            assert action["receipt"]["balance"] == 0
    print(f"Hermes journey passed for {first.session}. Independent chat {second.session} stayed at identification.")


if __name__ == "__main__":
    main()
