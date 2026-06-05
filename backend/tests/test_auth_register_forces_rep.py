"""Public registration must always create rep role, never admin from body."""

import pytest
from pydantic import ValidationError

from crm.models.schemas.user_schemas import UserRegister


def test_user_register_schema_has_no_role_field():
    with pytest.raises(ValidationError):
        UserRegister(
            email="evil@example.com",
            full_name="Evil",
            password="password123",
            role="admin",
        )


def test_user_register_accepts_standard_fields():
    u = UserRegister(email="rep@example.com", full_name="Rep User", password="password123")
    assert u.email == "rep@example.com"
    assert not hasattr(u, "role") or "role" not in u.model_fields
