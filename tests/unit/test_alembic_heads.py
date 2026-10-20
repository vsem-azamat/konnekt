"""One migration history: two branches from one parent cannot both be upgraded to."""

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

pytestmark = pytest.mark.unit


def test_there_is_one_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    assert len(script.get_heads()) == 1, script.get_heads()
