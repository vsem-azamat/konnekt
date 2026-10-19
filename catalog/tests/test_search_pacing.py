"""Search is for people, at a person's pace (#180), and says how long it took (#182)."""

from sqlalchemy import func, select

from students_cz.db.models import SearchQuery
from tests.conftest import auth_header


async def test_a_flood_of_searches_is_turned_away(client) -> None:
    """Any Telegram user gets a session, and every parse wrote two rows."""
    from students_cz.api.v1 import search

    answers = [
        (
            await client.post(
                "/api/v1/search/parse",
                json={"text": f"матан {i}"},
                headers=auth_header(90900),
            )
        ).status_code
        for i in range(search.PARSES_PER_MINUTE + 1)
    ]

    assert answers[:-1] == [200] * search.PARSES_PER_MINUTE
    assert answers[-1] == 429


async def test_one_person_s_flood_does_not_stop_another(client) -> None:
    from students_cz.api.v1 import search

    for _ in range(search.SEARCHES_PER_MINUTE + 1):
        await client.get("/api/v1/search", headers=auth_header(90901))

    assert (
        await client.get("/api/v1/search", headers=auth_header(90902))
    ).status_code == 200


async def test_the_same_question_twice_is_recorded_once(client, session) -> None:

    for _ in range(3):
        resp = await client.post(
            "/api/v1/search/parse",
            json={"text": "матан ČVUT"},
            headers=auth_header(90903),
        )
        assert resp.status_code == 200, resp.text

    rows = await session.scalar(
        select(func.count())
        .select_from(SearchQuery)
        .where(SearchQuery.raw_text == "матан ČVUT")
    )
    assert rows == 1


async def test_a_recorded_search_says_how_long_it_took(client, session) -> None:

    await client.post(
        "/api/v1/search/parse", json={"text": "химия VŠCHT"}, headers=auth_header(90904)
    )

    row = await session.scalar(
        select(SearchQuery).where(SearchQuery.raw_text == "химия VŠCHT")
    )
    assert row is not None
    assert row.took is not None


async def test_a_refused_init_data_does_not_explain_itself(client) -> None:
    """ "init data expired (Ns > 86400s)" told a prober which check to beat."""
    resp = await client.get(
        "/api/v1/search", headers={"Authorization": "tma auth_date=1&hash=x"}
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "init data rejected"


async def test_browsing_results_is_not_held_to_the_parse_limit(client) -> None:
    """The app runs a preview per typing pause and two searches per sort."""
    from students_cz.api.v1 import search

    for i in range(search.PARSES_PER_MINUTE):
        await client.post(
            "/api/v1/search/parse",
            json={"text": f"матан {i}"},
            headers=auth_header(90905),
        )

    assert (
        await client.get("/api/v1/search", headers=auth_header(90905))
    ).status_code == 200


async def test_a_refused_request_costs_nothing(client) -> None:
    from students_cz.api.v1 import search

    for _ in range(search.PARSES_PER_MINUTE):
        await client.post(
            "/api/v1/search/parse", json={"text": ""}, headers=auth_header(90906)
        )

    resp = await client.post(
        "/api/v1/search/parse", json={"text": "матан"}, headers=auth_header(90906)
    )
    assert resp.status_code == 200


async def test_results_have_a_limit_of_their_own(client) -> None:
    from students_cz.api.v1 import search

    answers = [
        (await client.get("/api/v1/search", headers=auth_header(90907))).status_code
        for _ in range(search.SEARCHES_PER_MINUTE + 1)
    ]

    assert answers[:-1] == [200] * search.SEARCHES_PER_MINUTE
    assert answers[-1] == 429
    assert search.SEARCHES_PER_MINUTE > search.PARSES_PER_MINUTE
