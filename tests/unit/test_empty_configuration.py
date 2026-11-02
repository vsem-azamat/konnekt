"""An empty environment variable means "not set".

Configuration reaches the host as environment variables forwarded by the deploy.
A GitHub variable or secret that was never given a value forwards as an empty
string rather than not forwarding at all, so every optional setting has to
survive arriving empty. The ones that parse into something other than a string
are where this bites: an empty ADMIN_REPORT_CHAT_ID took the process down on
boot rather than falling back to its default.

Built through ``model_validate`` rather than keyword arguments, because an empty
string is exactly what the type system says these fields cannot hold — which is
the point.
"""

from __future__ import annotations

import pytest
from app.core.config import AdminSettings, DatabaseSettings, ObservabilitySettings

pytestmark = pytest.mark.unit


def test_an_empty_optional_int_is_absent_rather_than_invalid() -> None:
    settings = AdminSettings.model_validate({"super_admins": [1], "report_chat_id": ""})

    assert settings.report_chat_id is None


def test_an_empty_int_falls_back_to_its_default() -> None:
    database = DatabaseSettings.model_validate({"user": "u", "password": "p", "name": "n", "port": ""})

    assert database.port == 5432


def test_an_empty_credential_leaves_its_feature_switched_off() -> None:
    """The deploy forwards these names whether or not they hold anything."""
    assert ObservabilitySettings.model_validate({"metrics_secret": ""}).metrics_secret.get_secret_value() == ""


def test_a_value_that_is_present_still_wins() -> None:
    admin = AdminSettings.model_validate({"super_admins": [1], "report_chat_id": -1001})
    database = DatabaseSettings.model_validate({"user": "u", "password": "p", "name": "n", "port": 6543})

    assert admin.report_chat_id == -1001
    assert database.port == 6543
