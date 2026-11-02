"""
app/database.py
=================
Stores conversation history so the AI can remember what was said earlier
in the SAME conversation - now backed by PostgreSQL instead of SQLite.

WHY SWITCH FROM SQLITE TO POSTGRES?
---------------------------------------
SQLite (Stage 3) was a single FILE (kowshi.db) that our own Python
process read and wrote directly - simple, zero setup, but everything
lived on one machine, in one file, accessed by one process at a time.

PostgreSQL is a completely separate SERVER PROCESS - possibly running on
a different machine entirely - that many applications can connect to
over the network at once. That's the standard setup for anything beyond
a single-developer prototype: a real deployment usually has the web
server and the database server as two separate things (sometimes on two
separate machines), and Postgres is one of the most widely used open
-source databases for exactly that role.

Concretely, here's what changes and what doesn't:
  - We connect over a NETWORK SOCKET (via a connection string in
    app/config.py's DATABASE_URL) instead of opening a local file.
  - SQL placeholders are %s instead of SQLite's ? (a driver-specific
    detail - the SQL itself is otherwise almost identical).
  - Auto-incrementing IDs use the SERIAL type instead of SQLite's
    INTEGER PRIMARY KEY AUTOINCREMENT.
  - Timestamps use Postgres's TIMESTAMPTZ + now() instead of SQLite's
    TEXT + datetime('now').
  - The overall SHAPE of this file - get_connection(), init_db(),
    add_message(), get_conversation_history() - is intentionally
    UNCHANGED from Stage 3, and nothing in app/main.py or app/llm.py had
    to change at all. That's the whole point of keeping a dedicated
    database module: every OTHER file only ever calls these four
    functions, so swapping what's on the other side of them is a
    one-file change.
"""

import os

import psycopg
from psycopg.rows import dict_row

from app.config import DATABASE_URL


def _is_pooled(url: str) -> bool:
    return "-pooler." in url


def _direct_url() -> str:
    """Non-pooled URL: Neon's DATABASE_URL_UNPOOLED, else DATABASE_URL minus "-pooler"."""
    return os.getenv("DATABASE_URL_UNPOOLED") or DATABASE_URL.replace("-pooler.", ".", 1)


def get_connection(direct: bool = False) -> psycopg.Connection:
    """
    Opens a fresh connection to the Postgres database.

    Just like the SQLite version, we open a NEW connection every time we
    need one rather than sharing one long-lived connection across the
    whole app - simple and safe across FastAPI's multiple worker threads.
    A high-traffic production system would instead use a "connection
    pool" (a small set of connections reused across requests, since
    opening a network connection is more expensive than opening a local
    file) - psycopg_pool exists for exactly that, but it's more
    machinery than a project this size needs yet.

    row_factory=dict_row makes each result row come back as a plain
    dict (row["role"], row["content"]) instead of a bare tuple where
    you'd have to remember that index 0 is the role and index 1 is the
    content - the same reasoning as SQLite's row_factory = sqlite3.Row
    from Stage 3.
    """
    # search_path decides which schema an unqualified table name means.
    # The dashboard tables (users, projects, ...) live in their own
    # "dashboard" schema so they can't collide with tables that already
    # exist in this database's default "public" schema (it already has its
    # own `projects`, for instance). Chat `messages` stays in public and is
    # always referred to as public.messages below.
    #
    # Neon's pooled endpoint (host contains "-pooler", PgBouncer) rejects
    # startup options, so there we connect without them and rely on a
    # ROLE-level search_path that init_db() sets once over a direct
    # connection (see _direct_url / init_db). Non-pooled URLs (local
    # Postgres, Neon direct) keep using the startup option.
    if direct or not _is_pooled(DATABASE_URL):
        return psycopg.connect(
            _direct_url() if direct else DATABASE_URL,
            row_factory=dict_row,
            options="-c search_path=dashboard,public",
        )
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


# Accounts, quotes, projects, appointments and documents. Everything the
# customer dashboard shows is derived from these tables - note there is NO
# stored "stage status": stages are computed from the facts below (see
# app/projects.py), so they can never drift out of sync with reality.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT,
    google_sub TEXT UNIQUE,
    role TEXT NOT NULL DEFAULT 'customer'
        CHECK (role IN ('customer', 'engineer', 'admin')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users (lower(email));

-- A signup waiting for its emailed code. The account itself is only created
-- once the code is verified, so unverified emails never become users.
CREATE TABLE IF NOT EXISTS signup_otps (
    email TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_sent_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A sign-in waiting for its emailed code (password already checked).
CREATE TABLE IF NOT EXISTS login_otps (
    email TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_sent_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS quotes (
    id SERIAL PRIMARY KEY,
    chat_session_id TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    details JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_quotes_chat_session ON quotes (chat_session_id);

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    quote_id INTEGER NOT NULL UNIQUE REFERENCES quotes(id),
    engineer_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    work_start_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS appointments (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('discussion', 'site_visit')),
    scheduled_for TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'requested'
        CHECK (status IN ('requested', 'confirmed', 'completed', 'cancelled')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- The admin can ask the client to change the time ('change_requested'): the
-- proposed time and a short message are stored on the appointment so the
-- client's dashboard can show them. These statements are re-run on every
-- start, so each one is idempotent.
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS proposed_for TIMESTAMPTZ;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS admin_note TEXT NOT NULL DEFAULT '';
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_status_check;
ALTER TABLE appointments ADD CONSTRAINT appointments_status_check
    CHECK (status IN ('requested', 'confirmed', 'change_requested', 'completed', 'cancelled'));
-- At most one live appointment per kind per project.
DROP INDEX IF EXISTS idx_appointments_one_active;
CREATE UNIQUE INDEX idx_appointments_one_active
    ON appointments (project_id, kind)
    WHERE status IN ('requested', 'confirmed', 'change_requested');

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    doc_type TEXT NOT NULL,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    review_note TEXT NOT NULL DEFAULT '',
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, doc_type)
);
"""


def init_db() -> None:
    """
    Creates the `messages` table if it doesn't already exist.

    CREATE TABLE IF NOT EXISTS is idempotent - safe to run every time the
    app starts, even if the table (and all its data) already exists from
    a previous run. Called once below, at MODULE IMPORT TIME, so the
    table is guaranteed to exist before any route tries to use it.
    """
    # direct=True: schema setup must see search_path=dashboard,public even
    # when the app itself runs through Neon's pooler.
    with get_connection(direct=True) as connection:
        # A quick tour of this table's columns (identical MEANING to the
        # SQLite version - only the exact type names changed):
        #   id          - SERIAL is Postgres's auto-incrementing integer
        #                 type - conceptually the same as SQLite's
        #                 "INTEGER PRIMARY KEY AUTOINCREMENT", just
        #                 spelled differently.
        #   session_id  - which conversation this message belongs to.
        #   role        - "user" or "assistant".
        #   content     - the actual message text. TEXT has no length
        #                 limit in Postgres, same as SQLite.
        #   created_at  - TIMESTAMPTZ ("timestamp with time zone") is
        #                 Postgres's proper datetime type - unlike
        #                 SQLite (which has no native date/time type and
        #                 stored ours as plain TEXT), Postgres actually
        #                 understands this as a point in time, and
        #                 now() is its equivalent of SQLite's
        #                 datetime('now').
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS public.messages (
                id SERIAL PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        # Same reasoning as Stage 3: we look up "every message for
        # session X" constantly (every chat request), so we keep this
        # column indexed for fast lookups instead of a full table scan.
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session_id "
            "ON public.messages (session_id)"
        )

        # `with get_connection() as connection:` (a context manager)
        # automatically commits when the block exits normally, and rolls
        # back if an exception happened inside it - a convenience
        # psycopg's Connection supports that we didn't use for SQLite
        # (there, we just called connection.commit() directly). Using
        # `with` here doesn't remove the need to commit ourselves - it
        # only means we don't have to remember to on every exit path,
        # including ones we didn't explicitly write a return for. It
        # also does NOT close the connection - we still do that
        # ourselves below, once we're done with it.
        # Serverless cold starts run this concurrently; serialize them (the
        # lock is released automatically at commit).
        connection.execute("SELECT pg_advisory_xact_lock(727274)")
        connection.execute("CREATE SCHEMA IF NOT EXISTS dashboard")
        # Persist the search_path on the role so pooled connections get it
        # (only when missing: concurrent ALTER ROLEs fail with "tuple
        # concurrently updated").
        configured = connection.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = current_user "
            "AND rolconfig::text LIKE '%search_path=dashboard%'"
        ).fetchone()
        if not configured:
            connection.execute(
                "ALTER ROLE CURRENT_USER SET search_path = dashboard, public"
            )
        connection.execute(SCHEMA_SQL)
        connection.commit()
    connection.close()


def add_message(session_id: str, role: str, content: str) -> None:
    """
    Saves one message to the conversation identified by `session_id`.

    Parameters
    ----------
    session_id : str
        Identifies which conversation this message belongs to.
    role : str
        Either "user" or "assistant".
    content : str
        The message text.
    """
    with get_connection() as connection:
        # %s placeholders (not SQLite's ?) - psycopg's parameterized
        # query syntax. The SAFETY reasoning is identical to Stage 3:
        # passing values separately, rather than building SQL with an
        # f-string, is what prevents SQL injection - the values are
        # always treated as pure data, never as part of the SQL command
        # itself, no matter what characters they contain.
        connection.execute(
            "INSERT INTO public.messages (session_id, role, content) VALUES (%s, %s, %s)",
            (session_id, role, content),
        )
        connection.commit()
    connection.close()


def get_conversation_history(session_id: str) -> list[dict]:
    """
    Retrieves every message for one conversation, oldest first, in the
    exact shape Claude's API expects: a list of {"role": ..., "content":
    ...} dicts.

    Parameters
    ----------
    session_id : str
        Identifies which conversation to load.

    Returns
    -------
    list[dict]
        e.g. [{"role": "user", "content": "hi"},
              {"role": "assistant", "content": "hello!"}, ...]
        Empty list if this session_id has no messages yet.
    """
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT role, content FROM public.messages WHERE session_id = %s "
            "ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    connection.close()

    # Each row is ALREADY a plain dict (row_factory=dict_row, set in
    # get_connection() above), and already only has the two columns we
    # selected - so unlike the SQLite version, there's no dict(row)
    # conversion needed here. We still return a fresh list rather than
    # the raw fetchall() result to keep this function's return type
    # obviously a plain list[dict], not tied to any psycopg-specific type.
    return list(rows)


# Run once, the moment this module is first imported (e.g. by
# app/main.py at server startup) - guarantees the table exists before any
# route ever tries to read or write to it. If Postgres isn't reachable
# (wrong DATABASE_URL, server not running), this raises immediately at
# startup - the same "fail fast" philosophy as app/config.py's missing
# -API-key check, rather than failing confusingly on someone's first
# chat message.
init_db()
