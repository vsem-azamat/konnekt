"""Say it in plain words: no «матан», no «Přijímačky»

The catalog called entrance preparation «Přijímačky» in three languages and
hinted at tutoring with «матан, физика, …» — the words students use, written
back at them as if they were the names. They are slang, and some readers do not
know them. The names become «Вступительные экзамены», «Přijímací zkoušky» and
«Вступні іспити», the hint says «математика», and the three subjects whose Czech
name began with «Přijímačky na …» begin with «Přijímací zkoušky na …».

Search still understands the slang: «přijímačky» reaches `entrance_prep`
through the parser's keyword table, «матан» is a synonym of calculus, and none
of that changes here.

Here as well as in `seed.py` and `seeds/subjects.json` because the deploy runs
`alembic upgrade head` and never the seed: production shows the old words until
this runs. `tests/test_service_groups.py` holds the two to the same text.

Revision ID: f561e35734cd
Revises: 01b89b8f84b1
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f561e35734cd"
down_revision: str | Sequence[str] | None = "01b89b8f84b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Name and hint per language, only for the languages that change. Declared under
# these names so `tests/test_service_groups.py` can compare them with the seed.
SERVICE_TYPE_RENAMES: dict[str, dict[str, tuple[str, str]]] = {
    "tutoring": {
        "ru": ("Репетитор по предмету", "математика, физика, экономика, программирование"),
        "uk": ("Репетитор з предмета", "математика, фізика, економіка, програмування"),
    },
    "entrance_prep": {
        "ru": ("Вступительные экзамены", "ČVUT, VŠE, UK, VUT, MUNI"),
        "cs": ("Přijímací zkoušky", "ČVUT, VŠE, UK, VUT, MUNI"),
        "uk": ("Вступні іспити", "ČVUT, VŠE, UK, VUT, MUNI"),
    },
}
SUBJECT_RENAMES: dict[str, dict[str, str]] = {
    "prijimacky-technicke-vs": {
        "cs": "Přijímací zkoušky na technické VŠ (matematika + fyzika)",
    },
    "prijimacky-ekonomicke-vs": {"cs": "Přijímací zkoušky na ekonomické VŠ (VŠE)"},
    "prijimacky-medicina": {"cs": "Přijímací zkoušky na medicínu (biologie + chemie)"},
}

# What production says today, for the downgrade.
_SERVICE_TYPES_BEFORE: dict[str, dict[str, tuple[str, str]]] = {
    "tutoring": {
        "ru": ("Репетитор по предмету", "матан, физика, экономика, программирование"),
        "uk": ("Репетитор з предмета", "матан, фізика, економіка, програмування"),
    },
    "entrance_prep": {
        "ru": ("Přijímačky", "ČVUT, VŠE, UK, VUT, MUNI"),
        "cs": ("Přijímačky", "ČVUT, VŠE, UK, VUT, MUNI"),
        "uk": ("Přijímačky", "ČVUT, VŠE, UK, VUT, MUNI"),
    },
}
_SUBJECTS_BEFORE: dict[str, dict[str, str]] = {
    "prijimacky-technicke-vs": {"cs": "Přijímačky na technické VŠ (matematika + fyzika)"},
    "prijimacky-ekonomicke-vs": {"cs": "Přijímačky na ekonomické VŠ (VŠE)"},
    "prijimacky-medicina": {"cs": "Přijímačky na medicínu (biologie + chemie)"},
}


def _name_service_types(bind, names: dict[str, dict[str, tuple[str, str]]]) -> None:
    for code, langs in names.items():
        for lang, (name, hint) in langs.items():
            bind.execute(
                sa.text(
                    "UPDATE service_type_i18n SET name = :name, hint = :hint"
                    " FROM service_types"
                    " WHERE service_types.id = service_type_i18n.service_type_id"
                    "   AND service_types.code = :code"
                    "   AND service_type_i18n.lang = CAST(:lang AS ui_lang)"
                ),
                {"code": code, "lang": lang, "name": name, "hint": hint},
            )


def _name_subjects(bind, names: dict[str, dict[str, str]]) -> None:
    for slug, langs in names.items():
        for lang, name in langs.items():
            bind.execute(
                sa.text(
                    "UPDATE subject_i18n SET name = :name"
                    " FROM subjects"
                    " WHERE subjects.id = subject_i18n.subject_id"
                    "   AND subjects.slug = :slug"
                    "   AND subject_i18n.lang = CAST(:lang AS ui_lang)"
                ),
                {"slug": slug, "lang": lang, "name": name},
            )


def upgrade() -> None:
    bind = op.get_bind()
    _name_service_types(bind, SERVICE_TYPE_RENAMES)
    _name_subjects(bind, SUBJECT_RENAMES)


def downgrade() -> None:
    bind = op.get_bind()
    _name_service_types(bind, _SERVICE_TYPES_BEFORE)
    _name_subjects(bind, _SUBJECTS_BEFORE)
