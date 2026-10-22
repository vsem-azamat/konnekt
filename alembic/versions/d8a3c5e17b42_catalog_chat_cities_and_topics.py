"""Place the listed chats in cities and file them under topics.

Values from the table reviewed in #konnekt on 2026-10-22 (catalogue variant B).
Chats are found by their public link rather than their Telegram id: the link
is already public, and a chat whose link changed since is simply left for the
console. A value is only written where the field is still empty, so nothing
set in the console is overwritten.

Only what cannot be derived is stored. A chat under a parent takes the
parent's city and topic, and a university's chats are filed as such by its
institution code, so the faculties carry nothing of their own.

Revision ID: d8a3c5e17b42
Revises: c4d81f2a9e60
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8a3c5e17b42"
down_revision: str | None = "c4d81f2a9e60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Universities' own chats: the city their taxonomy entry names.
CITIES = {
    "cvut_chat": "Praha",
    "karlov_chat": "Praha",
    "vscht_chat": "Praha",
    "vse_chat": "Praha",
    "czu_chat": "Praha",
    "masaryk_chat": "Brno",
    "vut_chat": "Brno",
    "chat_ntk": "Praha",
    "strahov_koleje": "Praha",
    "vsb_chat": "Ostrava",
}

TOPICS = {
    "biology_cz": "subjects",
    "chemie_cz": "subjects",
    "fyzika_cz": "subjects",
    "informatika_cz": "subjects",
    "matematika_cz": "subjects",
    "it_chat_cz": "work_it",
    "chat_ntk": "general",
    "strahov_koleje": "dorms",
    # VŠB-TUO is not in the catalog's taxonomy, so no institution says it.
    "vsb_chat": "university",
    # Dormitories listed under their university.
    "podoli_koleje": "dorms",
    "a02group": "dorms",
    "a03rus": "dorms",
    "kajetanka": "dorms",
    "kolej17": "dorms",
    "hvezda_koleje": "dorms",
}

# ČZU is in the taxonomy; its chat was listed before the code was set.
INSTITUTIONS = {"czu_chat": "czu"}

_FILL = (
    "UPDATE chats SET {column} = :value"
    " WHERE {column} IS NULL AND lower(rtrim(public_link, '/')) = lower(:link){only_top}"
)


def _fill(column: str, values: dict[str, str], *, top_only: bool) -> None:
    """Write each value where it is still empty; say which links matched nothing.

    A chat under a parent takes the parent's city and university, and the
    console refuses a university on one, so those two go to top chats only.
    """
    statement = sa.text(
        _FILL.format(column=column, only_top=" AND parent_chat_id IS NULL" if top_only else "")
    )
    bind = op.get_bind()
    for username, value in values.items():
        result = bind.execute(statement, {"value": value, "link": f"https://t.me/{username}"})
        if result.rowcount == 0:
            print(f"catalog data: {column} for t.me/{username} not written (no such empty field)")


def upgrade() -> None:
    _fill("city", CITIES, top_only=True)
    _fill("topic", TOPICS, top_only=False)
    _fill("institution_code", INSTITUTIONS, top_only=True)


def downgrade() -> None:
    # Data only, and by now possibly edited in the console: there is no telling
    # which values are still this migration's. The columns go with c4d81f2a9e60.
    pass
