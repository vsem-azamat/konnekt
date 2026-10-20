"""More words for shelves: physics, chemistry, programming, economics

The maths shelf showed the way: a bare «физика» answered whichever physics leaf
the trigram scorer liked, and «fyziky» answered «Fyziologie». These four groups
get synonyms of their own, stems like the maths group's, so the parser can
answer with the shelf.

And what a shelf holds beyond its subtree is now only what it lists in
`holds`. A leaf used to belong when one of its names started with a shelf's
synonym, which would have put «Fyzikální chemie» into physics and the medicine
admissions into chemistry. The maths shelf lists the four leaves that rule gave
it, so it holds what it held. And «хімія» leaves the synonyms of general
chemistry, where it named one leaf by the word for the whole shelf.

Here as well as in `seeds/subjects.json` because the deploy runs `alembic
upgrade head` and never the seed.

Revision ID: 8df19c21d6d8
Revises: 65e02593516e
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8df19c21d6d8"
down_revision: str | Sequence[str] | None = "65e02593516e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Declared under these names so the tests hold the seed to them:
# `tests/test_service_groups.py` the synonyms, `tests/test_subject_groups.py`
# the holds and both together on a seeded database.
SYNONYM_ADDS: dict[str, tuple[str, ...]] = {
    # Stems, and the Czech and Ukrainian locatives where k turns into c
    # («ve fyzice», «у фізиці») — «fyzice» whole, since «fyzic» begins
    # «fyzická příprava». "physics" whole, since "physic" begins "physician".
    "math": ("matematic",),
    "physics": ("физик", "фізик", "фізиц", "fyzik", "fyzice", "physics"),
    "chemistry": ("хими", "хімі", "chemi"),
    "it-programming": (
        "программир",
        "програмуван",
        "programov",
        "programming",
        "информатик",
        "інформатик",
        "інформатиц",
        "informatik",
        "informatic",
    ),
    "economics-finance": ("экономик", "економік", "економіц", "ekonomi", "economics"),
}
# A word for the whole chemistry shelf, sitting on one leaf of it: bare
# «хімія» named general chemistry at 1.00 and never reached the shelf.
SYNONYM_REMOVES: dict[str, tuple[str, ...]] = {"obecna-chemie": ("хімія",)}
HOLDS: dict[str, tuple[str, ...]] = {
    "math": (
        "maturita",
        "matematika-pro-ekonomy",
        "financni-matematika",
        "prijimacky-technicke-vs",
        "prijimacky-matematika",
    ),
    "physics": ("prijimacky-fyzika", "prijimacky-technicke-vs"),
}

# What the previous revision left, for the downgrade.
_HOLDS_BEFORE: dict[str, tuple[str, ...]] = {"math": ("maturita",), "physics": ()}


def _set_holds(bind, holds: dict[str, tuple[str, ...]]) -> None:
    for slug, slugs in holds.items():
        bind.execute(
            sa.text("UPDATE subjects SET holds = :slugs WHERE slug = :slug"),
            {"slugs": list(slugs), "slug": slug},
        )


def upgrade() -> None:
    bind = op.get_bind()
    for slug, words in SYNONYM_ADDS.items():
        for word in words:
            # Appended only when it is not already there, so a database somebody
            # had already seeded does not end up with the word twice.
            bind.execute(
                sa.text(
                    "UPDATE subjects SET synonyms = synonyms || :word"
                    " WHERE slug = :slug AND NOT (synonyms @> ARRAY[:word]::text[])"
                ),
                {"word": word, "slug": slug},
            )
    for slug, words in SYNONYM_REMOVES.items():
        for word in words:
            bind.execute(
                sa.text(
                    "UPDATE subjects SET synonyms = array_remove(synonyms, :word)"
                    " WHERE slug = :slug"
                ),
                {"word": word, "slug": slug},
            )
    _set_holds(bind, HOLDS)


def downgrade() -> None:
    bind = op.get_bind()
    for slug, words in SYNONYM_REMOVES.items():
        for word in words:
            bind.execute(
                sa.text(
                    "UPDATE subjects SET synonyms = synonyms || :word"
                    " WHERE slug = :slug AND NOT (synonyms @> ARRAY[:word]::text[])"
                ),
                {"word": word, "slug": slug},
            )
    for slug, words in SYNONYM_ADDS.items():
        for word in words:
            bind.execute(
                sa.text(
                    "UPDATE subjects SET synonyms = array_remove(synonyms, :word)"
                    " WHERE slug = :slug"
                ),
                {"word": word, "slug": slug},
            )
    _set_holds(bind, _HOLDS_BEFORE)
