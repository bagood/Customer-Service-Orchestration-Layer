import pytest

from csol.config import load_configuration
from csol.controller import Controller
from csol.store import Store


@pytest.fixture
def controller(tmp_path):
    return Controller(Store(tmp_path / "state.sqlite3"), load_configuration())
