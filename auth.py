import secrets
import string
import os
import hmac
import hashlib
import base64
from typing import Optional
from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from itsdangerous import URLSafeTimedSerializer
from db import get_db
from models import User

# Set up the password hashing context using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_token_serializer() -> URLSafeTimedSerializer:
    secret = os.getenv("SECRET_KEY")
    if not secret:
        raise RuntimeError("SECRET_KEY is required for token generation")
    return URLSafeTimedSerializer(secret)


def generate_reset_token(email: str) -> str:
    """Generates a timed token for password reset."""
    serializer = get_token_serializer()
    return serializer.dumps(email, salt="password-reset-salt")


def verify_reset_token(token: str, expiration=3600) -> Optional[str]:
    """
    Verifies the reset token. Returns the email if valid, None otherwise.
    Expiration defaults to 1 hour (3600 seconds).
    """
    serializer = get_token_serializer()
    try:
        email = serializer.loads(
            token,
            salt="password-reset-salt",
            max_age=expiration
        )
        return email
    except Exception:
        return None


def hash_password(password: str) -> str:
    """
    Hashes a plain text password using bcrypt.
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plain text password against its hashed version.
    """
    return pwd_context.verify(plain_password, hashed_password)


def normalize_identifier(identifier: str) -> str:
    """
    Normalizes identifiers (username/email) to avoid mismatch issues.
    - Trims whitespace.
    - Lowercases if it looks like an email.
    """
    if not identifier:
        return ""
    cleaned = identifier.strip()
    if "@" in cleaned:
        return cleaned.lower()
    return cleaned


def generate_random_password(length=12):
    """Generates a secure random password."""
    alphabet = string.ascii_letters + string.digits + string.punctuation
    while True:
        password = ''.join(secrets.choice(alphabet) for i in range(length))
        if (any(c.islower() for c in password)
                and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)):
            return password


def verify_elevenlabs_signature(raw_body: bytes, headers: dict, secret: str) -> Optional[bool]:
    """
    Verifies the ElevenLabs webhook signature.
    Returns:
    - True: Verified
    - False: Verification failed
    - None: Signature header missing
    """
    possible_keys = [
        "ElevenLabs-Signature",
        "elevenlabs-signature",
        "X-Elevenlabs-Signature",
        "x-elevenlabs-signature"
    ]

    sig_header = None
    for key in possible_keys:
        if key in headers:
            sig_header = headers[key]
            break

    if not sig_header:
        return None

    timestamp = None
    signature = None

    # Parse header: "t=TIMESTAMP,v1=SIGNATURE"
    # Allow whitespace around comma and equals
    try:
        parts = [p.strip() for p in sig_header.split(",")]
        for part in parts:
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            k = k.strip()
            v = v.strip()

            if k == "t":
                timestamp = v
            elif k in ("v1", "v0"):
                signature = v
    except Exception:
        return False

    if not timestamp or not signature:
        return False

    # Compute expected signatures with multiple common payload formats
    try:
        timestamp_bytes = timestamp.encode("utf-8")
        secret_bytes = secret.encode("utf-8")

        candidates = [
            raw_body + timestamp_bytes,          # Standard
            timestamp_bytes + raw_body,          # Reverse
            timestamp_bytes + b"." + raw_body,   # Dotted
        ]

        for payload in candidates:
            h = hmac.new(secret_bytes, payload, hashlib.sha256)
            digest = h.digest()

            # Compare against:
            # 1. Hex
            if hmac.compare_digest(h.hexdigest(), signature):
                return True

            # 2. Base64 (std)
            b64 = base64.b64encode(digest).decode("utf-8")
            if hmac.compare_digest(b64, signature):
                return True
            if hmac.compare_digest(b64.rstrip("="), signature):  # tolerate missing padding
                return True

            # 3. Base64 (urlsafe)
            b64_url = base64.urlsafe_b64encode(digest).decode("utf-8")
            if hmac.compare_digest(b64_url, signature):
                return True
            if hmac.compare_digest(b64_url.rstrip("="), signature):
                return True

        return False
    except Exception:
        return False


class NotAuthenticatedPage(Exception):
    """Raised when authentication is required for a page but not provided."""
    pass


class NotAuthorizedPage(Exception):
    """Raised when a user lacks permission for a page."""
    def __init__(self, user: User, required_role: str):
        self.user = user
        self.required_role = required_role


def get_user_from_session(request: Request, db: Session) -> Optional[User]:
    """
    Helper function to retrieve user from session without raising exceptions.
    Returns None if not authenticated.
    """
    user_session = request.session.get("user")
    if not user_session or "user_id" not in user_session:
        return None

    user_id = user_session["user_id"]
    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        # User deleted but session exists
        request.session.clear()
        return None

    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    A dependency to get the current user from the session (API style).
    If the user is not logged in, it raises HTTPException(401).
    """
    user = get_user_from_session(request, db)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
        )
    return user


def get_current_user_page(request: Request, db: Session = Depends(get_db)) -> User:
    """
    A dependency to get the current user for HTML pages.
    Raises NotAuthenticatedPage if not logged in.
    """
    user = get_user_from_session(request, db)
    if not user:
        raise NotAuthenticatedPage()
    return user


def require_role(role: str):
    def _require_role(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role != role:
            raise HTTPException(status_code=403, detail="Not authorized")
        return current_user

    return _require_role


def require_role_page(role: str):
    def _require_role_page(current_user: User = Depends(get_current_user_page)) -> User:
        if current_user.role != role:
            raise NotAuthorizedPage(user=current_user, required_role=role)
        return current_user
    return _require_role_page


def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """
    A dependency to get the current user, ensuring they are an admin.
    If the user is not an admin, it raises a 403 Forbidden error.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    return current_user


def get_current_admin_user_page(current_user: User = Depends(get_current_user_page)) -> User:
    """
    A dependency to get the current admin user for HTML pages.
    Raises NotAuthorizedPage if not admin.
    """
    if current_user.role != "admin":
        raise NotAuthorizedPage(user=current_user, required_role="admin")
    return current_user
