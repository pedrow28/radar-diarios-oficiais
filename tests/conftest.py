from pathlib import Path

import pytest


@pytest.fixture
def dir_fixtures() -> Path:
    return Path(__file__).parent / "fixtures"
