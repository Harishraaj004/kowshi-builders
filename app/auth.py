"""
app/auth.py
============
Accounts, sessions and role-based access control (RBAC).

HOW LOGIN WORKS
---------------
Signing up / in (email+password, or a Google ID token) creates a random
session token. We store only its SHA-256 hash in Postgres and hand the raw
token to the browser in an httpOnly cookie - JavaScript can't read it, so
an XSS bug can't steal it, and a leaked database can't be replayed. Every
API call then resolves cookie -> user via `current_user`.

HOW RBAC WORKS
--------------
Each user has exactly one role; each role maps to a fixed set of
permission strings (PERMISSIONS below). Routes declare what they need with
`Depends(require_permission("..."))`. Object-level rules (a customer may
only touch THEIR project) live in app/projects.py on top of this.
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.config import ADMIN_EMAILS, COOKIE_SECURE, GOOGLE_CLIENT_ID, SESSION_DAYS
from app.database import get_connection
from app.emailer import send_otp_email

COOKIE_NAME = "kb_session"
# The admin console has its own cookie (scoped to /api/admin), so an admin
# and a customer can be signed in at the same time in one browser.
ADMIN_COOKIE_NAME = "kb_admin_session"
ADMIN_COOKIE_PATH = "/api/admin"

# --- RBAC ------------------------------------------------------------------
PERMISSIONS: dict[str, set[str]] = {
    "customer": {
        "project:view_own",
        "appointment:request",
        "document:upload",
    },
    "engineer": {
        "project:view_assigned",
        "appointment:manage",
        "document:review",
        "project:schedule_start",
    },
    "admin": {
        "project:view_all",
        "project:assign",
        "appointment:manage",
        "document:review",
        "project:schedule_start",
        "user:manage",
    },
}
ROLES = tuple(PERMISSIONS)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def has_permission(user: dict, permission: str) -> bool:
    return permission in PERMISSIONS.get(user["role"], set())


# --- Passwords (scrypt, stdlib - no extra dependency) -----------------------
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    # Always burn a hash's worth of time, even for unknown users, so response
    # timing doesn't reveal which emails are registered.
    if not stored or not stored.startswith("scrypt$"):
        hashlib.scrypt(password.encode(), salt=b"0" * 16, dklen=32, **_SCRYPT)
        return False
    _, salt_hex, digest_hex = stored.split("$")
    digest = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt_hex), dklen=32, **_SCRYPT
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


# --- Sessions ----------------------------------------------------------------
def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(
    response: Response, user_id: int, cookie_name: str = COOKIE_NAME, path: str = "/"
) -> None:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    with get_connection() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE expires_at < now()")
        conn.execute(
            "INSERT INTO auth_sessions (token_hash, user_id, expires_at) "
            "VALUES (%s, %s, %s)",
            (token_hash(token), user_id, expires),
        )
        conn.commit()
    conn.close()
    response.set_cookie(
        cookie_name,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path=path,
    )


def get_user_from_request(request: Request, cookie_name: str = COOKIE_NAME) -> dict | None:
    token = request.cookies.get(cookie_name)
    if not token:
        return None
    with get_connection() as conn:
        user = conn.execute(
            "SELECT u.id, u.email, u.name, u.role FROM auth_sessions s "
            "JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = %s AND s.expires_at > now()",
            (token_hash(token),),
        ).fetchone()
    conn.close()
    return user


def current_user(request: Request) -> dict:
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return user


def require_permission(permission: str):
    def checker(user: dict = Depends(current_user)) -> dict:
        if not has_permission(user, permission):
            raise HTTPException(status_code=403, detail="You don't have access to this.")
        return user

    return checker


# --- Request models ------------------------------------------------------------
class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=200)
    session_id: str | None = None


class ResendRequest(BaseModel):
    email: str = Field(max_length=254)


class VerifyRequest(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(min_length=5, max_length=5)
    session_id: str | None = None


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class LoginOtpRequest(BaseModel):
    """Step 1 of sign-in: just the address we mailed the code to."""
    email: str = Field(max_length=254)


class GoogleRequest(BaseModel):
    credential: str
    session_id: str | None = None


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "permissions": sorted(PERMISSIONS.get(user["role"], set())),
    }


def _finish_login(response: Response, conn, user: dict, chat_session_id: str | None) -> dict:
    """Bootstrap-admin promotion, claim the visitor's chat quote, set cookie."""
    from app.projects import claim_chat_quotes  # local import: avoids a cycle

    if user["email"].lower() in ADMIN_EMAILS and user["role"] != "admin":
        conn.execute("UPDATE users SET role = 'admin' WHERE id = %s", (user["id"],))
        user["role"] = "admin"
    # Only customers own projects; staff signing in on a browser that had a
    # chat shouldn't swallow the quote.
    if chat_session_id and user["role"] == "customer":
        claim_chat_quotes(conn, user["id"], chat_session_id)
    conn.commit()
    start_session(response, user["id"])
    return {"user": public_user(user)}


# --- Routes --------------------------------------------------------------------
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/config")
def auth_config() -> dict:
    return {"google_client_id": GOOGLE_CLIENT_ID}


OTP_LENGTH = 5
OTP_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_SECONDS = 30


def _new_code() -> str:
    return f"{secrets.randbelow(10**OTP_LENGTH):0{OTP_LENGTH}d}"


def _code_hash(email: str, code: str) -> str:
    return hashlib.sha256(f"{email}:{code}".encode()).hexdigest()


def _issue_otp(conn, email: str, name: str, password_hash: str) -> None:
    """Create/replace the pending signup for this email and email the code."""
    code = _new_code()
    conn.execute(
        "INSERT INTO signup_otps (email, name, password_hash, code_hash, expires_at) "
        "VALUES (%s, %s, %s, %s, now() + make_interval(mins => %s)) "
        "ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name, "
        "password_hash = EXCLUDED.password_hash, code_hash = EXCLUDED.code_hash, "
        "expires_at = EXCLUDED.expires_at, attempts = 0, last_sent_at = now()",
        (email, name, password_hash, _code_hash(email, code), OTP_MINUTES),
    )
    try:
        send_otp_email(email, code, OTP_MINUTES, "signup")
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error))


@router.post("/signup/start")
def signup_start(body: SignupRequest) -> dict:
    """Step 1: validate, store the pending signup, email a 5-digit code."""
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Please enter a valid email address.")
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE lower(email) = %s", (email,)).fetchone():
            raise HTTPException(
                status_code=409, detail="An account with this email already exists - try signing in."
            )
        _issue_otp(conn, email, body.name.strip(), hash_password(body.password))
        conn.commit()
    conn.close()
    return {"email": email, "expires_in_minutes": OTP_MINUTES}


@router.post("/signup/resend")
def signup_resend(body: ResendRequest) -> dict:
    email = body.email.strip().lower()
    with get_connection() as conn:
        pending = conn.execute(
            "SELECT name, password_hash, "
            "extract(epoch FROM now() - last_sent_at) AS age FROM signup_otps WHERE email = %s",
            (email,),
        ).fetchone()
        if pending is None:
            raise HTTPException(status_code=404, detail="Signup expired - please start again.")
        if pending["age"] < OTP_RESEND_SECONDS:
            raise HTTPException(
                status_code=429, detail="Please wait a few seconds before requesting another code."
            )
        _issue_otp(conn, email, pending["name"], pending["password_hash"])
        conn.commit()
    conn.close()
    return {"ok": True}


@router.post("/signup/verify")
def signup_verify(body: VerifyRequest, response: Response) -> dict:
    """Step 2: check the code; only now is the account created and signed in."""
    email = body.email.strip().lower()
    with get_connection() as conn:
        pending = conn.execute("SELECT * FROM signup_otps WHERE email = %s", (email,)).fetchone()
        if pending is None or pending["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="That code has expired - request a new one.")
        if pending["attempts"] >= OTP_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Too many wrong attempts - request a new code.")
        if not hmac.compare_digest(pending["code_hash"], _code_hash(email, body.code.strip())):
            conn.execute("UPDATE signup_otps SET attempts = attempts + 1 WHERE email = %s", (email,))
            conn.commit()
            raise HTTPException(status_code=400, detail="Incorrect code. Check your email and try again.")
        if conn.execute("SELECT 1 FROM users WHERE lower(email) = %s", (email,)).fetchone():
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        user = conn.execute(
            "INSERT INTO users (email, name, password_hash) VALUES (%s, %s, %s) "
            "RETURNING id, email, name, role",
            (email, pending["name"], pending["password_hash"]),
        ).fetchone()
        conn.execute("DELETE FROM signup_otps WHERE email = %s", (email,))
        result = _finish_login(response, conn, user, body.session_id)
    conn.close()
    return result


def _send_login_code(conn, email: str) -> None:
    code = _new_code()
    conn.execute(
        "INSERT INTO login_otps (email, code_hash, expires_at) "
        "VALUES (%s, %s, now() + make_interval(mins => %s)) "
        "ON CONFLICT (email) DO UPDATE SET code_hash = EXCLUDED.code_hash, "
        "expires_at = EXCLUDED.expires_at, attempts = 0, last_sent_at = now()",
        (email, _code_hash(email, code), OTP_MINUTES),
    )
    try:
        send_otp_email(email, code, OTP_MINUTES, "login")
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error))


@router.post("/login/start")
def login_start(body: LoginRequest) -> dict:
    """Step 1 of sign-in: check the password, then email a 5-digit code.

    No session is created yet - that only happens once the code is verified.
    """
    email = body.email.strip().lower()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE lower(email) = %s", (email,)
        ).fetchone()
        if not verify_password(body.password, row["password_hash"] if row else None):
            raise HTTPException(status_code=401, detail="Incorrect email or password.")
        _send_login_code(conn, email)
        conn.commit()
    conn.close()
    return {"email": email, "expires_in_minutes": OTP_MINUTES}


@router.post("/login/resend")
def login_resend(body: LoginOtpRequest) -> dict:
    email = body.email.strip().lower()
    with get_connection() as conn:
        pending = conn.execute(
            "SELECT extract(epoch FROM now() - last_sent_at) AS age FROM login_otps WHERE email = %s",
            (email,),
        ).fetchone()
        if pending is None:
            raise HTTPException(status_code=404, detail="Sign-in expired - please start again.")
        if pending["age"] < OTP_RESEND_SECONDS:
            raise HTTPException(
                status_code=429, detail="Please wait a few seconds before requesting another code."
            )
        _send_login_code(conn, email)
        conn.commit()
    conn.close()
    return {"ok": True}


@router.post("/login/verify")
def login_verify(body: VerifyRequest, response: Response) -> dict:
    """Step 2 of sign-in: check the emailed code, then start the session."""
    email = body.email.strip().lower()
    with get_connection() as conn:
        pending = conn.execute("SELECT * FROM login_otps WHERE email = %s", (email,)).fetchone()
        if pending is None or pending["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="That code has expired - request a new one.")
        if pending["attempts"] >= OTP_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Too many wrong attempts - request a new code.")
        if not hmac.compare_digest(pending["code_hash"], _code_hash(email, body.code.strip())):
            conn.execute("UPDATE login_otps SET attempts = attempts + 1 WHERE email = %s", (email,))
            conn.commit()
            raise HTTPException(status_code=400, detail="Incorrect code. Check your email and try again.")
        row = conn.execute(
            "SELECT id, email, name, role FROM users WHERE lower(email) = %s", (email,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=400, detail="That code has expired - request a new one.")
        conn.execute("DELETE FROM login_otps WHERE email = %s", (email,))
        result = _finish_login(response, conn, dict(row), body.session_id)
    conn.close()
    return result


@router.post("/google")
def google_login(body: GoogleRequest, response: Response) -> dict:
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google sign-in isn't configured.")
    # Google verifies the signature and expiry for us at this endpoint; we
    # still check the audience (our client ID) so a token minted for some
    # OTHER app can't be replayed here.
    try:
        reply = httpx.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": body.credential},
            timeout=10,
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Couldn't reach Google - try again.")
    info = reply.json() if reply.status_code == 200 else {}
    if info.get("aud") != GOOGLE_CLIENT_ID or str(info.get("email_verified")).lower() != "true":
        raise HTTPException(status_code=401, detail="Google sign-in failed.")

    sub, email = info["sub"], info["email"].lower()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, email, name, role, google_sub, password_hash FROM users "
            "WHERE google_sub = %s OR lower(email) = %s",
            (sub, email),
        ).fetchone()
        if row is None:
            user = conn.execute(
                "INSERT INTO users (email, name, google_sub) VALUES (%s, %s, %s) "
                "RETURNING id, email, name, role",
                (email, info.get("name") or email.split("@")[0], sub),
            ).fetchone()
        else:
            if row["google_sub"] is None:
                # Email accounts are OTP-verified, so it's safe to link the
                # Google identity to the existing account.
                conn.execute("UPDATE users SET google_sub = %s WHERE id = %s", (sub, row["id"]))
            user = {k: row[k] for k in ("id", "email", "name", "role")}
        result = _finish_login(response, conn, user, body.session_id)
    conn.close()
    return result


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with get_connection() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = %s", (token_hash(token),))
            conn.commit()
        conn.close()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(current_user)) -> dict:
    return {"user": public_user(user)}
