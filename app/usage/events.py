"""What the Mini App may say it did, and in which words.

The one list of events. The client's twin is `web/src/lib/track.ts`; a name or
a property missing here is dropped by the server and counted, so the two
cannot drift without the drop counter saying so.

A property is a number, a yes or no, or a word of ours (`WORD`): never text a
person typed, never an id. What somebody searched for is the catalog's to
keep, and it already does.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator

# A word of ours: a tab, a section, where a tap came from.
WORD = re.compile(r"[a-z0-9_:-]{1,32}")
# A launch's start parameter may be longer: an article's is `site_article_<slug>`.
_LAUNCH = re.compile(r"[a-z0-9_:-]{1,64}")
# A route pattern, as the error reports name a screen (app/webapi/routes/client_errors.py).
SCREEN = r"^/[A-Za-z0-9/_:.\-]{0,119}$"
MAX_NUMBER = 100_000
# 2100-01-01 in milliseconds: past it a clock is not a clock, and Python cannot date it.
MAX_AT = 4_102_444_800_000
# A helper's card on konnekt.cz: «Написать в Konnekt» opens `helper-<id>`, and the
# catalog's /open passes it on only for a helper the site shows (web/src/lib/startParam.ts).
_HELPER = re.compile(r"^helper-\d+$")
SITE_HELPER = "site_helper"
_DIGITS = re.compile(r"\d{4,}")


def launch_word(start_param: str | None) -> str | None:
    """What brought a launch, as a word of ours: never an id.

    `helper-123` is «a helper's card on the site» (`site_helper`), whoever's it
    was; `uni-cvut` and `site_hero` are kept as they are. Anything else
    carrying a long number is not kept at all.
    """
    if not start_param:
        return None
    if _HELPER.fullmatch(start_param):
        return SITE_HELPER
    if _DIGITS.search(start_param) or not _LAUNCH.fullmatch(start_param.lower()):
        return None
    return start_param.lower()


Name = Literal[
    # The first event of a session: on launch, and again after a long break (`resumed`).
    "session_start",
    # Every half minute while the app is on screen; what sessions, time and «online» are counted from.
    "heartbeat",
    "screen_view",
    "tab_tap",
    "search_submit",
    "filter_change",
    "helper_open",
    "contact_tap",
    "offer_start",
    "request_send",
    "chat_open",
    "partner_tap",
]

# The properties each event may carry. Anything else in `props` is dropped with the event.
PROPS: dict[str, frozenset[str]] = {
    "session_start": frozenset({"resumed"}),
    "heartbeat": frozenset(),
    "screen_view": frozenset(),
    "tab_tap": frozenset({"tab"}),
    "search_submit": frozenset({"results", "filters"}),
    "filter_change": frozenset({"filter"}),
    "helper_open": frozenset({"from"}),
    "contact_tap": frozenset({"from"}),
    "offer_start": frozenset({"from"}),
    "request_send": frozenset(),
    "chat_open": frozenset({"section"}),
    "partner_tap": frozenset({"from"}),
}

Value = bool | int | str


class Event(BaseModel):
    name: Name
    # Milliseconds since the epoch, by the client's clock.
    at: Annotated[int, Field(ge=0, le=MAX_AT)]
    # Order within the session, so two events in one millisecond keep theirs.
    seq: Annotated[int, Field(ge=0, le=1_000_000)]
    session: Annotated[str, Field(pattern=r"^[A-Za-z0-9-]{8,36}$")]
    screen: Annotated[str, Field(pattern=SCREEN)] | None = None
    props: dict[str, Value] = Field(default_factory=dict, max_length=4)

    @field_validator("screen")
    @classmethod
    def _a_pattern(cls, screen: str | None) -> str | None:
        """A route pattern names no one: `/helper/:id`, never `/helper/123`."""
        if screen is not None and any(part.isdigit() for part in screen.split("/")):
            raise ValueError("a screen is a route pattern, not an address")
        return screen

    @field_validator("props")
    @classmethod
    def _ours(cls, props: dict[str, Value], info: Any) -> dict[str, Value]:
        allowed = PROPS.get(info.data.get("name", ""), frozenset())
        for key, value in props.items():
            if key not in allowed:
                raise ValueError(f"{key} is not a property of this event")
            if isinstance(value, str) and not WORD.fullmatch(value):
                raise ValueError(f"{key} is not one of our words")
            if isinstance(value, int) and not isinstance(value, bool) and not 0 <= value <= MAX_NUMBER:
                raise ValueError(f"{key} is out of range")
        return props
