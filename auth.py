import secrets
import string
from typing import Optional
from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from db import get_db
from models import User

# Set up the password hashing context using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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


def generate_random_password(length=12):
    """Generates a secure random password."""
    alphabet = string.ascii_letters + string.digits + string.punctuation
    while True:
        password = ''.join(secrets.choice(alphabet) for i in range(length))
        if (any(c.islower() for c in password)
                and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)):
            return password


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
    If the user is not logged in, it raises HTTPException(302).
    """
    user = get_user_from_session(request, db)
    if not user:
        raise HTTPException(
            status_code=302,
            detail="Not authenticated",
            headers={"Location": "/login"},
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
