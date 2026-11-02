"""The audience over time: bars that end yesterday, unknown days apart from empty ones, and who each step counts."""

import datetime

import pytest
from app.audience import record, trends
from app.audience.record import ESTIMATE, Person, Touchpoint
from app.db.models import Chat, JoinCaptcha, Message

pytestmark = pytest.mark.unit

TODAY = datetime.date(2026, 11, 20)


def at(day: datetime.date, hour: int = 12) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time(hour))


def ago(days: int) -> datetime.date:
    return TODAY - datetime.timedelta(days=days)


ANNA = Person(id=1, first_name="Anna", language_code="ru")
TARAS = Person(id=2, first_name="Тарас", language_code="uk")
JAN = Person(id=3, first_name="Jan", language_code="cs")
GUESS = Person(id=4, first_name="Guess", partial=True)


def _captcha(user_id: int, chat_id: int, day: datetime.date, status: str) -> JoinCaptcha:
    captcha = JoinCaptcha(
        chat_id=chat_id,
        user_id=user_id,
        user_chat_id=user_id,
        status=status,
        answer="🍎",
        options=["🍎"],
        attempts_left=0,
        expires_at=at(day, 13),
        created_at=at(day, 11),
    )
    captcha.resolved_at = at(day, 12)
    return captcha


@pytest.fixture
async def audience(session_maker):
    async with session_maker() as db:
        db.add(Chat(id=-100, title="ČVUT FIT"))
        db.add(Chat(id=-200, title="Studenti VŠE"))
        # Anna: asked to join ČVUT FIT, then started the bot and opened the Mini App.
        db.add(_captcha(ANNA.id, -100, ago(10), JoinCaptcha.STATUS_PASSED))
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=at(ago(9)), started=Touchpoint.MAIN_BOT, source="welcome")
        await record.seen(db, ANNA, Touchpoint.MINI_APP, at=at(ago(2)))
        # Taras: wrote in VŠE long ago, opened the Mini App without /start.
        message = Message(chat_id=-200, user_id=TARAS.id, message_id=1, message_info={})
        message.timestamp = at(ago(60))
        db.add(message)
        await record.seen(db, TARAS, Touchpoint.MINI_APP, at=at(ago(40)))
        # Jan: came by a link, never in a chat; started, then blocked the bot yesterday.
        await record.seen(db, JAN, Touchpoint.MAIN_BOT, at=at(ago(3)), started=Touchpoint.MAIN_BOT, source="uni-cvut")
        await record.blocked(db, JAN.id, Touchpoint.MAIN_BOT, at=at(ago(1)))
        # Somebody turned away at the door, and somebody let in today.
        db.add(_captcha(90, -100, ago(5), JoinCaptcha.STATUS_FAILED))
        db.add(_captcha(91, -100, TODAY, JoinCaptcha.STATUS_PASSED))
        # A guess of the backfill, never confirmed.
        await record.seen(db, GUESS, Touchpoint.MAIN_BOT, at=at(ago(200)), source=ESTIMATE, replay=True)
        await db.commit()


def test_bars_end_yesterday_and_a_long_period_is_in_weeks():
    days = trends.bars(7, TODAY)
    assert len(days) == 14
    assert days[-1] == (ago(1), ago(1))
    assert days[0] == (ago(14), ago(14))

    weeks = trends.bars(90, TODAY)
    assert len(weeks) == 26
    assert weeks[-1] == (ago(7), ago(1))
    assert weeks[-2] == (ago(14), ago(8))


async def test_each_metric_is_counted_on_its_day(session_maker, audience):
    async with session_maker() as db:
        answer = await trends.trends(db, days=30, today=TODAY)

    by_day = {point["to"]: point for point in answer["series"]}
    assert by_day[ago(9)]["starts"] == 1
    assert by_day[ago(3)]["starts"] == 1
    assert by_day[ago(2)]["app_new"] == 1
    assert by_day[ago(10)]["joins"] == 1
    assert by_day[ago(5)]["joins"] == 0, "a failed captcha let nobody in"
    assert by_day[ago(1)]["blocks"] == 1
    assert answer["totals"]["starts"]["now"] == 2


async def test_today_is_apart_from_the_bars(session_maker, audience):
    async with session_maker() as db:
        answer = await trends.trends(db, days=7, today=TODAY)

    assert answer["today_point"]["joins"] == 1
    assert all(point["to"] < TODAY for point in answer["series"])
    assert answer["totals"]["joins"]["now"] == 0


async def test_days_before_a_record_began_are_unknown_not_empty(session_maker, audience):
    async with session_maker() as db:
        answer = await trends.trends(db, days=30, today=TODAY)

    before = [point for point in answer["series"] if point["to"] < trends.STARTS_SINCE]
    assert before, "the period before reaches back past the start of the record"
    assert all(point["starts"] is None for point in before)
    assert answer["counted_since"]["starts"] == trends.STARTS_SINCE


async def test_the_funnel_says_who_came_from_where(session_maker, audience):
    async with session_maker() as db:
        answer = await trends.trends(db, days=30, today=TODAY)

    funnel = answer["funnel"]
    # Anna, Taras, and the two at the door: Jan was never seen in a chat.
    assert funnel["seen_in_chats"] == 4
    assert (funnel["started_bot"], funnel["opened_app"], funnel["both"]) == (2, 2, 1)
    assert funnel["not_from_chats"] == 1
    assert (funnel["reachable"], funnel["blocked"]) == (1, 1)
    assert funnel["estimate"] == 1
    # Taras opened the Mini App 40 days ago, before this period.
    assert answer["funnel_new"]["opened_app"] == 1


async def test_segments_name_the_chat_seen_first(session_maker, audience):
    async with session_maker() as db:
        answer = await trends.trends(db, days=30, today=TODAY)

    chats = {row["label"]: row["people"] for row in answer["segments"]["chats"]}
    assert chats == {"ČVUT FIT": 1, "Studenti VŠE": 1}
    languages = {row["key"]: row["people"] for row in answer["segments"]["languages"]}
    assert languages == {"ru": 1, "uk": 1, "cs": 1}
    sources = {row["key"]: row["people"] for row in answer["segments"]["sources"]}
    assert sources == {"welcome": 1, "uni-cvut": 1, "": 1}
