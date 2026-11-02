"""
app/projects.py
================
The customer dashboard's backend: projects (created from a chat quote),
the five tracked stages, call / site-visit appointments, approval
documents, and the staff actions (confirm, review, assign, set start date).

STAGES ARE COMPUTED, NOT STORED
-------------------------------
The dashboard shows five stages:
    1. Initial quote            - done as soon as the project exists
    2. Discussion with engineer - a "discussion" appointment
    3. Site visit               - a "site_visit" appointment
    4. Approval documents       - every required document approved
    5. Start of work            - work_start_date set by staff
Each stage's status (pending / in_progress / completed) is derived from the
underlying rows in `compute_stages`, so there's no second copy of the truth
to keep in sync.

ACCESS RULES (on top of the role permissions in app/auth.py)
------------------------------------------------------------
    customer  -> only projects they own
    engineer  -> only projects assigned to them
    admin     -> every project
A project you can't access returns 404 (not 403) so ids can't be probed.
"""

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.auth import current_user, has_permission, require_permission, ROLES
from app.config import UPLOAD_DIR
from app.database import get_connection

LIVE_STATUSES = ("requested", "confirmed", "change_requested")

STAGES = [
    ("quote", "Initial quote"),
    ("discussion", "Discussion with engineer"),
    ("site_visit", "Site visit"),
    ("documents", "Approval documents"),
    ("work_start", "Start of work"),
]

# Illustrative list for building approvals in Tamil Nadu - adjust to the
# paperwork your engineers actually collect.
REQUIRED_DOCUMENTS = [
    ("id_proof", "Owner ID proof (Aadhaar / PAN)"),
    ("land_title", "Land title deed / Patta"),
    ("encumbrance", "Encumbrance certificate"),
    ("tax_receipt", "Latest property tax receipt"),
    ("site_plan", "Site plan / survey sketch"),
]
DOC_LABELS = dict(REQUIRED_DOCUMENTS)

ALLOWED_UPLOADS = {
    # extension -> magic bytes the file must start with
    ".pdf": (b"%PDF",),
    ".png": (b"\x89PNG",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

upload_root = Path(UPLOAD_DIR).resolve()


# --- Quotes -> projects --------------------------------------------------------
def save_quote(conn, chat_session_id: str, details: dict, user_id: int | None) -> int:
    """Persist a quote produced by the chat; if the visitor is already signed
    in as a customer, give them their project straight away."""
    quote_id = conn.execute(
        "INSERT INTO quotes (chat_session_id, details, user_id) VALUES (%s, %s, %s) RETURNING id",
        (chat_session_id, json.dumps(details), user_id),
    ).fetchone()["id"]
    if user_id is not None:
        create_project(conn, user_id, quote_id)
    return quote_id


def create_project(conn, customer_id: int, quote_id: int) -> None:
    conn.execute(
        "INSERT INTO projects (customer_id, quote_id) VALUES (%s, %s) "
        "ON CONFLICT (quote_id) DO NOTHING",
        (customer_id, quote_id),
    )


def claim_chat_quotes(conn, user_id: int, chat_session_id: str) -> None:
    """Attach the anonymous visitor's quotes to the account they just made
    or signed into. The newest quote becomes the project; older ones (earlier
    what-if estimates in the same chat) are kept on the account only."""
    claimed = conn.execute(
        "UPDATE quotes SET user_id = %s WHERE chat_session_id = %s AND user_id IS NULL "
        "RETURNING id",
        (user_id, chat_session_id),
    ).fetchall()
    if claimed:
        create_project(conn, user_id, max(row["id"] for row in claimed))


# --- Access control -------------------------------------------------------------
def load_project(conn, user: dict, project_id: int) -> dict:
    row = conn.execute(
        "SELECT p.*, q.details AS quote, q.created_at AS quote_created_at, "
        "c.name AS customer_name, c.email AS customer_email, "
        "e.name AS engineer_name FROM projects p "
        "JOIN quotes q ON q.id = p.quote_id "
        "JOIN users c ON c.id = p.customer_id "
        "LEFT JOIN users e ON e.id = p.engineer_id WHERE p.id = %s",
        (project_id,),
    ).fetchone()
    allowed = row is not None and (
        has_permission(user, "project:view_all")
        or (has_permission(user, "project:view_own") and row["customer_id"] == user["id"])
        or (has_permission(user, "project:view_assigned") and row["engineer_id"] == user["id"])
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="Project not found.")
    return row


# --- Stage computation ----------------------------------------------------------
def compute_stages(project: dict, appointments: list[dict], documents: list[dict]) -> list[dict]:
    def appointment_status(kind: str) -> str:
        mine = [a["status"] for a in appointments if a["kind"] == kind]
        if "completed" in mine:
            return "completed"
        return "in_progress" if any(s in LIVE_STATUSES for s in mine) else "pending"

    approved = {d["doc_type"] for d in documents if d["status"] == "approved"}
    if all(key in approved for key, _ in REQUIRED_DOCUMENTS):
        docs_status = "completed"
    elif documents:
        docs_status = "in_progress"
    else:
        docs_status = "pending"

    start = project["work_start_date"]
    if start is None:
        work_status = "pending"
    else:
        work_status = "completed" if start <= date.today() else "in_progress"

    statuses = {
        "quote": "completed",
        "discussion": appointment_status("discussion"),
        "site_visit": appointment_status("site_visit"),
        "documents": docs_status,
        "work_start": work_status,
    }
    return [{"key": k, "label": label, "status": statuses[k]} for k, label in STAGES]


def project_summary(project: dict, stages: list[dict]) -> dict:
    quote = project["quote"]
    done = sum(1 for s in stages if s["status"] == "completed")
    current = next((s for s in stages if s["status"] != "completed"), None)
    return {
        "id": project["id"],
        "location": quote.get("location"),
        "total_cost": quote.get("total_cost"),
        "customer_name": project["customer_name"],
        "engineer_name": project["engineer_name"],
        "progress": {"done": done, "total": len(stages)},
        "current_stage": current["label"] if current else "All stages complete",
        "created_at": project["created_at"],
    }


def _stages_for(conn, project: dict) -> tuple[list, list, list]:
    appointments = conn.execute(
        "SELECT * FROM appointments WHERE project_id = %s ORDER BY created_at DESC, id DESC",
        (project["id"],),
    ).fetchall()
    documents = conn.execute(
        "SELECT id, doc_type, original_name, size_bytes, status, review_note, uploaded_at "
        "FROM documents WHERE project_id = %s",
        (project["id"],),
    ).fetchall()
    return appointments, documents, compute_stages(project, appointments, documents)


# --- Routes ---------------------------------------------------------------------
router = APIRouter(prefix="/api", tags=["projects"])


@router.get("/projects")
def list_projects(user: dict = Depends(current_user)) -> dict:
    if has_permission(user, "project:view_all"):
        where, params = "TRUE", ()
    elif has_permission(user, "project:view_assigned"):
        where, params = "p.engineer_id = %s", (user["id"],)
    else:
        where, params = "p.customer_id = %s", (user["id"],)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT p.*, q.details AS quote, c.name AS customer_name, e.name AS engineer_name "
            "FROM projects p JOIN quotes q ON q.id = p.quote_id "
            "JOIN users c ON c.id = p.customer_id "
            f"LEFT JOIN users e ON e.id = p.engineer_id WHERE {where} "
            "ORDER BY p.created_at DESC",
            params,
        ).fetchall()
        projects = []
        for row in rows:
            _, _, stages = _stages_for(conn, row)
            projects.append(project_summary(row, stages))
    conn.close()
    return {"projects": projects}


@router.get("/projects/{project_id}")
def get_project(project_id: int, user: dict = Depends(current_user)) -> dict:
    with get_connection() as conn:
        project = load_project(conn, user, project_id)
        appointments, documents, stages = _stages_for(conn, project)
    conn.close()
    by_type = {d["doc_type"]: d for d in documents}
    return {
        **project_summary(project, stages),
        "quote": project["quote"],
        "customer_email": project["customer_email"],
        "work_start_date": project["work_start_date"],
        "stages": stages,
        "appointments": appointments,
        "documents": [
            {"doc_type": key, "label": label, "upload": by_type.get(key)}
            for key, label in REQUIRED_DOCUMENTS
        ],
    }


class AppointmentRequest(BaseModel):
    kind: str = Field(pattern="^(discussion|site_visit)$")
    scheduled_for: datetime
    notes: str = Field(default="", max_length=500)


@router.post("/projects/{project_id}/appointments")
def request_appointment(
    project_id: int,
    body: AppointmentRequest,
    user: dict = Depends(require_permission("appointment:request")),
) -> dict:
    if body.scheduled_for.tzinfo is None:
        raise HTTPException(status_code=422, detail="Time must include a timezone.")
    if body.scheduled_for <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Please pick a time in the future.")
    with get_connection() as conn:
        project = load_project(conn, user, project_id)
        if project["customer_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="Project not found.")
        live = conn.execute(
            "SELECT 1 FROM appointments WHERE project_id = %s AND kind = %s "
            "AND status IN ('requested','confirmed','change_requested')",
            (project_id, body.kind),
        ).fetchone()
        if live:
            raise HTTPException(
                status_code=409, detail="You already have one scheduled - cancel it first to change the time."
            )
        conn.execute(
            "INSERT INTO appointments (project_id, kind, scheduled_for, notes) VALUES (%s,%s,%s,%s)",
            (project_id, body.kind, body.scheduled_for, body.notes.strip()),
        )
        conn.commit()
    conn.close()
    return {"ok": True}


class AppointmentUpdate(BaseModel):
    status: str = Field(pattern="^(confirmed|completed|cancelled)$")
    scheduled_for: datetime | None = None


@router.patch("/appointments/{appointment_id}")
def update_appointment(
    appointment_id: int, body: AppointmentUpdate, user: dict = Depends(current_user)
) -> dict:
    with get_connection() as conn:
        appt = conn.execute("SELECT * FROM appointments WHERE id = %s", (appointment_id,)).fetchone()
        if appt is None:
            raise HTTPException(status_code=404, detail="Appointment not found.")
        project = load_project(conn, user, appt["project_id"])  # 404 if no access
        is_staff = has_permission(user, "appointment:manage")
        # Customers may only cancel their own; staff can confirm / complete /
        # cancel / reschedule.
        if not is_staff and (body.status != "cancelled" or project["customer_id"] != user["id"]):
            raise HTTPException(status_code=403, detail="You don't have access to this.")
        if appt["status"] in ("completed", "cancelled"):
            raise HTTPException(status_code=409, detail="This appointment is already closed.")
        if body.scheduled_for is not None:
            if not is_staff:
                raise HTTPException(status_code=403, detail="You don't have access to this.")
            if body.scheduled_for.tzinfo is None:
                raise HTTPException(status_code=422, detail="Time must include a timezone.")
        conn.execute(
            "UPDATE appointments SET status = %s, scheduled_for = COALESCE(%s, scheduled_for), "
            "proposed_for = NULL, updated_at = now() WHERE id = %s",
            (body.status, body.scheduled_for, appointment_id),
        )
        conn.commit()
    conn.close()
    return {"ok": True}


class AppointmentResponse(BaseModel):
    action: str = Field(pattern="^(accept|counter)$")
    scheduled_for: datetime | None = None


@router.post("/appointments/{appointment_id}/respond")
def respond_to_change(
    appointment_id: int,
    body: AppointmentResponse,
    user: dict = Depends(require_permission("appointment:request")),
) -> dict:
    """The client's answer when the admin asked them to change the time:
    accept the proposed time, or suggest a different one."""
    with get_connection() as conn:
        appt = conn.execute("SELECT * FROM appointments WHERE id = %s", (appointment_id,)).fetchone()
        if appt is None:
            raise HTTPException(status_code=404, detail="Appointment not found.")
        project = load_project(conn, user, appt["project_id"])
        if project["customer_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="Appointment not found.")
        if appt["status"] != "change_requested" or appt["proposed_for"] is None:
            raise HTTPException(status_code=409, detail="There's no time change waiting for your answer.")
        if body.action == "accept":
            conn.execute(
                "UPDATE appointments SET status = 'confirmed', scheduled_for = proposed_for, "
                "proposed_for = NULL, updated_at = now() WHERE id = %s",
                (appointment_id,),
            )
        else:
            when = body.scheduled_for
            if when is None or when.tzinfo is None:
                raise HTTPException(status_code=422, detail="Pick a new time (with timezone).")
            if when <= datetime.now(timezone.utc):
                raise HTTPException(status_code=422, detail="Please pick a time in the future.")
            conn.execute(
                "UPDATE appointments SET status = 'requested', scheduled_for = %s, "
                "proposed_for = NULL, updated_at = now() WHERE id = %s",
                (when, appointment_id),
            )
        conn.commit()
    conn.close()
    return {"ok": True}


@router.post("/projects/{project_id}/documents")
async def upload_document(
    project_id: int,
    doc_type: str = Form(),
    file: UploadFile = File(),
    user: dict = Depends(require_permission("document:upload")),
) -> dict:
    if doc_type not in DOC_LABELS:
        raise HTTPException(status_code=422, detail="Unknown document type.")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_UPLOADS:
        raise HTTPException(status_code=422, detail="Upload a PDF, PNG or JPG file.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 10 MB.")
    if not data.startswith(ALLOWED_UPLOADS[ext]):
        raise HTTPException(status_code=422, detail="That file doesn't look like a valid " + ext[1:].upper() + ".")

    with get_connection() as conn:
        project = load_project(conn, user, project_id)
        if project["customer_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="Project not found.")
        existing = conn.execute(
            "SELECT id, status, stored_name FROM documents WHERE project_id = %s AND doc_type = %s",
            (project_id, doc_type),
        ).fetchone()
        if existing and existing["status"] == "approved":
            raise HTTPException(status_code=409, detail="This document is already approved.")

        upload_root.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}{ext}"
        (upload_root / stored_name).write_bytes(data)
        original = Path(file.filename or "document").name[:200]
        conn.execute(
            "INSERT INTO documents (project_id, doc_type, original_name, stored_name, size_bytes) "
            "VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (project_id, doc_type) DO UPDATE SET original_name = EXCLUDED.original_name, "
            "stored_name = EXCLUDED.stored_name, size_bytes = EXCLUDED.size_bytes, "
            "status = 'pending', review_note = '', uploaded_at = now()",
            (project_id, doc_type, original, stored_name, len(data)),
        )
        conn.commit()
        if existing:
            (upload_root / existing["stored_name"]).unlink(missing_ok=True)
    conn.close()
    return {"ok": True}


@router.get("/documents/{document_id}/download")
def download_document(document_id: int, user: dict = Depends(current_user)):
    with get_connection() as conn:
        doc = conn.execute("SELECT * FROM documents WHERE id = %s", (document_id,)).fetchone()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        load_project(conn, user, doc["project_id"])  # 404 if no access
    conn.close()
    path = upload_root / doc["stored_name"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File is missing.")
    return FileResponse(path, filename=doc["original_name"], content_disposition_type="attachment")


class DocumentReview(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")
    review_note: str = Field(default="", max_length=500)


@router.patch("/documents/{document_id}")
def review_document(
    document_id: int,
    body: DocumentReview,
    user: dict = Depends(require_permission("document:review")),
) -> dict:
    with get_connection() as conn:
        doc = conn.execute("SELECT project_id FROM documents WHERE id = %s", (document_id,)).fetchone()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        load_project(conn, user, doc["project_id"])
        conn.execute(
            "UPDATE documents SET status = %s, review_note = %s WHERE id = %s",
            (body.status, body.review_note.strip(), document_id),
        )
        conn.commit()
    conn.close()
    return {"ok": True}


class StartDate(BaseModel):
    work_start_date: date | None


@router.put("/projects/{project_id}/start-date")
def set_start_date(
    project_id: int,
    body: StartDate,
    user: dict = Depends(require_permission("project:schedule_start")),
) -> dict:
    with get_connection() as conn:
        load_project(conn, user, project_id)
        conn.execute(
            "UPDATE projects SET work_start_date = %s WHERE id = %s", (body.work_start_date, project_id)
        )
        conn.commit()
    conn.close()
    return {"ok": True}


class Assignment(BaseModel):
    engineer_id: int | None


@router.put("/projects/{project_id}/engineer")
def assign_engineer(
    project_id: int,
    body: Assignment,
    user: dict = Depends(require_permission("project:assign")),
) -> dict:
    with get_connection() as conn:
        load_project(conn, user, project_id)
        if body.engineer_id is not None and not conn.execute(
            "SELECT 1 FROM users WHERE id = %s AND role = 'engineer'", (body.engineer_id,)
        ).fetchone():
            raise HTTPException(status_code=422, detail="That user isn't an engineer.")
        conn.execute("UPDATE projects SET engineer_id = %s WHERE id = %s", (body.engineer_id, project_id))
        conn.commit()
    conn.close()
    return {"ok": True}


# --- Admin: user & role management ------------------------------------------------
@router.get("/admin/users")
def list_users(user: dict = Depends(require_permission("user:manage"))) -> dict:
    with get_connection() as conn:
        users = conn.execute(
            "SELECT id, email, name, role, created_at FROM users ORDER BY created_at"
        ).fetchall()
    conn.close()
    return {"users": users, "roles": list(ROLES)}


class RoleChange(BaseModel):
    role: str


@router.patch("/admin/users/{user_id}")
def change_role(
    user_id: int, body: RoleChange, user: dict = Depends(require_permission("user:manage"))
) -> dict:
    if body.role not in ROLES:
        raise HTTPException(status_code=422, detail="Unknown role.")
    if user_id == user["id"]:
        raise HTTPException(status_code=409, detail="You can't change your own role.")
    with get_connection() as conn:
        updated = conn.execute(
            "UPDATE users SET role = %s WHERE id = %s RETURNING id", (body.role, user_id)
        ).fetchone()
        if updated is None:
            raise HTTPException(status_code=404, detail="User not found.")
        conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/engineers")
def list_engineers(user: dict = Depends(require_permission("project:assign"))) -> dict:
    with get_connection() as conn:
        rows = conn.execute("SELECT id, name, email FROM users WHERE role = 'engineer' ORDER BY name").fetchall()
    conn.close()
    return {"engineers": rows}
