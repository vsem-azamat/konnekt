"""The embedder, and the rules that do not need it.

Everything here runs on fakes, and `conftest` points `MODEL_DIR` at nothing for
the whole suite, so the answers do not depend on whether this machine happens to
have 200 MB of model on it. The real one is exercised where it belongs: the
image build checks the files it baked in, and the fixture in the pull request
was measured through `parse` with it.

Three fakes, each for a different question. `FakeEmbedder` gives every text a
deterministic vector — enough for the rebuild. `PointedEmbedder` puts one query
on top of one passage, which tests the wiring. `RiggedEmbedder` sets the cosine
itself, which is the only way to ask what happens at 0.3.
"""

import pytest

from students_cz.services.embedding import (
    DOCUMENT_PREFIX,
    QUERY_PREFIX,
    as_document,
    as_query,
)

pytestmark = pytest.mark.asyncio


class FakeEmbedder:
    """Deterministic vectors, so every rule above the model is testable.

    Under its own model name, so its rows never mix with the real ones a
    development database may already hold — the same property that lets a
    rollback find its own.

    Derived from the text rather than random: two runs over the same catalog
    have to agree, or the rebuild test below would pass for the wrong reason.
    """

    name = "fake"

    def encode(self, texts: list[str]) -> list[list[float]]:
        import hashlib

        from students_cz.services.embedding import DIMENSIONS

        out = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            raw = [digest[i % len(digest)] / 255 for i in range(DIMENSIONS)]
            length = sum(value * value for value in raw) ** 0.5
            out.append([value / length for value in raw])
        return out


class PointedEmbedder(FakeEmbedder):
    """A fake that puts one query next to one passage, and nothing else near.

    The only way to test a nearest-neighbour rule without the real model: rig
    which neighbour is nearest, then assert the wiring around it.
    """

    def __init__(self, pairs: dict[str, str]) -> None:
        self._pairs = pairs

    def encode(self, texts: list[str]) -> list[list[float]]:
        from students_cz.services.embedding import DOCUMENT_PREFIX, QUERY_PREFIX

        plain = []
        for text in texts:
            bare = text.removeprefix(QUERY_PREFIX).removeprefix(DOCUMENT_PREFIX)
            # A query and the passage it is rigged to point at embed as the same
            # text, so their cosine is exactly 1.
            plain.append(self._pairs.get(bare, bare))
        return super().encode(plain)


class RiggedEmbedder:
    """Explicit geometry: one passage at a chosen cosine, everything else at nil.

    `PointedEmbedder` can only put two texts on top of each other, which tests
    the wiring and not the numbers. This one answers "what if the nearest thing
    is only 0.3 away" — the question the floor exists for.
    """

    name = "rigged"

    def __init__(self, target: str, cosine: float) -> None:
        self._target = target
        self._cosine = cosine

    def encode(self, texts: list[str]) -> list[list[float]]:
        from students_cz.services.embedding import (
            DIMENSIONS,
            DOCUMENT_PREFIX,
            QUERY_PREFIX,
        )

        out = []
        for text in texts:
            vector = [0.0] * DIMENSIONS
            if text.startswith(QUERY_PREFIX):
                # Along the target's axis by exactly `cosine`, and the rest of
                # its length along an axis no passage uses.
                vector[0] = self._cosine
                vector[2] = (1 - self._cosine**2) ** 0.5
            elif text.removeprefix(DOCUMENT_PREFIX) == self._target:
                vector[0] = 1.0
            else:
                vector[1] = 1.0
            out.append(vector)
        return out


async def test_the_prefixes_are_the_ones_the_model_wants() -> None:
    """EmbeddingGemma was trained with them, and drops without.

    Not decoration: the same text embedded with the wrong prefix lands
    somewhere else, and the two sides of the comparison have different ones —
    the query says what it is looking for, the passage says what it is.
    """
    assert as_query("матан") == f"{QUERY_PREFIX}матан"
    assert (
        as_document("Математический анализ") == f"{DOCUMENT_PREFIX}Математический анализ"
    )
    assert QUERY_PREFIX != DOCUMENT_PREFIX


async def test_a_subject_can_carry_vectors(session) -> None:
    """The table exists, the extension is on, and a vector round-trips.

    `vector` is not in the base image's default set: a column typed against a
    missing extension fails at migration time, which is the good case, and a
    column that silently became text fails at query time, which is not.
    """
    from sqlalchemy import select

    from students_cz.db.models import Subject, SubjectEmbedding
    from students_cz.services.embedding import DIMENSIONS, MODEL_NAME

    subject = await session.scalar(select(Subject).limit(1))
    assert subject is not None, "reference data is not loaded — run `make seed`"

    session.add(
        SubjectEmbedding(
            subject_id=subject.id,
            model=MODEL_NAME,
            source="матан",
            text_sha="0" * 64,
            embedding=[0.0] * DIMENSIONS,
        )
    )
    await session.flush()

    stored = await session.scalar(
        select(SubjectEmbedding).where(SubjectEmbedding.text_sha == "0" * 64)
    )
    assert stored is not None
    assert len(stored.embedding) == DIMENSIONS


async def test_the_rebuild_writes_once_and_then_nothing(session) -> None:
    """Derived data, so the deploy runs it every time and it must be cheap.

    Keyed by the passage's hash and the model: the second run sees the same
    catalog and the same model and has nothing to do.
    """
    from sqlalchemy import func, select

    from students_cz.db.embed import rebuild
    from students_cz.db.models import SubjectEmbedding

    written = await rebuild(session, embedder=FakeEmbedder())
    assert written > 0, "nothing was embedded"
    total = await session.scalar(select(func.count(SubjectEmbedding.id)))

    again = await rebuild(session, embedder=FakeEmbedder())
    assert again == 0, "the second run rewrote rows nothing had changed"
    assert await session.scalar(select(func.count(SubjectEmbedding.id))) == total


async def test_a_passage_that_is_gone_takes_its_vector_with_it(session) -> None:
    """A synonym removed from the catalog must not answer queries for ever."""
    from sqlalchemy import select

    from students_cz.db.embed import rebuild
    from students_cz.db.models import Subject, SubjectEmbedding

    fake = FakeEmbedder()
    await rebuild(session, embedder=fake)
    subject = await session.scalar(select(Subject).where(Subject.synonyms != []).limit(1))
    assert subject is not None

    stale = SubjectEmbedding(
        subject_id=subject.id,
        model=fake.name,
        source="слово которого больше нет",
        text_sha="f" * 64,
        embedding=[0.5] * 768,
    )
    session.add(stale)
    await session.flush()

    await rebuild(session, embedder=fake)
    assert (
        await session.scalar(
            select(SubjectEmbedding).where(SubjectEmbedding.text_sha == "f" * 64)
        )
    ) is None, "a vector outlived the words it came from"


async def test_search_works_with_no_model_at_all(session, monkeypatch) -> None:
    """The vector is the third mechanism, not a dependency.

    A development checkout has no 200 MB file in it, and neither does an image
    built without the model stage. Both must search — they simply cannot answer
    the queries only meaning reaches.
    """
    from pathlib import Path

    from students_cz.services import embedding
    from students_cz.services.parser import parse

    embedding.set_embedder(None)
    monkeypatch.setattr(embedding, "_looked", False)
    monkeypatch.setattr(embedding, "MODEL_DIR", Path("/nonexistent"))

    parsed = await parse(session, "матан ČVUT", "ru")
    assert parsed.subject is not None
    assert parsed.institution is not None
    assert parsed.vector is None


async def test_what_the_vector_proposed_is_logged_even_when_refused(
    client, session
) -> None:
    """The thresholds were set by eye; this is where better ones come from."""
    from sqlalchemy import desc, select

    from students_cz.db.embed import rebuild
    from students_cz.db.models import SearchQuery
    from students_cz.services import embedding

    from .conftest import auth_header

    await rebuild(session, embedder=FakeEmbedder())
    embedding.set_embedder(FakeEmbedder())
    try:
        response = await client.post(
            "/api/v1/search/parse",
            json={"text": "не понимаю как считать вероятности"},
            headers=auth_header(90801),
        )
    finally:
        embedding.set_embedder(None)
    assert response.status_code == 200, response.text

    row = await session.scalar(
        select(SearchQuery).order_by(desc(SearchQuery.id)).limit(1)
    )
    assert row is not None
    assert row.parsed["vector"] is not None, "the proposal was not logged"
    assert {"subject_id", "score", "lead", "used"} <= set(row.parsed["vector"])


async def test_the_model_name_carries_the_revision_the_image_builds() -> None:
    """Two files have to agree, and nothing else would notice if they did not.

    The name is what every vector is written and read under. Bump the Dockerfile
    to a new model and leave the name alone, and the rebuild finds nothing to do
    — the catalog is unchanged — while the API embeds queries with the new
    weights against vectors made by the old ones. No error anywhere; just worse
    answers.
    """
    import re
    from pathlib import Path

    from students_cz.services.embedding import MODEL_NAME, MODEL_REVISION

    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    match = re.search(r"ARG EMBEDDING_REVISION=([0-9a-f]{40})", dockerfile)
    assert match, "the Dockerfile no longer pins a revision"
    assert match.group(1) == MODEL_REVISION
    assert MODEL_REVISION[:7] in MODEL_NAME


async def test_the_model_runs_off_the_event_loop(client, session) -> None:
    """Inference is CPU work; on the loop it stalled every request, healthz included."""
    import threading

    from students_cz.db.embed import rebuild
    from students_cz.services import embedding

    from .conftest import auth_header

    loop_thread = threading.current_thread()
    seen: list[threading.Thread] = []

    class Recording(FakeEmbedder):
        def encode(self, texts):
            seen.append(threading.current_thread())
            return super().encode(texts)

    await rebuild(session, embedder=FakeEmbedder())
    embedding.set_embedder(Recording())
    try:
        response = await client.post(
            "/api/v1/search/parse",
            json={"text": "не понимаю как считать вероятности"},
            headers=auth_header(90802),
        )
    finally:
        embedding.set_embedder(None)

    assert response.status_code == 200, response.text
    assert seen
    assert all(thread is not loop_thread for thread in seen)
