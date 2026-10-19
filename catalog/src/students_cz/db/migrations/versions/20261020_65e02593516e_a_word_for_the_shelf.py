"""A word for the shelf: «математика» names the maths group

A bare «математика» was answered with whichever leaf the trigram scorer liked
best — «Математика для экономистов» at 0.66 — and "maths" found nothing. The
parser may now answer with a group, through the group's own synonyms, and the
search reads a group as all of its leaves. These are the maths group's: stems,
so «математике», «matematiky» and "mathematics" reach it too.

Here as well as in `seeds/subjects.json` because the deploy runs `alembic
upgrade head` and never the seed.

Revision ID: 65e02593516e
Revises: f561e35734cd
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "65e02593516e"
down_revision: str | Sequence[str] | None = "f561e35734cd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Declared under this name so `tests/test_service_groups.py` holds the seed to it.
SYNONYM_ADDS: dict[str, tuple[str, ...]] = {"math": ("математик", "matematik", "math")}


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


def downgrade() -> None:
    bind = op.get_bind()
    for slug, words in SYNONYM_ADDS.items():
        for word in words:
            bind.execute(
                sa.text(
                    "UPDATE subjects SET synonyms = array_remove(synonyms, :word)"
                    " WHERE slug = :slug"
                ),
                {"word": word, "slug": slug},
            )
