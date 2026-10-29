"""All ORM models.

Importing this package registers every mapper, which is what Alembic's
autogenerate needs to see the full schema. Import it, do not cherry-pick
modules, or migrations will silently miss tables.
"""

from students_cz.db.base import Base
from students_cz.db.models.catalog import Offer
from students_cz.db.models.goods import Item, Material
from students_cz.db.models.ops import ModerationReview, SearchQuery, UserEvent
from students_cz.db.models.partners import (
    Partner,
    PartnerOffer,
    PartnerOfferI18n,
    PartnerPhoto,
    Placement,
    PlacementEvent,
)
from students_cz.db.models.people import (
    AvailabilitySlot,
    HelperProfile,
    User,
    UserEducation,
    WeeklyAvailability,
)
from students_cz.db.models.requests import (
    Contact,
    HelpRequest,
    RequestAlert,
    RequestResponse,
)
from students_cz.db.models.taxonomy import (
    Institution,
    InstitutionI18n,
    ItemCategory,
    ItemCategoryI18n,
    Language,
    LanguageI18n,
    ServiceOption,
    ServiceOptionI18n,
    ServiceType,
    ServiceTypeI18n,
    StudentChat,
    Subject,
    SubjectEmbedding,
    SubjectI18n,
)

__all__ = [
    "AvailabilitySlot",
    "Base",
    "Contact",
    "HelpRequest",
    "HelperProfile",
    "Institution",
    "InstitutionI18n",
    "Item",
    "ItemCategory",
    "ItemCategoryI18n",
    "Language",
    "LanguageI18n",
    "Material",
    "ModerationReview",
    "Offer",
    "Partner",
    "PartnerOffer",
    "PartnerOfferI18n",
    "PartnerPhoto",
    "Placement",
    "PlacementEvent",
    "RequestAlert",
    "RequestResponse",
    "SearchQuery",
    "ServiceOption",
    "ServiceOptionI18n",
    "ServiceType",
    "ServiceTypeI18n",
    "StudentChat",
    "Subject",
    "SubjectEmbedding",
    "SubjectI18n",
    "User",
    "UserEducation",
    "UserEvent",
    "WeeklyAvailability",
]
