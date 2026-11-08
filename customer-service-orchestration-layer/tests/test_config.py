from pathlib import Path
from shutil import copytree

import pytest
import yaml
from pydantic import ValidationError

from csol.config import DEFAULT_CONFIG_DIR, load_configuration
from csol.server import create_app


def test_example_configuration_parses():
    """Read the real sample with PyYAML's safe loader, independent of cwd."""
    config_path = Path(__file__).resolve().parents[1] / "configs" / "example.yaml"
    with config_path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)

    assert config["project"]["name"] == "csol"
    assert type(config["project"]["stage"]) is int
    assert config["project"]["stage"] == 0
    assert config["project"]["mode"] == "offline"


def test_versioned_workflows_and_catalog_load():
    config = load_configuration()
    assert set(config.routing.routes) == {"buy_package", "send_credit"}
    assert config.workflows["buy_package"].states == [
        "SELECT_PACKAGE", "ENTER_BALANCE", "CONFIRM_PURCHASE", "EXECUTE_PURCHASE", "FEEDBACK",
    ]
    assert config.workflows["send_credit"].states == ["ENTER_MSISDN"]
    assert {workflow.version for workflow in config.workflows.values()} == {1}
    assert {name: item.price_idr for name, item in config.workflows["buy_package"].catalog.items()} == {
        "A": 10000, "B": 20000,
    }
    assert config.workflows["send_credit"].catalog == {}


@pytest.mark.parametrize("relative_path,patch", [
    ("global.yaml", {"routes": {"buy_package": ["beli paket"]}}),
    ("global.yaml", {"routes": {"buy_package": [], "send_credit": ["send credit"]}}),
    ("global.yaml", {"routes": {"buy_package": ["buy package"], "send_credit": [" BUY  PACKAGE "]}}),
    ("global.yaml", {"routes": {"buy_package": [" "], "send_credit": ["send credit"]}}),
    ("global.yaml", {"routes": {"buy_package": ["buy package"], "refund": ["refund"]}}),
    ("global.yaml", {"execute": "anything"}),
    ("workflows/buy_package.v1.yaml", {"workflow": "send_credit"}),
    ("workflows/buy_package.v1.yaml", {"version": 2}),
    ("workflows/buy_package.v1.yaml", {"version": True}),
    ("workflows/buy_package.v1.yaml", {"states": ["ENTER_MSISDN"]}),
    ("workflows/buy_package.v1.yaml", {"states": ["SELECT_PACKAGE", "EXECUTE_PURCHASE"]}),
    ("workflows/buy_package.v1.yaml", {"catalog": {}}),
    ("workflows/buy_package.v1.yaml", {"catalog": {"A": {"price_idr": -1}, "B": {"price_idr": 20000}}}),
    ("workflows/buy_package.v1.yaml", {"catalog": {"A": {"price_idr": "10000"}, "B": {"price_idr": 20000}}}),
    ("workflows/buy_package.v1.yaml", {"catalog": {"A": {"price_idr": 1}, "B": {"price_idr": 20000}}}),
    ("workflows/send_credit.v1.yaml", {"states": ["IDLE"]}),
    ("workflows/send_credit.v1.yaml", {"catalog": {"A": {"price_idr": 10000}}}),
    ("workflows/send_credit.v1.yaml", {"backend": "execute"}),
])
def test_invalid_configuration_prevents_startup_before_database_creation(monkeypatch, tmp_path, relative_path, patch):
    config_dir = copytree(DEFAULT_CONFIG_DIR, tmp_path / "configs")
    path = config_dir / relative_path
    definition = yaml.safe_load(path.read_text(encoding="utf-8"))
    path.write_text(yaml.safe_dump(definition | patch), encoding="utf-8")
    monkeypatch.setenv("CSOL_BEARER_TOKEN", "config-test-" + "x" * 32)
    db_path = tmp_path / "not-created.sqlite3"
    with pytest.raises((ValidationError, ValueError)):
        create_app(db_path=db_path, config_dir=config_dir)
    assert not db_path.exists()


@pytest.mark.parametrize("relative_path,content,error", [
    ("global.yaml", "routes: [", yaml.YAMLError),
    ("global.yaml", "!!python/object/apply:os.system ['never run']", yaml.YAMLError),
    ("workflows/send_credit.v1.yaml", None, FileNotFoundError),
])
def test_unreadable_or_unsafe_configuration_fails(monkeypatch, tmp_path, relative_path, content, error):
    config_dir = copytree(DEFAULT_CONFIG_DIR, tmp_path / "configs")
    path = config_dir / relative_path
    if content is None:
        path.unlink()
    else:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("CSOL_BEARER_TOKEN", "config-test-" + "x" * 32)
    db_path = tmp_path / "not-created.sqlite3"
    with pytest.raises(error):
        create_app(db_path=db_path, config_dir=config_dir)
    assert not db_path.exists()
