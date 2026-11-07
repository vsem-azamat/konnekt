"""The usage reports and the site import, on PostgreSQL: its JSON, its upsert and its date arithmetic."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from app.db.models import ProductEvent, SearchDay, SiteDay
from app.usage import report, sources
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NOW = datetime.datetime(2026, 11, 10, 11, 0)


async def test_the_usage_report_runs_on_postgres(pg_session: AsyncSession) -> None:
    pg_session.add_all(
        [
            ProductEvent(
                user_id=1,
                session="s",
                seq=i,
                name=name,
                screen="/home",
                props=props,
                at=NOW - datetime.timedelta(minutes=5 - i),
                platform="ios",
                version="t",
            )
            for i, (name, props) in enumerate(
                [
                    ("session_start", {"source": "site_hero"}),
                    ("screen_view", {}),
                    ("tab_tap", {"tab": "chats"}),
                    ("heartbeat", {}),
                ]
            )
        ]
    )
    await pg_session.commit()

    got = await report.usage(pg_session, days=7, now=NOW)

    assert (got["people"], got["sessions"], got["screens"]) == (1, 1, [{"screen": "/home", "people": 1}])
    assert got["entries"] == [{"source": "site_hero", "launches": 1}]


async def test_the_site_days_are_rewritten_not_doubled(pg_session: AsyncSession) -> None:
    day = datetime.date(2026, 11, 9)
    for visits in (3, 5):
        await sources.save(
            pg_session,
            SiteDay.__table__,
            [{"day": day, "dimension": "total", "key": "*", "visits": visits, "views": 9}],
            ("day", "dimension", "key"),
        )
        await sources.save(
            pg_session,
            SearchDay.__table__,
            [{"day": day, "query": "*", "clicks": visits, "impressions": 9, "position": 2.0}],
            ("day", "query"),
        )
    await pg_session.commit()

    assert [r.visits for r in await pg_session.scalars(select(SiteDay))] == [5]
    got = await sources.report(pg_session, days=7, today=datetime.date(2026, 11, 10))
    assert (got["site"]["visits"], got["search"]["clicks"]) == (5, 5)
