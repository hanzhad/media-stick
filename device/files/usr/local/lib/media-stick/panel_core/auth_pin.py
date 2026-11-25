"""Optional 4-digit LAN Pairing PIN with PBKDF2-HMAC-SHA256 and signed session cookie.

Pure Core:
  - validate_pin, hash_pin, verify_pin_hash
  - sign_token, verify_token, extract_cookie, format_set_cookie

Thin Store:
  - PinAuth: stores PBKDF2 hash + HMAC secret (never plaintext PIN) in `<state_dir>/pin.json`.
    Transparent (allows all requests) when no PIN is configured.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading

PIN_RE = re.compile(r"^[0-9]{4}$")
PBKDF2_ITERS = 100_000
COOKIE_NAME = "ms_pin"
COOKIE_MAX_AGE = 2592000  # 30 days


# --- Pure Core ------------------------------------------------------------------------------------


def validate_pin(pin: str) -> str:
    """Validate that `pin` is a 4-digit ASCII string, else raise ValueError."""
    if not isinstance(pin, str) or not PIN_RE.match(pin):
        raise ValueError("PIN must be exactly 4 digits")
    return pin


def hash_pin(pin: str, salt: bytes, iterations: int = PBKDF2_ITERS) -> str:
    """Compute PBKDF2-HMAC-SHA256 hex digest for a validated 4-digit PIN."""
    validate_pin(pin)
    return hashlib.pbkdf2_hmac("sha256", pin.encode("ascii"), salt, iterations).hex()


def verify_pin_hash(pin: str, salt_hex: str, hash_hex: str, iterations: int = PBKDF2_ITERS) -> bool:
    """Constant-time verification of a PIN against stored PBKDF2 salt and hash."""
    try:
        validate_pin(pin)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", pin.encode("ascii"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def sign_token(secret: bytes, nonce: str) -> str:
    """Sign a session nonce with HMAC-SHA256."""
    sig = hmac.new(secret, nonce.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{nonce}.{sig}"


def verify_token(secret: bytes, token: str) -> bool:
    """Verify an HMAC-SHA256 signed session token in constant time."""
    if not isinstance(token, str) or "." not in token:
        return False
    nonce, sig = token.split(".", 1)
    if not nonce or not sig:
        return False
    expected = hmac.new(secret, nonce.encode("ascii"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def extract_cookie(headers, name: str = COOKIE_NAME) -> str:
    """Extract named cookie value from request headers (case-insensitive)."""
    raw = ""
    if hasattr(headers, "items"):
        for k, v in headers.items():
            if str(k).lower() == "cookie":
                raw = str(v)
                break
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() == name:
                return v.strip()
    return ""


def format_set_cookie(
    token: str,
    secure: bool = False,
    name: str = COOKIE_NAME,
    max_age: int = COOKIE_MAX_AGE,
) -> str:
    """Format a Set-Cookie header value with HttpOnly and SameSite=Strict."""
    parts = [f"{name}={token}", "Path=/", "HttpOnly", "SameSite=Strict", f"Max-Age={max_age}"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


# --- Thin Store -----------------------------------------------------------------------------------


class PinAuth:
    """Optional LAN Pairing PIN manager backed by `<state_dir>/pin.json`."""

    def __init__(self, state_dir: str = "/var/lib/media-stick"):
        self.state_dir = state_dir
        self.path = os.path.join(state_dir, "pin.json")
        self._lock = threading.Lock()

    def _load(self) -> dict | None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if (
                isinstance(data, dict)
                and isinstance(data.get("salt"), str)
                and isinstance(data.get("hash"), str)
                and isinstance(data.get("secret"), str)
            ):
                return data
        except (OSError, ValueError):
            pass
        return None

    def is_enabled(self) -> bool:
        with self._lock:
            return self._load() is not None

    def set_pin(self, pin: str) -> None:
        """Hash and store a new 4-digit PIN (never storing plaintext)."""
        validate_pin(pin)
        salt = secrets.token_bytes(16)
        secret = secrets.token_bytes(32)
        iters = PBKDF2_ITERS
        digest = hash_pin(pin, salt, iters)
        payload = json.dumps({
            "salt": salt.hex(),
            "hash": digest,
            "iterations": iters,
            "secret": secret.hex(),
        }).encode("utf-8")

        with self._lock:
            os.makedirs(self.state_dir, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(prefix=".pin-", dir=self.state_dir)
            try:
                os.chmod(tmp_path, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(payload)
                os.replace(tmp_path, self.path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

    def verify_pin(self, pin: str) -> bool:
        with self._lock:
            data = self._load()
        if data is None:
            return False
        iters = int(data.get("iterations") or PBKDF2_ITERS)
        return verify_pin_hash(pin, data["salt"], data["hash"], iters)

    def issue_cookie(self, secure: bool = False) -> str:
        """Return a signed Set-Cookie header value for an authenticated client."""
        with self._lock:
            data = self._load()
        if data is None:
            return ""
        secret = bytes.fromhex(data["secret"])
        token = sign_token(secret, secrets.token_hex(16))
        return format_set_cookie(token, secure=secure)

    def clear_cookie(self, secure: bool = False) -> str:
        return format_set_cookie("", secure=secure, max_age=0)

    def check_request(self, headers) -> bool:
        """Return True if PIN auth is disabled or request carries a valid signed cookie."""
        with self._lock:
            data = self._load()
        if data is None:
            return True
        token = extract_cookie(headers)
        if not token:
            return False
        try:
            secret = bytes.fromhex(data["secret"])
        except ValueError:
            return False
        return verify_token(secret, token)

    def disable(self) -> None:
        """Remove stored PIN, making the panel open again."""
        with self._lock:
            try:
                os.unlink(self.path)
            except FileNotFoundError:
                pass
