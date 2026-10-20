"""«řízení» alone is not control theory

`rizeni` was a synonym of «Automatizace a teorie řízení», and a synonym scores
1.00 — so «přijímací řízení», the admission procedure, came back as control
theory beside the entrance exams. The word on its own means management and
proceedings as often as control; «teorie řízení» stays and still finds the
subject, and «automatické řízení» and «řízení procesů», which the bare word used
to carry, become synonyms of their own.

Here as well as in `seeds/subjects.json` because the deploy runs `alembic
upgrade head` and never the seed.

Revision ID: bcda508d1145
Revises: 8df19c21d6d8
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bcda508d1145"
down_revision: str | Sequence[str] | None = "8df19c21d6d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Declared under these names so the tests hold the seed to them. No shelf's
# holds change; the name is there so the shelf-migration tests run this one too.
SYNONYM_REMOVES: dict[str, tuple[str, ...]] = {"automatizace-a-rizeni": ("rizeni",)}
SYNONYM_ADDS: dict[str, tuple[str, ...]] = {
    "automatizace-a-rizeni": ("automaticke rizeni", "rizeni procesu")
}
HOLDS: dict[str, tuple[str, ...]] = {}


def upgrade() -> None:
    bind = op.get_bind()
    for slug, words in SYNONYM_ADDS.items():
        for word in words:
            # Appended only when it is not already there.
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
    for slug, words in SYNONYM_REMOVES.items():
        for word in words:
            # Appended only when it is not already there.
            bind.execute(
                sa.text(
                    "UPDATE subjects SET synonyms = synonyms || :word"
                    " WHERE slug = :slug AND NOT (synonyms @> ARRAY[:word]::text[])"
                ),
                {"word": word, "slug": slug},
            )
