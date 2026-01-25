import pytest
import os
import importlib
from unittest.mock import patch
import sys

# Common env for tests that import app
# We need OPENAI_API_KEY because call_utils initializes OpenAI client at module level
BASE_ENV = {
    "OPENAI_API_KEY": "sk-mock-key",
    "DATABASE_URL": "sqlite:///:memory:", # To avoid other errors
}

def test_auth_serializer_missing_secret():
    """Test that get_token_serializer raises error if SECRET_KEY is missing."""
    with patch.dict(os.environ, {}, clear=True):
        import auth
        # Force reload auth to ensure it picks up env if it was caching (it's not, but good practice)
        importlib.reload(auth)

        with pytest.raises(RuntimeError, match="SECRET_KEY is required"):
            auth.get_token_serializer()

def test_auth_serializer_valid_secret():
    """Test that get_token_serializer works with SECRET_KEY."""
    with patch.dict(os.environ, {"SECRET_KEY": "valid-secret-key-at-least-32-chars-long"}, clear=True):
        import auth
        importlib.reload(auth)

        serializer = auth.get_token_serializer()
        assert serializer is not None
        token = serializer.dumps("test@example.com")
        assert serializer.loads(token) == "test@example.com"

def test_app_startup_missing_secret():
    """Test that app module raises RuntimeError on import if SECRET_KEY is missing."""
    env = BASE_ENV.copy()
    if "SECRET_KEY" in env:
        del env["SECRET_KEY"]

    with patch.dict(os.environ, env, clear=True):
        # We need to handle both first import and reload
        with pytest.raises(RuntimeError, match="SECRET_KEY is required"):
            if 'app' in sys.modules:
                import app
                importlib.reload(app)
            else:
                import app

def test_app_startup_short_secret(caplog):
    """Test that app module logs warning if SECRET_KEY is short."""
    env = BASE_ENV.copy()
    env["SECRET_KEY"] = "short"

    with patch.dict(os.environ, env, clear=True):
        import logging
        if 'app' in sys.modules:
            import app
            with caplog.at_level(logging.WARNING):
                importlib.reload(app)
        else:
            with caplog.at_level(logging.WARNING):
                import app

        assert "SECRET_KEY is too short" in caplog.text

def test_app_startup_valid_secret(caplog):
    """Test that app module starts fine with valid secret."""
    env = BASE_ENV.copy()
    env["SECRET_KEY"] = "valid-secret-key-at-least-32-chars-long"

    with patch.dict(os.environ, env, clear=True):
        import logging
        if 'app' in sys.modules:
            import app
            with caplog.at_level(logging.WARNING):
                caplog.clear()
                importlib.reload(app)
        else:
            with caplog.at_level(logging.WARNING):
                import app

        assert "SECRET_KEY is too short" not in caplog.text
