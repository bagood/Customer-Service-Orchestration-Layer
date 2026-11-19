"""Merge reviewed CSOL settings and a token into an existing Hermes data directory.

Run with the CSOL virtualenv on the Docker host. Never print configuration or
secrets. Existing settings outside the explicitly supplied fragments survive.
"""

import argparse
import os
import re
import tempfile
import uuid
from pathlib import Path

import yaml


def merge_mapping(existing: dict, fragment: dict) -> dict:
    result = dict(existing)
    for key, value in fragment.items():
        if isinstance(value, dict) and key in result:
            if not isinstance(result[key], dict):
                raise ValueError("Cannot merge a mapping into a non-mapping setting")
            result[key] = merge_mapping(result[key], value)
        else:
            result[key] = value
    return result


def read_mapping(path: Path) -> dict:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Expected a YAML mapping")
    return value


def read_token(path: Path) -> str:
    matches = re.findall(r"^\s*(?:export\s+)?CSOL_BEARER_TOKEN\s*=([^\n]*)$", path.read_text(), re.M)
    if len(matches) != 1 or not re.fullmatch(r"[A-Za-z0-9_~-]{32,512}", matches[0]):
        raise ValueError("Token file must contain exactly one valid unquoted CSOL_BEARER_TOKEN")
    return matches[0]


def atomic_private_write(path: Path, content: str) -> None:
    # The temporary file and any backups are private even if the old config was not.
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def install(config: Path, env: Path, token_file: Path, fragments: list[Path]) -> list[Path]:
    token = read_token(token_file)
    original = read_mapping(config)
    merged = original
    for fragment in fragments:
        merged = merge_mapping(merged, read_mapping(fragment))
    config_text = yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)
    if yaml.safe_load(config_text) != merged:
        raise ValueError("Configuration did not round-trip")
    env_text = env.read_text() if env.exists() else ""
    # Preserve all other dotenv lines; remove old definitions of this one key.
    lines = [line for line in env_text.splitlines(keepends=True)
             if not re.match(r"^\s*(?:export\s+)?CSOL_BEARER_TOKEN\s*=", line)]
    new_env = "".join(lines)
    if new_env and not new_env.endswith("\n"):
        new_env += "\n"
    new_env += f"CSOL_BEARER_TOKEN={token}\n"
    backups = []
    suffix = f".stage06-{uuid.uuid4().hex}.bak"
    for path in (config, env):
        if path.exists():
            backup = path.with_name(path.name + suffix)
            atomic_private_write(backup, path.read_text())
            backups.append(backup)
    # Secret first: a crash between writes cannot send an unresolved placeholder.
    atomic_private_write(env, new_env)
    atomic_private_write(config, config_text)
    return backups


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--fragment", type=Path, action="append", required=True)
    args = parser.parse_args()
    backups = install(args.config, args.env, args.token_file, args.fragment)
    print("CSOL settings merged; unrelated model/channel settings preserved.")
    print("Private backups:", ", ".join(str(path) for path in backups))
    print("YAML values preserved; YAML comments/formatting may change. Restart/reload Hermes.")


if __name__ == "__main__":
    main()
