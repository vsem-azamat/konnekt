"""One head: two branches of migrations would leave `alembic upgrade head` refusing to run on deploy."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]


def test_the_migrations_have_one_head() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))

    assert len(ScriptDirectory.from_config(config).get_heads()) == 1
