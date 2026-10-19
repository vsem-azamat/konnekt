"""Parsing `!mute` durations: what a moderator types is what the member gets."""

import datetime

import pytest
from app.presentation.telegram.utils.other import calculate_mute_duration


@pytest.mark.parametrize(
    ("text", "time", "unit"),
    [
        ("!mute", 5, "m"),
        ("/mute 10", 10, "m"),
        ("!mute 2h", 2, "h"),
        ("!mute 3 d", 3, "d"),
        ("/mute@konnekt_cz_bot 1w", 1, "w"),
        ("!mute 2H", 2, "h"),
        ("!mute 366d", 366, "d"),
    ],
)
def test_accepted_durations(text: str, time: int, unit: str) -> None:
    duration = calculate_mute_duration(text)

    assert (duration.time, duration.unit) == (time, unit)


@pytest.mark.parametrize(
    "text",
    [
        # Telegram treats an until_date under 30 seconds away as forever, so a
        # zero would be a permanent mute reported as a momentary one.
        "!mute 0",
        "!mute 0h",
        # A typo used to fall back to five minutes without a word.
        "!mute abc",
        "!mute 5x",
        "!mute 5m please",
        # Past 366 days Telegram reads the until_date as forever too.
        "!mute 367d",
        "!mute 53w",
        "!mute 9000h",
    ],
)
def test_refused_durations(text: str) -> None:
    with pytest.raises(ValueError, match="(?i)mute"):
        calculate_mute_duration(text)


def test_until_date_is_in_the_future() -> None:
    duration = calculate_mute_duration("!mute 1h")

    remaining = duration.until_date - datetime.datetime.now(datetime.UTC)
    assert datetime.timedelta(minutes=59) < remaining <= datetime.timedelta(hours=1)
