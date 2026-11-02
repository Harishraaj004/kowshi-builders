"""
app/admin.py
=============
The admin console's backend (static/admin.html): the client list, every
appointment request, and the accept / ask-to-change-the-time actions.

Everything here needs the "user:manage" permission, which only the admin
role has. Admins sign in with email + password on /admin (no emailed code),
and ONLY admin accounts can use that sign-in.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import (
    ADMIN_COOKIE_NAME,
    ADMIN_COOKIE_PATH,
    ADMIN_EMAILS,
    LoginRequest,
    hash_password,
    public_user,
    get_user_from_request,
    has_permission,
    start_session,
    token_hash,
    verify_password,
)
from app.config import ADMIN_EMAIL, ADMIN_PASSWORD
from app.database import get_connection

log = logging.getLogger("uvicorn.error")


def sync_admin_account() -> None:
    """Make the ADMIN_EMAIL / ADMIN_PASSWORD from .env a real admin account.

    Runs at startup. The password is only re-hashed when it differs from the
    stored one, so restarts don't churn the database.
    """
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        log.warning("ADMIN_EMAIL / ADMIN_PASSWORD not set - no admin account is managed from .env.")
        return
    if len(ADMIN_PASSWORD) < 8:
        log.error("ADMIN_PASSWORD must be at least 8 characters - admin account not synced.")
        return
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, role, password_hash FROM users WHERE lower(email) = %s", (ADMIN_EMAIL,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (email, name, password_hash, role) VALUES (%s, 'Admin', %s, 'admin')",
                (ADMIN_EMAIL, hash_password(ADMIN_PASSWORD)),
            )
        elif row["role"] != "admin" or not verify_password(ADMIN_PASSWORD, row["password_hash"]):
            conn.execute(
                "UPDATE users SET role = 'admin', password_hash = %s WHERE id = %s",
                (hash_password(ADMIN_PASSWORD), row["id"]),
            )
        conn.commit()
    conn.close()


router = APIRouter(prefix="/api/admin", tags=["admin"])


def admin_only(request: Request) -> dict:
    """The signed-in admin, read from the ADMIN cookie only - a customer's
    session cookie never grants access here, and vice versa."""
    user = get_user_from_request(request, ADMIN_COOKIE_NAME)
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    if not has_permission(user, "user:manage"):
        raise HTTPException(status_code=403, detail="You don't have access to this.")
    return user


@router.post("/login")
def admin_login(body: LoginRequest, response: Response) -> dict:
    email = body.email.strip().lower()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, email, name, role, password_hash FROM users WHERE lower(email) = %s",
            (email,),
        ).fetchone()
        ok = verify_password(body.password, row["password_hash"] if row else None)
        # Same message for "wrong password" and "not an admin" so this page
        # doesn't reveal which emails exist or who is staff.
        if not ok or not (row["role"] == "admin" or email in ADMIN_EMAILS):
            raise HTTPException(status_code=401, detail="Incorrect email or password.")
        if row["role"] != "admin":
            conn.execute("UPDATE users SET role = 'admin' WHERE id = %s", (row["id"],))
            conn.commit()
        user = {"id": row["id"], "email": row["email"], "name": row["name"], "role": "admin"}
    conn.close()
    start_session(response, user["id"], ADMIN_COOKIE_NAME, ADMIN_COOKIE_PATH)
    return {"user": public_user(user)}


@router.get("/me")
def admin_me(user: dict = Depends(admin_only)) -> dict:
    return {"user": public_user(user)}


@router.post("/logout")
def admin_logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(ADMIN_COOKIE_NAME)
    if token:
        with get_connection() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = %s", (token_hash(token),))
            conn.commit()
        conn.close()
    response.delete_cookie(ADMIN_COOKIE_NAME, path=ADMIN_COOKIE_PATH)
    return {"ok": True}


@router.get("/clients")
def clients(user: dict = Depends(admin_only)) -> dict:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT u.id, u.name, u.email, u.created_at, "
            "(SELECT count(*) FROM projects p WHERE p.customer_id = u.id) AS projects, "
            "(SELECT count(*) FROM appointments a JOIN projects p ON p.id = a.project_id "
            " WHERE p.customer_id = u.id AND a.status IN ('requested','change_requested')) AS open_requests, "
            "(SELECT q.details->>'location' FROM projects p JOIN quotes q ON q.id = p.quote_id "
            " WHERE p.customer_id = u.id ORDER BY p.created_at DESC LIMIT 1) AS latest_location "
            "FROM users u WHERE u.role = 'customer' ORDER BY u.created_at DESC"
        ).fetchall()
    conn.close()
    return {"clients": rows}


@router.get("/appointments")
def appointments(user: dict = Depends(admin_only)) -> dict:
    """Every appointment, with who it is for - feeds both the request list
    and the calendar."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT a.id, a.kind, a.status, a.scheduled_for, a.proposed_for, a.notes, "
            "a.admin_note, a.created_at, a.project_id, "
            "c.id AS customer_id, c.name AS customer_name, c.email AS customer_email, "
            "q.details->>'location' AS location "
            "FROM appointments a JOIN projects p ON p.id = a.project_id "
            "JOIN users c ON c.id = p.customer_id JOIN quotes q ON q.id = p.quote_id "
            "ORDER BY a.scheduled_for"
        ).fetchall()
    conn.close()
    return {"appointments": rows}


def _open_appointment(conn, appointment_id: int) -> dict:
    appt = conn.execute("SELECT * FROM appointments WHERE id = %s", (appointment_id,)).fetchone()
    if appt is None:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    if appt["status"] not in ("requested", "confirmed", "change_requested"):
        raise HTTPException(status_code=409, detail="This appointment is already closed.")
    return appt


@router.post("/appointments/{appointment_id}/accept")
def accept(appointment_id: int, user: dict = Depends(admin_only)) -> dict:
    with get_connection() as conn:
        appt = _open_appointment(conn, appointment_id)
        if appt["status"] != "requested":
            raise HTTPException(status_code=409, detail="Only a new request can be accepted.")
        conn.execute(
            "UPDATE appointments SET status = 'confirmed', admin_note = '', "
            "proposed_for = NULL, updated_at = now() WHERE id = %s",
            (appointment_id,),
        )
        conn.commit()
    conn.close()
    return {"ok": True}


class ChangeRequest(BaseModel):
    proposed_for: datetime
    message: str = Field(default="", max_length=500)


@router.post("/appointments/{appointment_id}/request-change")
def request_change(
    appointment_id: int, body: ChangeRequest, user: dict = Depends(admin_only)
) -> dict:
    """Ask the client to move the appointment to a different time. The client
    sees the proposed time and message on their dashboard and can accept it
    or suggest another."""
    if body.proposed_for.tzinfo is None:
        raise HTTPException(status_code=422, detail="Time must include a timezone.")
    if body.proposed_for <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Please propose a time in the future.")
    with get_connection() as conn:
        _open_appointment(conn, appointment_id)
        conn.execute(
            "UPDATE appointments SET status = 'change_requested', proposed_for = %s, "
            "admin_note = %s, updated_at = now() WHERE id = %s",
            (body.proposed_for, body.message.strip(), appointment_id),
        )
        conn.commit()
    conn.close()
    return {"ok": True}
