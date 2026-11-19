"""Deployment config writes must preserve existing credentials and fail before mutation."""

import importlib.util
import stat
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("merge_hermes_config", ROOT / "scripts/merge_hermes_config.py")
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)


def test_merge_preserves_model_channel_other_mcp_and_secrets(tmp_path):
    config, env, token = (tmp_path / name for name in ("config.yaml", ".env", "token.env"))
    original = {
        "model": {"provider": "existing", "api_key": "synthetic-model-secret"},
        "platforms": {"telegram": {"token": "synthetic-channel-secret"}},
        "platform_toolsets": {"telegram": ["existing-toolset"]},
        "agent": {"max_turns": 10},
        "mcp_servers": {"existing": {"url": "http://existing/mcp"}},
    }
    config.write_text(yaml.safe_dump(original))
    old_env = "# Keep comments\nMODEL_KEY=synthetic-key\nexport CSOL_BEARER_TOKEN=old\nOTHER=value\n"
    env.write_text(old_env)
    secret = "synthetic-stage06-" + "x" * 32
    token.write_text(f"CSOL_BEARER_TOKEN={secret}\n")
    fragments = [ROOT / "hermes/mcp-config.example.yaml", ROOT / "hermes/customer-service-profile.example.yaml"]
    backups = merge.install(config, env, token, fragments)
    result = yaml.safe_load(config.read_text())
    for key in ("model", "platforms"):
        assert result[key] == original[key]
    assert result["agent"]["max_turns"] == 10
    assert result["tools"]["tool_search"]["enabled"] == "off"
    assert result["platform_toolsets"] == {"telegram": ["existing-toolset"], "cli": ["csol"]}
    assert result["mcp_servers"]["existing"] == original["mcp_servers"]["existing"]
    csol = result["mcp_servers"]["csol"]
    assert csol["headers"]["Authorization"] == "Bearer ${CSOL_BEARER_TOKEN}"
    assert csol["url"] == "http://csol:8000/mcp"
    assert csol["tools"] == {"include": ["csol_process_turn"], "resources": False, "prompts": False}
    assert csol["supports_parallel_tool_calls"] is False
    assert 0 < csol["connect_timeout"] <= csol["timeout"] <= 60
    assert env.read_text() == old_env.replace("export CSOL_BEARER_TOKEN=old\n", "") + f"CSOL_BEARER_TOKEN={secret}\n"
    assert secret not in config.read_text()
    assert yaml.safe_load(backups[0].read_text()) == original
    assert backups[1].read_text() == old_env
    for path in [config, env, *backups]:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # Reapplying cannot duplicate dotenv definitions or erase unrelated settings.
    merge.install(config, env, token, fragments)
    assert yaml.safe_load(config.read_text()) == result
    assert env.read_text().count("CSOL_BEARER_TOKEN=") == 1


@pytest.mark.parametrize("bad_input", ["token", "config", "fragment", "collision"])
def test_invalid_merge_inputs_never_change_either_persisted_file(tmp_path, bad_input):
    config, env, token, fragment = (tmp_path / name for name in ("config.yaml", ".env", "token.env", "fragment.yaml"))
    config.write_text("model: {provider: keep}\nmcp_servers: {}\n")
    env.write_text("MODEL_KEY=synthetic-keep\n")
    token.write_text("CSOL_BEARER_TOKEN=" + "x" * 32 + "\n")
    fragment.write_text("mcp_servers: {csol: {enabled: true}}\n")
    if bad_input == "token":
        token.write_text("CSOL_BEARER_TOKEN=short\n")
    elif bad_input == "config":
        config.write_text("- invalid\n")
    elif bad_input == "fragment":
        fragment.write_text("- invalid\n")
    else:
        config.write_text("mcp_servers: invalid\n")
    before = (config.read_bytes(), env.read_bytes())
    with pytest.raises(ValueError):
        merge.install(config, env, token, [fragment])
    assert (config.read_bytes(), env.read_bytes()) == before
    assert not list(tmp_path.glob("*.bak"))


def test_ambiguous_token_file_is_rejected(tmp_path):
    token = tmp_path / "token.env"
    token.write_text("CSOL_BEARER_TOKEN=" + "x" * 32 + "\nCSOL_BEARER_TOKEN=short\n")
    with pytest.raises(ValueError):
        merge.read_token(token)
