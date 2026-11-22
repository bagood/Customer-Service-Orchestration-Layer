"""Dedicated CSOL profile middleware for Hermes v2026.9.24."""
import json
import logging
import os
import time
from copy import deepcopy

import httpx
import jwt

PREFIX = "mcp__csol__"
logger = logging.getLogger(__name__)


def binding(session_id, turn_id):
    if not session_id or not turn_id:
        raise ValueError("Missing Hermes session or turn ID")
    # This profile uses a single explicitly bound test wallet. A channel adapter
    # can supply its authenticated customer ID here for a multi-account deployment.
    return jwt.encode({"aud": "csol", "sub": session_id, "customer": os.environ["CSOL_CUSTOMER_ID"],
                       "turn": turn_id, "exp": int(time.time()) + 60}, os.environ["CSOL_BINDING_KEY"], algorithm="HS256")


def scope(session_id, turn_id):
    result = httpx.get(os.environ["CSOL_URL"].rstrip("/") + "/scope",
                       headers={"Authorization": "Bearer " + binding(session_id, turn_id)}, timeout=5)
    result.raise_for_status()
    return [PREFIX + name for name in result.json()["allowed_tools"]]


def scoped_error(message):
    # Hermes includes its stable registry in this internally generated error.
    # Narrow the copy sent to the provider on subsequent inference calls.
    if message.get("role") == "tool":
        field = "content"
    elif message.get("type") == "function_call_output":
        field = "output"
    else:
        return message
    content = message.get(field)
    if isinstance(content, str) and "does not exist. Available tools:" in content:
        return {**message, field: "That tool is unavailable. Use the currently presented CSOL tools."}
    return message


def filter_request(request, session_id, turn_id, **kwargs):
    # Hermes runs this before every provider call, including calls within a turn.
    # Its middleware dispatcher fails open on exceptions, so return an empty
    # tool list explicitly when CSOL or the profile configuration is unavailable.
    filtered = dict(request, tools=[])
    for field in ("messages", "input"):
        if isinstance(request.get(field), list):
            filtered[field] = [scoped_error(m) if isinstance(m, dict) else m for m in request[field]]
    try:
        names = scope(session_id, turn_id)
        for tool in request.get("tools") or []:
            function = tool.get("function", tool)
            if function.get("name") not in names:
                continue
            visible = deepcopy(tool)
            schema = visible.get("function", visible)
            params = schema.get("parameters", schema.get("input_schema", {}))
            params.get("properties", {}).pop("binding", None)
            params["required"] = [p for p in params.get("required", []) if p != "binding"]
            filtered["tools"].append(visible)
        if len(filtered["tools"]) != 4:
            raise ValueError("Expected all four CSOL tools in the eager catalog")
        # Hermes' Chat Completions and Responses transports both support
        # choosing the instruction function on the first inference of a turn.
        messages = request.get("messages") or request.get("input") or []
        if messages and isinstance(messages[-1], dict) and messages[-1].get("role") == "user":
            if "messages" in request:
                filtered["tool_choice"] = {"type": "function", "function": {"name": names[0]}}
            else:
                filtered["tool_choice"] = {"type": "function", "name": names[0]}
    except Exception as exc:
        filtered.pop("tool_choice", None)
        filtered["tools"] = []
        logger.error("CSOL tool scope unavailable (%s)", type(exc).__name__)
    return {"request": filtered}


def bind_request(tool_name, args, session_id, turn_id, **kwargs):
    if tool_name.startswith(PREFIX):
        bound = dict(args)
        bound.pop("binding", None)
        try:
            bound["binding"] = binding(session_id, turn_id)
        except (KeyError, ValueError):
            pass
        return {"args": bound}


def restrict_execution(tool_name, args, next_call, **kwargs):
    # The pinned Hermes agent wraps tool execution before its search bridge
    # can expand the unfiltered registry (including a guessed bridge call).
    if not tool_name.startswith(PREFIX):
        return json.dumps({"error": "Use the currently presented CSOL tools."})
    return next_call(args)


def register(ctx):
    ctx.register_middleware("llm_request", filter_request)
    ctx.register_middleware("tool_request", bind_request)
    ctx.register_middleware("tool_execution", restrict_execution)
