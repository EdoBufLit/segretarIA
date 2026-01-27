import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
