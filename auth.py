<<<<<<< HEAD
<<<<<<< HEAD
import secrets
import string
=======
>>>>>>> origin/feature/stripe-integration-14308306324681726244
=======
>>>>>>> origin/landing-page-11717745976152594883
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


<<<<<<< HEAD
<<<<<<< HEAD
def generate_random_password(length: int = 12) -> str:
    """
    Generates a secure random password with at least one uppercase,
    one lowercase, one number, and one special character.
    """
    if length < 4:
        raise ValueError("Password length must be at least 4")

    alphabet = string.ascii_letters + string.digits + string.punctuation

    # Ensure at least one of each required character type
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(string.punctuation),
    ]

    # Fill the rest
    password += [secrets.choice(alphabet) for _ in range(length - 4)]

    # Shuffle to avoid predictable pattern
    secrets.SystemRandom().shuffle(password)

    return "".join(password)


=======
>>>>>>> origin/feature/stripe-integration-14308306324681726244
=======
>>>>>>> origin/landing-page-11717745976152594883
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


def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """
    A dependency to get the current user, ensuring they are an admin.
    If the user is not an admin, it raises a 403 Forbidden error.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    return current_user
