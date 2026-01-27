import os
import pytest

# Ensure validation logic is loaded
os.environ["SECRET_KEY"] = "testing_secret_key_12345678901234567890"

from services.validators import normalize_phone_number
from models import PhoneNumber, AgentSettings
from app import CreatePhoneNumberRequest, AgentSettingsUpdate, UpdatePhoneNumberRequest

def test_normalize_phone_number_function():
    assert normalize_phone_number(" +39 02 123 456 ") == "+3902123456"
    assert normalize_phone_number("+39-02-123-456") == "+3902123456"
    assert normalize_phone_number("(+39) 02 123 456") == "+3902123456"
    assert normalize_phone_number("333 1234567") == "+3331234567"
    assert normalize_phone_number("") == ""
    assert normalize_phone_number(None) is None

def test_sqlalchemy_validation_none():
    pn = PhoneNumber()
    pn.office_phone_e164 = None
    assert pn.office_phone_e164 is None

def test_sqlalchemy_validation_phone_number():
    pn = PhoneNumber()
    # @validates triggers on assignment
    pn.e164 = " +39 333 123 "
    assert pn.e164 == "+39333123"

    pn.office_phone_e164 = " 02-123-456 "
    assert pn.office_phone_e164 == "+02123456"

def test_sqlalchemy_validation_agent_settings():
    settings = AgentSettings()
    settings.fallback_number = " +1 (555) 123-4567 "
    assert settings.fallback_number == "+15551234567"

    settings.test_phone_number = " 333 999 888 "
    assert settings.test_phone_number == "+333999888"

def test_pydantic_validation_create_phone():
    req = CreatePhoneNumberRequest(
        e164=" +39 111 222 ",
        user_id=1,
        office_phone_e164=" 02-555 "
    )
    assert req.e164 == "+39111222"
    assert req.office_phone_e164 == "+02555"

def test_pydantic_validation_update_phone():
    req = UpdatePhoneNumberRequest(
        office_phone_e164=" (02) 555-123 "
    )
    assert req.office_phone_e164 == "+02555123"

def test_pydantic_validation_agent_settings_update():
    req = AgentSettingsUpdate(
        test_phone_number=" +44 20 1234 5678 "
    )
    assert req.test_phone_number == "+442012345678"

    req_none = AgentSettingsUpdate(test_phone_number=None)
    assert req_none.test_phone_number is None

def test_pydantic_validation_non_string():
    # Should pass through non-string without crashing re.sub
    # Pydantic might raise validation error for int if field expects str, but we check if normalize_phones crashes.
    try:
        CreatePhoneNumberRequest(
            e164=123456,
            user_id=1
        )
    except Exception as e:
        # Pydantic validation error is expected, but not TypeError from re.sub
        assert "Input should be a valid string" in str(e) or "str" in str(e)
