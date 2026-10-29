"""Reference data: subject tree, institutions, service types, item categories.

Everything here is curated by us rather than written by users, so it is
translated through dedicated ``*_i18n`` tables. User-written text is never
translated — it only carries the language it happens to be written in.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from students_cz.db.base import Base, IdMixin, TimestampMixin
from students_cz.db.models.enums import (
    InstitutionKind,
    NodeKind,
    ServiceForm,
    ServiceGroup,
    UiLang,
    pg_enum,
)
from students_cz.services.embedding import DIMENSIONS as EMBEDDING_DIMENSIONS


class Subject(IdMixin, TimestampMixin, Base):
    """A node in the subject tree.

    Hierarchy is a materialised path: ``path`` holds the chain of ancestor ids
    terminated by a dot (``'4.19.128.'``). A whole branch is one indexed
    ``path LIKE '4.19.%'`` — no recursive CTE, no ltree extension. The path is
    built from ids rather than slugs so renaming a subject never rewrites the
    subtree.
    """

    __tablename__ = "subjects"

    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="RESTRICT"), index=True
    )
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    depth: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    slug: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    kind: Mapped[NodeKind] = mapped_column(
        pg_enum(NodeKind, "node_kind"),
        nullable=False,
        default=NodeKind.LEAF,
        server_default="leaf",
    )

    # Course code as printed in the university system: 'FY1', '221023'.
    # Students search by these more often than by the full name.
    external_code: Mapped[str | None] = mapped_column(String(32))

    # Alternative spellings for fuzzy lookup: 'матан', 'matan', 'mat. analyza'.
    # Searched through pg_trgm, so accented variants need no duplicates —
    # unaccent strips the diacritics.
    synonyms: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    # A group's leaves on other shelves, by slug: maths for economists sits
    # under economics and is maths too. Written down rather than guessed from
    # names or synonyms, which mention a shelf's word on leaves that are not
    # about it. See `lookup.held_by` and docs/data-model.md.
    holds: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    sort: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    parent: Mapped["Subject | None"] = relationship(remote_side="Subject.id")
    names: Mapped[list["SubjectI18n"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index(
            "ix_subjects_path_prefix",
            "path",
            postgresql_ops={"path": "text_pattern_ops"},
        ),
        Index("ix_subjects_synonyms", "synonyms", postgresql_using="gin"),
        Index("ix_subjects_active_sort", "is_active", "sort"),
    )


class SubjectEmbedding(IdMixin, Base):
    """One vector per passage of a subject, per model.

    Per *passage* and not per subject: a subject is known by its name in four
    languages and by its synonyms, and averaging «Чешский язык B1» with
    «čeština pro cizince» into one vector gives something that is neither. A
    subject scores as the best of its own rows.

    Derived data — `python -m students_cz.db.embed` fills it from the catalog
    and the model, and nothing else writes it. `model` is in the key so a
    rollback finds the vectors its own image made, and `text_sha` is what makes
    the rebuild skip everything that has not changed.
    """

    __tablename__ = "subject_embeddings"

    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    # The text that was embedded, kept for the same reason `search_queries`
    # keeps the raw query: without it a wrong neighbour is unexplainable.
    source: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))

    __table_args__ = (
        UniqueConstraint(
            "subject_id", "model", "text_sha", name="uq_subject_embeddings_source"
        ),
        # No ANN index on purpose. Eighty-eight subjects are about twelve
        # hundred rows, an exact scan of those is faster than probing an index,
        # and IVFFlat built on this little data returns worse neighbours than
        # none at all. See docs/data-model.md.
        Index("ix_subject_embeddings_model", "model"),
    )


class SubjectI18n(Base):
    __tablename__ = "subject_i18n"

    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True
    )
    lang: Mapped[UiLang] = mapped_column(pg_enum(UiLang, "ui_lang"), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(64))

    subject: Mapped[Subject] = relationship(back_populates="names")

    __table_args__ = (
        # Trigram index backing "what did the person actually mean" lookups.
        # Indexed on the *normalised* expression, because that is what the
        # query compares: an index on the raw column cannot serve
        # word_similarity(immutable_unaccent(lower(name)), ...) and Postgres
        # quietly falls back to a sequential scan.
        Index(
            "ix_subject_i18n_name_trgm",
            text("immutable_unaccent(lower(name))"),
            postgresql_using="gin",
            postgresql_ops={"immutable_unaccent(lower(name))": "gin_trgm_ops"},
        ),
    )


class Institution(IdMixin, TimestampMixin, Base):
    """University, faculty, secondary school or examining body.

    Same materialised path: a faculty hangs under its university, so "everything
    at ČVUT" is one prefix query instead of enumerating faculties by hand.
    """

    __tablename__ = "institutions"

    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), index=True
    )
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    depth: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    kind: Mapped[InstitutionKind] = mapped_column(
        pg_enum(InstitutionKind, "institution_kind"), nullable=False
    )
    city: Mapped[str | None] = mapped_column(String(96))
    site_url: Mapped[str | None] = mapped_column(String(512))
    sort: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    parent: Mapped["Institution | None"] = relationship(remote_side="Institution.id")
    names: Mapped[list["InstitutionI18n"]] = relationship(
        back_populates="institution", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index(
            "ix_institutions_path_prefix",
            "path",
            postgresql_ops={"path": "text_pattern_ops"},
        ),
        Index("ix_institutions_active_sort", "is_active", "sort"),
    )


class InstitutionI18n(Base):
    __tablename__ = "institution_i18n"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    lang: Mapped[UiLang] = mapped_column(pg_enum(UiLang, "ui_lang"), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(64))

    institution: Mapped[Institution] = relationship(back_populates="names")

    __table_args__ = (
        Index(
            "ix_institution_i18n_name_trgm",
            text("immutable_unaccent(lower(name))"),
            postgresql_using="gin",
            postgresql_ops={"immutable_unaccent(lower(name))": "gin_trgm_ops"},
        ),
        Index(
            "ix_institution_i18n_short_trgm",
            text("immutable_unaccent(lower(short_name))"),
            postgresql_using="gin",
            postgresql_ops={"immutable_unaccent(lower(short_name))": "gin_trgm_ops"},
        ),
    )


class ServiceType(IdMixin, TimestampMixin, Base):
    """Kind of help: tutoring, live exam help, writing a paper, and so on.

    The ``requires_*`` flags drive the offer form: a written paper does not need
    a subject, while exam preparation is meaningless without an institution.
    """

    __tablename__ = "service_types"

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Which shelf the tile sits on. NOT NULL with a default rather than
    # nullable: a type in no group would render on neither screen, and the
    # failure would be an absence nobody sees.
    group_code: Mapped[ServiceGroup] = mapped_column(
        pg_enum(ServiceGroup, "service_group"),
        nullable=False,
        default=ServiceGroup.STUDY,
        server_default="study",
    )
    # The shape of the form that offers this, which is not the shelf it sits on.
    # Defaulting to `lesson` is the safe direction for an unmigrated row — the
    # lesson form is a superset of the questions — but a new kind of help that
    # takes the default silently gets asked how it teaches.
    form_shape: Mapped[ServiceForm] = mapped_column(
        pg_enum(ServiceForm, "service_form"),
        nullable=False,
        default=ServiceForm.LESSON,
        server_default="lesson",
    )
    requires_subject: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    requires_institution: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    default_price_unit: Mapped[str | None] = mapped_column(String(16))
    sort: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    names: Mapped[list["ServiceTypeI18n"]] = relationship(
        back_populates="service_type", cascade="all, delete-orphan", lazy="selectin"
    )
    options: Mapped[list["ServiceOption"]] = relationship(
        back_populates="service_type", cascade="all, delete-orphan"
    )


class ServiceTypeI18n(Base):
    __tablename__ = "service_type_i18n"

    service_type_id: Mapped[int] = mapped_column(
        ForeignKey("service_types.id", ondelete="CASCADE"), primary_key=True
    )
    lang: Mapped[UiLang] = mapped_column(pg_enum(UiLang, "ui_lang"), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # The explanatory line under the title on the home screen.
    hint: Mapped[str | None] = mapped_column(String(240))

    service_type: Mapped[ServiceType] = relationship(back_populates="names")


class ServiceOption(IdMixin, TimestampMixin, Base):
    """One line of what a kind of help covers: "I come to the bank with you".

    Reference data we author, so its labels live in a side table like every
    other name — see docs/data-model.md. An offer's choices are ids in
    `offers.option_ids`, which is why a retired option is deactivated rather
    than deleted: the array references nothing and a deleted row would leave an
    offer pointing at a label that no longer exists.
    """

    __tablename__ = "service_options"

    service_type_id: Mapped[int] = mapped_column(
        ForeignKey("service_types.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(48), nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    # `names` and not `labels`, so `services/naming.translated` reads it the way
    # it reads every other reference table's side table.
    service_type: Mapped["ServiceType"] = relationship(back_populates="options")
    names: Mapped[list["ServiceOptionI18n"]] = relationship(
        back_populates="option", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("service_type_id", "code", name="uq_service_options_code"),
    )


class ServiceOptionI18n(Base):
    __tablename__ = "service_option_i18n"

    option_id: Mapped[int] = mapped_column(
        ForeignKey("service_options.id", ondelete="CASCADE"), primary_key=True
    )
    lang: Mapped[UiLang] = mapped_column(pg_enum(UiLang, "ui_lang"), primary_key=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)

    option: Mapped[ServiceOption] = relationship(back_populates="names")


class ItemCategory(IdMixin, TimestampMixin, Base):
    """Category of physical things: gear for rent, textbooks, everything else."""

    __tablename__ = "item_categories"

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    sort: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    names: Mapped[list["ItemCategoryI18n"]] = relationship(
        back_populates="category", cascade="all, delete-orphan", lazy="selectin"
    )


class ItemCategoryI18n(Base):
    __tablename__ = "item_category_i18n"

    category_id: Mapped[int] = mapped_column(
        ForeignKey("item_categories.id", ondelete="CASCADE"), primary_key=True
    )
    lang: Mapped[UiLang] = mapped_column(pg_enum(UiLang, "ui_lang"), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    hint: Mapped[str | None] = mapped_column(String(240))

    category: Mapped[ItemCategory] = relationship(back_populates="names")


class Language(Base):
    """A language someone is willing to work in.

    Wider than the interface languages: a tutor may teach in German even though
    we ship no German UI. Offers store languages as an array rather than a
    foreign key so that "speaks any of mine" is a single indexed overlap test;
    this table only supplies display names and ordering.
    """

    __tablename__ = "languages"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    sort: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    names: Mapped[list["LanguageI18n"]] = relationship(
        back_populates="language", cascade="all, delete-orphan", lazy="selectin"
    )


class LanguageI18n(Base):
    __tablename__ = "language_i18n"

    language_code: Mapped[str] = mapped_column(
        ForeignKey("languages.code", ondelete="CASCADE"), primary_key=True
    )
    lang: Mapped[UiLang] = mapped_column(pg_enum(UiLang, "ui_lang"), primary_key=True)
    name: Mapped[str] = mapped_column(String(96), nullable=False)

    language: Mapped[Language] = relationship(back_populates="names")


class StudentChat(Base):
    """Curated list of public student chats, carried over from the legacy bot.

    Small, hand-maintained, and genuinely useful — the one legacy table worth
    keeping as-is.
    """

    __tablename__ = "student_chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="SET NULL"), index=True
    )
    sort: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


__all__ = [
    "Institution",
    "InstitutionI18n",
    "ItemCategory",
    "ItemCategoryI18n",
    "Language",
    "LanguageI18n",
    "ServiceType",
    "ServiceTypeI18n",
    "StudentChat",
    "Subject",
    "SubjectI18n",
]
