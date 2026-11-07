"""The public site and Google search, for the console's «Источники».

Read once a day from the two services that count them, Cloudflare Web
Analytics (no cookies, our own CDN) and Google Search Console, and kept by the
day in `site_days` and `search_days`. The console then reads our database,
never theirs, so a slow or failed import costs freshness and not the screen.

Each import asks for the last `LOOKBACK` days and writes them over what it
had: Cloudflare finishes a day late, and Search Console two or three days
late, so a day settles over several runs.
"""

from __future__ import annotations

import datetime
import json
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import jwt
from sqlalchemy import func, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import ProductEvent, SearchDay, SiteDay
from app.db.upsert import insert_for

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("usage.sources")

LOOKBACK = 7
TOP = 10
# The whole of a day, in both tables: no referrer, path or query is a single star.
WHOLE = "*"
# Where the site's own buttons into the app say they came from (web/site/src/landing/copy.ts).
SITE_SOURCE = "site"

CLOUDFLARE_GRAPHQL = "https://api.cloudflare.com/client/v4/graphql"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"  # noqa: S105 — an address, not a secret
SEARCH_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
SEARCH_ROWS = 1000

_RUM = """
query Site($account: string!, $site: string!, $from: Date!, $to: Date!) {
  viewer { accounts(filter: {accountTag: $account}) {
    total: rumPageloadEventsAdaptiveGroups(limit: 100, filter: {siteTag: $site, date_geq: $from, date_leq: $to}) {
      count sum { visits } dimensions { date }
    }
    referrer: rumPageloadEventsAdaptiveGroups(limit: 2000, orderBy: [count_DESC], filter: {siteTag: $site, date_geq: $from, date_leq: $to}) {
      count sum { visits } dimensions { date refererHost }
    }
    page: rumPageloadEventsAdaptiveGroups(limit: 2000, orderBy: [count_DESC], filter: {siteTag: $site, date_geq: $from, date_leq: $to}) {
      count sum { visits } dimensions { date requestPath }
    }
  } }
}
"""


class SourceError(RuntimeError):
    """A service answered, but not with what was asked for."""


def _window(today: datetime.date) -> tuple[datetime.date, datetime.date]:
    return today - datetime.timedelta(days=LOOKBACK), today - datetime.timedelta(days=1)


async def fetch_site(http: httpx.AsyncClient, *, today: datetime.date) -> list[dict[str, Any]]:
    """Cloudflare's days as `site_days` rows."""
    first, last = _window(today)
    config = settings.analytics
    response = await http.post(
        CLOUDFLARE_GRAPHQL,
        headers={"Authorization": f"Bearer {config.cloudflare_token.get_secret_value()}"},
        json={
            "query": _RUM,
            "variables": {
                "account": config.cloudflare_account_id,
                "site": config.cloudflare_site_tag,
                "from": first.isoformat(),
                "to": last.isoformat(),
            },
        },
    )
    response.raise_for_status()
    body = response.json()
    if body.get("errors") or not body.get("data"):
        # Their messages name the query, not us; the field paths are what helps.
        raise SourceError(f"cloudflare: {[error.get('path') for error in body.get('errors') or []]}")
    accounts = body["data"]["viewer"]["accounts"]
    if not accounts:
        raise SourceError("cloudflare: no such account for this token")
    rows = []
    for dimension, field in (("total", None), ("referrer", "refererHost"), ("page", "requestPath")):
        for group in accounts[0][dimension]:
            key = WHOLE if field is None else (group["dimensions"].get(field) or WHOLE)
            rows.append(
                {
                    "day": datetime.date.fromisoformat(group["dimensions"]["date"]),
                    "dimension": dimension,
                    "key": key[:200],
                    "visits": int(group["sum"]["visits"]),
                    "views": int(group["count"]),
                }
            )
    return rows


async def _google_token(http: httpx.AsyncClient) -> str:
    """A token for the service account, from its own key: no Google library needed for one call."""
    key = json.loads(settings.analytics.search_console_credentials.get_secret_value())
    now = int(time.time())
    assertion = jwt.encode(
        {"iss": key["client_email"], "scope": SEARCH_SCOPE, "aud": GOOGLE_TOKEN, "iat": now, "exp": now + 600},
        key["private_key"],
        algorithm="RS256",
    )
    response = await http.post(
        GOOGLE_TOKEN, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
    )
    response.raise_for_status()
    return response.json()["access_token"]


async def fetch_search(http: httpx.AsyncClient, *, today: datetime.date) -> list[dict[str, Any]]:
    """Search Console's days as `search_days` rows, the day's whole as query `*`."""
    first, last = _window(today)
    token = await _google_token(http)
    site = quote(settings.analytics.search_console_site, safe="")
    url = f"https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
    rows = []
    for dimensions in (["date"], ["date", "query"]):
        response = await http.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "startDate": first.isoformat(),
                "endDate": last.isoformat(),
                "dimensions": dimensions,
                "rowLimit": SEARCH_ROWS,
            },
        )
        response.raise_for_status()
        for row in response.json().get("rows", []):
            rows.append(
                {
                    "day": datetime.date.fromisoformat(row["keys"][0]),
                    "query": row["keys"][1][:200] if len(row["keys"]) > 1 else WHOLE,
                    "clicks": int(row["clicks"]),
                    "impressions": int(row["impressions"]),
                    "position": float(row["position"]),
                }
            )
    return rows


async def save(db: AsyncSession, table: Any, rows: list[dict[str, Any]], keys: tuple[str, ...]) -> None:
    for row in rows:
        insert = insert_for(db, table).values(**row)
        await db.execute(
            insert.on_conflict_do_update(
                index_elements=list(keys),
                set_={column: getattr(insert.excluded, column) for column in row if column not in keys},
            )
        )


async def import_once(db: AsyncSession, http: httpx.AsyncClient, *, today: datetime.date) -> None:
    """Both imports that are configured; one failing does not stop the other."""
    config = settings.analytics
    if config.cloudflare_on:
        try:
            await save(db, SiteDay.__table__, await fetch_site(http, today=today), ("day", "dimension", "key"))
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("site_import_failed")
    if config.search_console_on:
        try:
            await save(db, SearchDay.__table__, await fetch_search(http, today=today), ("day", "query"))
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("search_import_failed")


def _top(rows: list[tuple[str, int]]) -> list[dict[str, Any]]:
    return [{"key": key, "visits": visits} for key, visits in rows]


async def report(db: AsyncSession, *, days: int, today: datetime.date) -> dict[str, Any]:
    """The period ending yesterday: today is not imported yet."""
    first = today - datetime.timedelta(days=days)
    in_site = (SiteDay.day >= first) & (SiteDay.day < today)
    in_search = (SearchDay.day >= first) & (SearchDay.day < today)

    async def site_top(dimension: str) -> list[dict[str, Any]]:
        rows = await db.execute(
            select(SiteDay.key, func.sum(SiteDay.visits))
            .where(in_site, SiteDay.dimension == dimension)
            .group_by(SiteDay.key)
            .order_by(func.sum(SiteDay.visits).desc(), SiteDay.key)
            .limit(TOP)
        )
        return _top([(key, int(visits)) for key, visits in rows.all()])

    visits, views = (
        await db.execute(
            select(func.sum(SiteDay.visits), func.sum(SiteDay.views)).where(in_site, SiteDay.dimension == "total")
        )
    ).one()
    site_days = (
        await db.execute(
            select(SiteDay.day, SiteDay.visits).where(in_site, SiteDay.dimension == "total").order_by(SiteDay.day)
        )
    ).all()
    clicks, impressions = (
        await db.execute(
            select(func.sum(SearchDay.clicks), func.sum(SearchDay.impressions)).where(
                in_search, SearchDay.query == WHOLE
            )
        )
    ).one()
    queries = (
        await db.execute(
            select(
                SearchDay.query,
                func.sum(SearchDay.clicks),
                func.sum(SearchDay.impressions),
                # Weighted by impressions, as Google averages it.
                func.sum(SearchDay.position * SearchDay.impressions) / func.nullif(func.sum(SearchDay.impressions), 0),
            )
            .where(in_search, SearchDay.query != WHOLE)
            .group_by(SearchDay.query)
            .order_by(func.sum(SearchDay.clicks).desc(), func.sum(SearchDay.impressions).desc(), SearchDay.query)
            .limit(TOP)
        )
    ).all()

    # Launches the site's own buttons brought, from the app's side: the start parameter Telegram signed.
    starts = (
        await db.execute(
            select(ProductEvent.props).where(
                ProductEvent.name == "session_start",
                ProductEvent.at >= datetime.datetime.combine(first, datetime.time()),
                ProductEvent.at < datetime.datetime.combine(today, datetime.time()),
            )
        )
    ).scalars()
    to_app: defaultdict[str, int] = defaultdict(int)
    for props in starts:
        source = (props or {}).get("source") or ""
        if source.startswith(SITE_SOURCE) and not (props or {}).get("resumed"):
            to_app[source] += 1

    last_site = await db.scalar(select(func.max(SiteDay.day)))
    last_search = await db.scalar(select(func.max(SearchDay.day)))
    return {
        "days": days,
        "site": {
            "on": settings.analytics.cloudflare_on,
            "through": last_site,
            "visits": int(visits or 0),
            "views": int(views or 0),
            "by_day": [{"day": day, "visits": n} for day, n in site_days],
            "referrers": await site_top("referrer"),
            "pages": await site_top("page"),
        },
        "search": {
            "on": settings.analytics.search_console_on,
            "through": last_search,
            "clicks": int(clicks or 0),
            "impressions": int(impressions or 0),
            "queries": [
                {"query": query, "clicks": int(c), "impressions": int(i), "position": round(float(p or 0), 1)}
                for query, c, i, p in queries
            ],
        },
        "to_app": {
            "launches": sum(to_app.values()),
            "by_source": [
                {"source": source, "launches": n}
                for source, n in sorted(to_app.items(), key=lambda item: (-item[1], item[0]))[:TOP]
            ],
        },
    }
