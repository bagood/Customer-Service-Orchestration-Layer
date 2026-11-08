from pathlib import Path

import yaml


def test_example_configuration_parses():
    """Read the real sample with PyYAML's safe loader, independent of cwd."""
    config_path = Path(__file__).resolve().parents[1] / "configs" / "example.yaml"
    with config_path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)

    assert config["project"]["name"] == "csol"
    assert type(config["project"]["stage"]) is int
    assert config["project"]["stage"] == 0
    assert config["project"]["mode"] == "offline"
