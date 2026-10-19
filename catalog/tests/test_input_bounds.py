"""Query and path values a client cannot turn into a 500.

Any Telegram user can get a session, so any session could trigger these on
purpose: `inf` reached `int(max_price)`, and an id past bigint reached asyncpg.
"""

import pytest

from tests.conftest import auth_header

BIGINT_PAST = 2**63


@pytest.mark.parametrize(
    "params",
    [
        {"max_price": "inf"},
        {"max_price": "nan"},
        {"max_price": "-1"},
        {"subject_id": BIGINT_PAST},
        {"institution_id": 0},
        {"service_type_id": BIGINT_PAST},
        {"langs": ["cs"] * 21},
        {"langs": ["x" * 40]},
    ],
)
async def test_search_refuses_what_it_cannot_handle(client, params) -> None:
    resp = await client.get("/api/v1/search", params=params, headers=auth_header(90777))

    assert resp.status_code == 422, resp.text


async def test_a_helper_id_past_bigint_is_refused(client) -> None:
    resp = await client.get(f"/api/v1/helpers/{BIGINT_PAST}", headers=auth_header(90777))

    assert resp.status_code == 422, resp.text


async def test_a_subject_parent_past_bigint_is_refused(client) -> None:
    resp = await client.get(
        "/api/v1/taxonomy/subjects",
        params={"parent_id": BIGINT_PAST},
        headers=auth_header(90777),
    )

    assert resp.status_code == 422, resp.text


async def test_an_ordinary_search_still_answers(client) -> None:
    resp = await client.get(
        "/api/v1/search",
        params={"max_price": 500, "langs": ["cs", "en"]},
        headers=auth_header(90777),
    )

    assert resp.status_code == 200, resp.text
