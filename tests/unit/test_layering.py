"""The shared feature packages do not reach into the bot's presentation layer.

app.moderation and app.chats serve the web API and the control plane as well
as the bot; importing app.presentation from them made the shared layer depend
on one of its callers.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
SHARED = ["chats", "core", "db", "mcp", "moderation", "webapi"]


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


@pytest.mark.parametrize("package", SHARED)
def test_a_shared_package_does_not_import_the_bot_presentation(package: str) -> None:
    offenders = {
        str(path.relative_to(APP)): sorted(name for name in _imports(path) if name.startswith("app.presentation"))
        for path in (APP / package).rglob("*.py")
    }

    assert {path: names for path, names in offenders.items() if names} == {}
