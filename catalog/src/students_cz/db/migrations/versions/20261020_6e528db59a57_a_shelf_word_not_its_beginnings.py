"""A shelf's word, and not the words that begin like it

The chemistry and programming shelves took stems — «хими», «chemi»,
«информатик» — and a stem is every word that begins with it: «химиотерапия»,
"chemist", «chemik», «информатик» the person. They take the forms of the
subject's own name instead, which is what people type.

Here as well as in `seeds/subjects.json` because the deploy runs `alembic
upgrade head` and never the seed.

Revision ID: 6e528db59a57
Revises: bcda508d1145
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6e528db59a57"
down_revision: str | Sequence[str] | None = "bcda508d1145"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Declared under these names so the tests hold the seed to them. No shelf's
# holds change; the name is there so the shelf-migration tests run this one too.
SYNONYM_REMOVES: dict[str, tuple[str, ...]] = {
    "chemistry": ("хими", "хімі", "chemi"),
    "it-programming": ("информатик", "інформатик", "informatik", "informatic"),
}
SYNONYM_ADDS: dict[str, tuple[str, ...]] = {
    "chemistry": (
        "химия",
        "химии",
        "химию",
        "химией",
        "хімія",
        "хімії",
        "хімію",
        "хімією",
        "chemie",
        "chemii",
        "chemistry",
    ),
    "it-programming": (
        "информатика",
        "информатики",
        "информатике",
        "информатику",
        "информатикой",
        "інформатика",
        "інформатики",
        "інформатику",
        "інформатикою",
        "informatika",
        "informatiky",
        "informatiku",
        "informatikou",
        "informatice",
        "informatics",
    ),
}
HOLDS: dict[str, tuple[str, ...]] = {}


def _add(bind, words: dict[str, tuple[str, ...]]) -> None:
    for slug, values in words.items():
        for word in values:
            # Appended only when it is not already there.
            bind.execute(
                sa.text(
                    "UPDATE subjects SET synonyms = synonyms || :word"
                    " WHERE slug = :slug AND NOT (synonyms @> ARRAY[:word]::text[])"
                ),
                {"word": word, "slug": slug},
            )


def _remove(bind, words: dict[str, tuple[str, ...]]) -> None:
    for slug, values in words.items():
        for word in values:
            bind.execute(
                sa.text(
                    "UPDATE subjects SET synonyms = array_remove(synonyms, :word)"
                    " WHERE slug = :slug"
                ),
                {"word": word, "slug": slug},
            )


def upgrade() -> None:
    bind = op.get_bind()
    _remove(bind, SYNONYM_REMOVES)
    _add(bind, SYNONYM_ADDS)


def downgrade() -> None:
    bind = op.get_bind()
    _remove(bind, SYNONYM_ADDS)
    _add(bind, SYNONYM_REMOVES)
