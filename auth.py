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


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    A dependency to get the current user from the session.
    If the user is not logged in, it redirects to the login page.
    """
    user_session = request.session.get("user")
    if not user_session or "user_id" not in user_session:
        raise HTTPException(
            status_code=302,
            detail="Not authenticated",
            headers={"Location": "/login"},
        )

    user_id = user_session["user_id"]
    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        # This case might happen if the user was deleted but the session persists.
        request.session.clear()
        raise HTTPException(
            status_code=302,
            detail="User not found",
            headers={"Location": "/login"},
        )

    return user
