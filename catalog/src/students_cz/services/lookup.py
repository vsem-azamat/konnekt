"""Turning what a student typed into rows in the reference tables.

Students type slang, no diacritics, the wrong language and typos — often all
four at once: "нужен матан на чвуте", "prijimacky cvut", "mat analiza".

Two mechanisms, in order of confidence:

1. **Synonyms.** A curated list per subject, matched from the start of a word.
   A synonym of four characters or more may run into the middle of the word, so
   "матан" still finds "матаном" and "линал" finds "линала" — Russian and Czech
   inflect, and students type inflected forms. Shorter synonyms must be whole
   words, or "ос" would fire on "основы".

   What no synonym may do is start mid-word. Not
   as substrings: the synonym "TIN" sits inside "čeština", which once made
   "cestina b2 pro nostrifikaci" resolve to automata theory with full
   confidence. Both sides are reduced to space-delimited tokens and compared
   with the spaces included, so a synonym has to be whole words. A hit here is
   certain, so it scores 1.0.
2. **Trigram similarity** against every translated name, in all four languages
   at once — the person's interface language says nothing about which language
   they typed in.

`word_similarity` rather than `similarity`: the query is a sentence and the
name is two words, so plain similarity would score near zero. Word similarity
asks how well the name matches *some part* of the query, which is the actual
question.
"""

import asyncio
import unicodedata
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from students_cz.db.models.enums import NodeKind, UiLang
from students_cz.services.naming import translated

_ENCODING = asyncio.Semaphore(1)

# Below this, matches are noise. Tuned by hand against real-looking queries:
# 0.5 lets "mat analiza" reach "Matematická analýza" while keeping "fyzika"
# from reaching "Fyzikální chemie".
NAME_THRESHOLD = 0.5


def normalise(value: str) -> str:
    """Lowercase and strip Latin diacritics, the way Postgres' unaccent does.

    Only Latin. Blanket mark-stripping decomposes "й" into "и" plus a breve and
    then throws the breve away, turning "чешский" into "чешскии" — which
    Postgres does not do, so the two sides stopped agreeing and nothing matched.
    Postgres does fold "ё" to "е", so that one case is spelled out.

    This runs on Python-side text only. Anything compared inside SQL is
    normalised by SQL, so there is one implementation of the rule per
    comparison rather than two that can drift.
    """
    out: list[str] = []
    for ch in unicodedata.normalize("NFD", value.casefold()):
        # A Latin base letter loses its accent; a Cyrillic one keeps it.
        if unicodedata.combining(ch) and out and out[-1].isascii():
            continue
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out)).replace("ё", "е").strip()


# Russian speakers write Czech abbreviations in Cyrillic: "чвут", "вше",
# "муни". The mapping is Czech-flavoured rather than the usual Russian
# romanisation — ч becomes "c" (as in Č) rather than "ch", because the target
# is a Czech acronym, not an English transcription.
_TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ж": "z",
        "з": "z",
        "и": "i",
        "й": "j",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "ch",
        "ц": "c",
        "ч": "c",
        "ш": "s",
        "щ": "s",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "ju",
        "я": "ja",
        "і": "i",
        "ї": "ji",
        "є": "je",
        "ґ": "g",
    }
)


def transliterate(value: str) -> str:
    """Czech-style romanisation of Cyrillic, for matching acronyms."""
    return normalise(value).translate(_TRANSLIT)


@dataclass(frozen=True)
class Match:
    id: int
    label: str
    score: float
    matched_on: str


# Reducing both sides to " token token " and comparing with the spaces kept is
# what enforces word boundaries — cheaper and less error-prone than escaping
# every synonym into a regex, and it handles multi-word synonyms unchanged.
# CAST(:p AS text) rather than :p::text — SQLAlchemy's text() refuses to treat
# a placeholder as a bind parameter when a colon follows it, so `:qnorm::text`
# reaches Postgres with the placeholder still in it.
# [[:alnum:]] rather than [a-z0-9]: the latter deletes every Cyrillic letter,
# which turned "матан" into an empty token string that matched everything.
# A synonym of four letters or more matches the start of a word, so «линал»
# reaches «линала» — unless it ends in a digit: «физика 1» is not the start
# of «физика 11 класс».
_NORM = "immutable_unaccent(lower({expr}))"
_TOKENS = "' ' || btrim(regexp_replace({expr}, '[^[:alnum:]]+', ' ', 'g')) || ' '"

# Does one of the subject's synonyms appear in the query as words? Written once,
# because the hit flag and the score must not disagree about it.
_SYNONYM_HIT = f"""EXISTS (
    SELECT 1 FROM unnest(s.synonyms) syn
     WHERE btrim(syn) <> '' AND strpos(
         q.tokens,
         rtrim({_TOKENS.format(expr="immutable_unaccent(lower(syn))")})
         || CASE WHEN length(btrim(syn)) >= 4 AND btrim(syn) !~ '[0-9]$'
            THEN '' ELSE ' ' END
     ) > 0
)"""

_SUBJECT_SQL = text(
    f"""
    WITH q AS (
        SELECT {_NORM.format(expr="CAST(:qnorm AS text)")} AS raw,
               {_TOKENS.format(expr=_NORM.format(expr="CAST(:qnorm AS text)"))} AS tokens
    )
    SELECT id, label, score, hit FROM (
        SELECT s.id,
               COALESCE(pref.name, any_name.name) AS label,
               ({_SYNONYM_HIT}) AS hit,
               GREATEST(
                   CASE WHEN {_SYNONYM_HIT} THEN 1.0 ELSE 0.0 END,
                   -- Prefix matching handles a changed word *ending* only
                   -- when the ending is added, not when it is replaced:
                   -- "линал" reaches "линала" but "линейка" does not reach
                   -- "линейку". Trigram similarity against the synonym itself
                   -- covers that, scored just below an exact hit so exact
                   -- hits still sort first.
                   COALESCE((
                       SELECT MAX(word_similarity(
                           immutable_unaccent(lower(syn)), q.raw)) * 0.92
                         FROM unnest(s.synonyms) syn
                        WHERE length(btrim(syn)) >= 5
                   ), 0.0),
                   CASE WHEN s.external_code IS NOT NULL
                         AND strpos(
                             q.tokens,
                             {_TOKENS.format(expr="lower(s.external_code)")}
                         ) > 0
                        THEN 0.95 ELSE 0.0 END,
                   COALESCE(MAX(word_similarity(
                       immutable_unaccent(lower(i.name)), q.raw)), 0.0)
               ) AS score
          FROM subjects s
          CROSS JOIN q
          LEFT JOIN subject_i18n i ON i.subject_id = s.id
          LEFT JOIN subject_i18n pref
                 ON pref.subject_id = s.id AND pref.lang = :lang
          LEFT JOIN LATERAL (
               SELECT name FROM subject_i18n WHERE subject_id = s.id LIMIT 1
          ) any_name ON TRUE
         WHERE s.is_active AND s.kind = CAST(:kind AS node_kind)
         GROUP BY s.id, s.synonyms, s.external_code,
                  pref.name, any_name.name, q.raw, q.tokens
    ) ranked
     WHERE score >= :threshold
     ORDER BY score DESC, id
     LIMIT :limit
    """
)

# What a shelf holds: everything under it, and the leaves elsewhere that it
# lists by slug in `holds`. The tree files «Математика для экономистов» under
# economics and the physics entrance exam under admissions, and both belong to
# the shelf somebody names by one word. Listed by hand, not guessed from names
# or synonyms: «Fyzikální chemie» starts with physics and is chemistry, and the
# medicine admissions name chemistry without being it. Only live leaves, in
# both directions. A leaf holds itself and nothing else — and, as a plain filter
# by its id always did, active or not.
_HOLDS = """s.is_active AND (
    s.path LIKE shelf.path || '%'
    OR (shelf.kind = 'group' AND s.kind = 'leaf' AND s.slug = ANY(shelf.holds))
)"""

_HELD_BY_SQL = text(
    f"""
    SELECT s.id FROM subjects s, subjects shelf
     WHERE shelf.id = :shelf AND (s.id = shelf.id OR ({_HOLDS}))
    """
)

_SHELVES_OF_SQL = text(
    f"""
    SELECT shelf.id FROM subjects shelf
     WHERE shelf.id = ANY(:ids) OR shelf.is_active AND EXISTS (
         SELECT 1 FROM subjects s WHERE s.id = ANY(:ids) AND {_HOLDS}
     )
    """
)

_SHELVES_BY_SUBJECT_SQL = text(
    f"""
    SELECT s.id, shelf.id FROM subjects s, subjects shelf
     WHERE s.id = ANY(:ids) AND (shelf.id = s.id OR shelf.is_active AND {_HOLDS})
    """
)


async def held_by(session: AsyncSession, subject_id: int) -> list[int]:
    """What a search for this subject covers: itself, and for a shelf what the
    shelf holds. Offers sit on leaves, so this is what a filter compares.

    A subject always covers itself, active or not, as a plain filter by its id
    always did; only what it reaches beyond itself has to be live."""
    return list(await session.scalars(_HELD_BY_SQL, {"shelf": subject_id}))


async def shelves_of(session: AsyncSession, subject_ids: set[int]) -> set[int]:
    """Every subject that holds one of these — themselves and the shelves they
    are on. The same relation as `held_by`, read the other way."""
    if not subject_ids:
        return set()
    return set(await session.scalars(_SHELVES_OF_SQL, {"ids": sorted(subject_ids)}))


async def shelves_by_subject(
    session: AsyncSession, subject_ids: set[int]
) -> dict[int, set[int]]:
    """`shelves_of` for each subject apart, in one query rather than one each."""
    shelves: dict[int, set[int]] = {subject_id: set() for subject_id in subject_ids}
    if subject_ids:
        rows = await session.execute(
            _SHELVES_BY_SUBJECT_SQL, {"ids": sorted(subject_ids)}
        )
        for subject_id, shelf_id in rows:
            shelves[subject_id].add(shelf_id)
    return shelves


_INSTITUTION_SQL = text(
    f"""
    WITH q AS (
        SELECT {_NORM.format(expr="CAST(:qnorm AS text)")} AS raw,
               {_NORM.format(expr="CAST(:qlat AS text)")} AS latin,
               {_TOKENS.format(expr=_NORM.format(expr="CAST(:qnorm AS text)"))}
                   AS tokens,
               {_TOKENS.format(expr=_NORM.format(expr="CAST(:qlat AS text)"))}
                   AS latin_tokens
    )
    SELECT n.id, n.label, n.score
      FROM (
        SELECT inst.id,
               COALESCE(pref.short_name, pref.name,
                        any_name.short_name, any_name.name) AS label,
               GREATEST(
                   -- The code is how people actually write it: cvut, vse, uk.
                   CASE WHEN q.raw ~ ('(^|[^a-z0-9])'
                                      || replace(inst.code, '_', '[ _-]?')
                                      || '([^a-z0-9]|$)')
                          OR q.latin ~ ('(^|[^a-z0-9])'
                                        || replace(inst.code, '_', '[ _-]?')
                                        || '([^a-z0-9]|$)')
                        THEN 1.0 ELSE 0.0 END,
                   -- A two-letter faculty name is a whole word or it is
                   -- nothing. "FI", "UK" and "JU" are two letters, and trigram
                   -- similarity puts any word containing them over the
                   -- threshold: "по физике" came back naming the faculty FI at
                   -- 0.67. Matched against the query's tokens, the same way
                   -- subject synonyms are two functions up, so there is one
                   -- idea of "whole word" here and no second regex to escape.
                   --
                   -- Two and not three: Czech declines the abbreviation itself,
                   -- and "na FELu", "na FITu", "na MFFce" are how people write
                   -- it. Cutting at three characters cost the 69 institutions
                   -- with a three-character short name every inflected form
                   -- they had — 60 of them faculties — and bought
                   -- nothing — every false positive worth killing here is two
                   -- letters long.
                   --
                   -- The two-letter names pay that price instead: "na UKu" and
                   -- "na FIu" used to resolve at 0.67 and now resolve to
                   -- nothing. That is the trade, taken deliberately. A missing
                   -- institution filter shows a wider list than the person
                   -- asked for; a wrong one silently narrows the catalog to a
                   -- faculty nobody named, which is what "по физике" did.
                   COALESCE(MAX(CASE WHEN length(i.short_name) < 3 AND (
                            strpos(q.tokens, ' ' || {_NORM.format(expr="i.short_name")}
                                   || ' ') > 0
                         OR strpos(q.latin_tokens,
                                   ' ' || {_NORM.format(expr="i.short_name")}
                                   || ' ') > 0)
                       THEN 1.0 ELSE 0.0 END), 0.0),
                   COALESCE(MAX(word_similarity(
                       immutable_unaccent(lower(i.name)), q.raw)), 0.0),
                   -- Long enough for a trigram score to mean something.
                   COALESCE(MAX(CASE WHEN length(i.short_name) >= 3
                       THEN word_similarity(
                           immutable_unaccent(lower(i.short_name)), q.raw)
                       END), 0.0),
                   COALESCE(MAX(CASE WHEN length(i.short_name) >= 3
                       THEN word_similarity(
                           immutable_unaccent(lower(i.short_name)), q.latin)
                       END), 0.0)
               ) AS score
          FROM institutions inst
          CROSS JOIN q
          LEFT JOIN institution_i18n i ON i.institution_id = inst.id
          LEFT JOIN institution_i18n pref
                 ON pref.institution_id = inst.id AND pref.lang = :lang
          LEFT JOIN LATERAL (
               SELECT name, short_name FROM institution_i18n
                WHERE institution_id = inst.id LIMIT 1
          ) any_name ON TRUE
         WHERE inst.is_active
         GROUP BY inst.id, inst.code, pref.short_name, pref.name,
                  any_name.short_name, any_name.name,
                  q.raw, q.latin, q.tokens, q.latin_tokens
      ) n
     WHERE n.score >= :threshold
     -- Total, so the same query always names the same school.
     ORDER BY n.score DESC, n.id
     LIMIT :limit
    """
)


async def find_subjects(
    session: AsyncSession,
    query: str,
    lang: str,
    *,
    limit: int = 5,
    threshold: float = NAME_THRESHOLD,
    kind: NodeKind = NodeKind.LEAF,
) -> list[Match]:
    """Subjects the query names or resembles, best first.

    Leaves by default, which is what an offer or a picker can hold. Groups are
    asked for separately, by the parser alone: a word for a whole shelf —
    «математика» — names the shelf, and the search reads it as its leaves.
    """
    rows = await session.execute(
        _SUBJECT_SQL,
        {
            "qnorm": normalise(query),
            "lang": lang,
            "limit": limit,
            "threshold": threshold,
            "kind": kind.value,
        },
    )
    return [
        Match(
            id=r.id,
            label=r.label,
            score=float(r.score),
            matched_on="synonym" if r.hit else "name",
        )
        for r in rows
    ]


# By eye, from a fixture measured on the real tree with the real model: right
# answers scored 0.49–0.68, and the two the model was unsure of led the
# runner-up by 0.00 and 0.03. Both numbers are meant to be replaced by ones
# taken from `search_queries`, which logs what the vector proposed on every
# parse whether or not it was used.
VECTOR_FLOOR = 0.45
VECTOR_LEAD = 0.04

# Below the two above the proposal is shown rather than used — a guess that
# cannot narrow a search can still be worth reading. Below this it is not even
# that: at that distance the nearest subject is whatever happened to be closest,
# and a section of noise is worse than no section.
VECTOR_ALSO_FLOOR = 0.35


async def find_by_meaning(
    session: AsyncSession, query: str, lang: str
) -> tuple[Match | None, Match | None]:
    """The nearest subject by meaning, and the runner-up that has to be beaten.

    Both come back so the caller can log what was proposed even when it refuses
    it — the numbers above were set by eye, and the only way to set them from
    data is to have the data.

    A subject scores as the best of its passages, and the runner-up is the best
    *other subject*: two rows of the same subject beating each other says
    nothing about confidence.
    """
    from students_cz.db.models import Subject, SubjectEmbedding
    from students_cz.services.embedding import as_query, get_embedder

    model = get_embedder()
    if model is None:
        return None, None
    # In a thread: inference is CPU work, and on the loop it stalled every
    # request the API's one worker had, its health check included.
    # One at a time: each inference already uses its own threads, and a burst
    # in parallel would take more of a shared box than the model is given.
    async with _ENCODING:
        vector = (await asyncio.to_thread(model.encode, [as_query(query)]))[0]

    # Distance rather than similarity, because that is the operator pgvector
    # indexes; cosine similarity is one minus it.
    # The best row of each subject, and then the best two subjects. `DISTINCT
    # ON` rather than a window over the closest rows: a subject with two dozen
    # passages could fill any window by itself, and then the runner-up the lead
    # is measured against would be nothing at all.
    distance = SubjectEmbedding.embedding.cosine_distance(vector)
    nearest = (
        select(
            SubjectEmbedding.subject_id,
            distance.label("distance"),
        )
        .join(Subject, Subject.id == SubjectEmbedding.subject_id)
        .where(SubjectEmbedding.model == model.name, Subject.is_active)
        .distinct(SubjectEmbedding.subject_id)
        .order_by(SubjectEmbedding.subject_id, "distance")
        .subquery()
    )
    rows = (
        await session.execute(
            select(nearest.c.subject_id, nearest.c.distance)
            .order_by(nearest.c.distance)
            .limit(2)
        )
    ).all()
    if not rows:
        return None, None

    ranked = [(subject_id, 1.0 - float(dist)) for subject_id, dist in rows]

    labelled: list[Match] = []
    for subject_id, score in ranked:
        subject = await session.get(
            Subject, subject_id, options=[selectinload(Subject.names)]
        )
        if subject is None:
            continue
        labelled.append(
            Match(
                id=subject.id,
                label=translated(subject, UiLang(lang)) or subject.slug,
                score=score,
                matched_on="vector",
            )
        )
    top = labelled[0] if labelled else None
    second = labelled[1] if len(labelled) > 1 else None
    return top, second


async def find_institutions(
    session: AsyncSession,
    query: str,
    lang: str,
    *,
    limit: int = 3,
    threshold: float = 0.6,
) -> list[Match]:
    rows = await session.execute(
        _INSTITUTION_SQL,
        {
            "qnorm": normalise(query),
            "qlat": transliterate(query),
            "lang": lang,
            "limit": limit,
            "threshold": threshold,
        },
    )
    return [
        Match(
            id=r.id,
            label=r.label,
            score=float(r.score),
            # "exact" rather than "code": a 1.0 can come from the code, from a
            # whole-word short name, or from a full name the query reproduced
            # exactly, and which of the three is not carried back. What the
            # field is read for is whether the match was a guess.
            matched_on="exact" if r.score >= 1.0 else "name",
        )
        for r in rows
    ]
