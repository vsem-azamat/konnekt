"""The public endpoints' answers, remembered for a minute.

Both aggregate over messages and member snapshots, and they answer strangers,
who may ask in a loop. A figure a minute old is what any visitor would have
seen anyway. A console edit forgets them, so an operator who changes a chat
sees the public page change; edits from the bot process (approval, titles)
show within the minute.

Per process: webapi runs one uvicorn worker. With more, each would keep its
own answers, and forgetting would reach only the worker that took the edit.
The values are shared between requests and must not be changed in place.
"""

from __future__ import annotations

import time

SECONDS = 60
_answers: dict[str, tuple[float, object]] = {}


def remembered(key: str) -> object | None:
    entry = _answers.get(key)
    if entry is None or entry[0] <= time.monotonic():
        return None
    return entry[1]


def remember(key: str, value: object) -> None:
    _answers[key] = (time.monotonic() + SECONDS, value)


def forget() -> None:
    _answers.clear()
