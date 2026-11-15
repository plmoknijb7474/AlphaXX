import hashlib
import hmac
import secrets
from cryptography.fernet import Fernet, InvalidToken
from .config import settings


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, salt_hex, digest_hex = stored.split("$", 2)
        if kind != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def create_api_key() -> tuple[str, str, str]:
    raw = "alpha_" + secrets.token_urlsafe(32)
    prefix = raw[:16]
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, prefix, key_hash


def verify_api_key(raw: str, key_hash: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(raw.encode()).hexdigest(), key_hash)


def encrypt_secret(value: str) -> str:
    if not settings.fernet_key:
        raise RuntimeError("FERNET_KEY is required before storing provider credentials")
    try:
        return Fernet(settings.fernet_key.encode()).encrypt(value.encode()).decode()
    except (ValueError, TypeError) as exc:
        raise RuntimeError("FERNET_KEY must be a valid Fernet key") from exc


def decrypt_secret(value: str) -> str:
    if not settings.fernet_key:
        raise RuntimeError("FERNET_KEY is not configured")
    try:
        return Fernet(settings.fernet_key.encode()).decrypt(value.encode()).decode()
    except (InvalidToken, ValueError, TypeError) as exc:
        raise RuntimeError("Provider credential cannot be decrypted; check FERNET_KEY") from exc
