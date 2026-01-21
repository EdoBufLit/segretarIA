from passlib.context import CryptContext

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
