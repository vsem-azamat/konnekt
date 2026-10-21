"""A failure leaves a line that says what failed.

`error=str(err)` was the habit: it keeps the message and drops the class and the
stack, and on a broad `except Exception` those are the whole diagnosis. Reading
the code is how this is held, because nothing at runtime notices a log call that
says too little.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
LEVELS = {"debug", "info", "warning", "error", "exception", "critical"}

# Broad handlers that are not failures to report: the answer is the handling.
DELIBERATE = {
    # logging's own contract: a handler that fails hands the record to handleError.
    ("core/alerts.py", "emit"),
    # A failing alert send logs its class at warning, so it cannot alert about itself.
    ("core/alerts.py", "_run"),
    # About the audience, whose ids and names stay out of the logs: a database
    # error's text carries the statement's parameters, so only the class goes in.
    ("ads/desk.py", "_blocked"),
    ("presentation/telegram/middlewares/audience.py", "__call__"),
    # Text that does not parse as a duration is the user's mistake and is told so.
    ("presentation/telegram/handlers/moderation/mute.py", "mute_user"),
}


def _is_logger_call(node: ast.AST) -> ast.Call | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LEVELS:
        owner = node.func.value
        if isinstance(owner, ast.Name) and owner.id in {"logger", "log"}:
            return node
    return None


def _handlers() -> list[tuple[str, ast.ExceptHandler, str]]:
    """Every handler, with the innermost function around it."""
    found: list[tuple[str, ast.ExceptHandler, str]] = []

    def visit(node: ast.AST, file: str, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ExceptHandler):
                found.append((file, child, function))
            name = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else function
            visit(child, file, name)

    for path in sorted(APP.rglob("*.py")):
        visit(ast.parse(path.read_text()), path.relative_to(APP).as_posix(), "<module>")
    return found


def _where(file: str, handler: ast.ExceptHandler) -> str:
    return f"app/{file}:{handler.lineno}"


def _keeps_the_traceback(call: ast.Call) -> bool:
    return call.func.attr == "exception" or any(k.arg == "exc_info" for k in call.keywords)  # ty: ignore[unresolved-attribute]


def test_a_broad_except_reports_its_traceback_or_raises() -> None:
    silent = []
    for file, handler, function in _handlers():
        broad = handler.type is None or (
            isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"}
        )
        if not broad or (file, function) in DELIBERATE:
            continue
        nodes = [n for stmt in handler.body for n in ast.walk(stmt)]
        if any(isinstance(n, ast.Raise) for n in nodes):
            continue
        calls = [c for n in nodes if (c := _is_logger_call(n))]
        # A refusal Telegram gives routinely (a message already gone, a user who
        # blocked the bot) is a warning that names its class; anything worse
        # keeps the stack.
        refusal = bool(calls) and all(
            c.func.attr in {"debug", "info", "warning"} and any(k.arg == "error_type" for k in c.keywords)  # ty: ignore[unresolved-attribute]
            for c in calls
        )
        if not (refusal or any(_keeps_the_traceback(c) for c in calls)):
            silent.append(_where(file, handler))
    assert silent == [], "broad except without exc_info or a raise"


def test_a_logged_error_names_its_class() -> None:
    """`error=str(err)` alone is a message with no class and no stack."""
    bare = []
    for path in sorted(APP.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            call = _is_logger_call(node)
            if call is None:
                continue
            names = {k.arg for k in call.keywords}
            error = next((k.value for k in call.keywords if k.arg == "error"), None)
            says_str = isinstance(error, ast.Call) and getattr(error.func, "id", "") == "str"
            if says_str and not names & {"error_type", "exc_info"} and call.func.attr != "exception":  # ty: ignore[unresolved-attribute]
                bare.append(f"app/{path.relative_to(APP).as_posix()}:{call.lineno}")
    assert bare == [], "error= without error_type or exc_info"


def test_the_allowance_names_something_that_exists() -> None:
    """A stale entry would excuse a handler nobody meant to."""
    assert {(file, name) for file, _, name in _handlers()} >= DELIBERATE
