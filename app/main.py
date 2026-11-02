"""
app/main.py
===========

This is the ENTRY POINT of our backend. When you run:

    uvicorn app.main:app --reload

Uvicorn (an "ASGI server" - a program whose whole job is to accept network
connections, speak the HTTP protocol, and hand each request to a Python
web application) imports this file, finds the variable named `app` below,
and starts serving it.

WHAT IS FASTAPI, REALLY?
-------------------------
FastAPI is a Python library that lets you say "when a request comes in for
THIS url, run THIS function" and handles all the tedious HTTP plumbing
(parsing headers, reading the request body, validating JSON, formatting
the response, generating docs) for you.

At its absolute core, a backend's job is just:

    request in  ->  Python function runs  ->  response out

Everything else (databases, LLMs, RAG, calculators) we add later just
plugs into the middle of that same loop.

WHY DO WE EVEN NEED A BACKEND?
--------------------------------
The frontend (HTML/CSS/JS running in the user's browser) could try to do
everything itself, but:
  - It can never safely hold secret API keys - anyone can open dev tools
    and read every line of JS that was sent to their browser.
  - It has no direct, trusted line to a database.
  - Any "business logic" written in frontend JS can be tampered with by
    the user (it's running on THEIR machine, under THEIR control).

So the backend is the trusted, server-side half of the system - the part
we control. Later, this is exactly where LLM calls, RAG, and construction
calculators will live. None of that will ever run in the browser.
"""

# --- Imports ---------------------------------------------------------------

# FastAPI: the class we instantiate to create our web application object.
from fastapi import FastAPI, HTTPException, Request

# StaticFiles: a small built-in helper that serves plain files (HTML, CSS,
# JS, images) straight off disk - the same job any generic web server does.
# We use it so the browser can load our chat UI from this SAME backend,
# without needing a second server just for the frontend yet.
from fastapi.staticfiles import StaticFiles

# FileResponse: lets a route return the contents of a single file (here,
# our index.html) as the HTTP response body.
from fastapi.responses import FileResponse

# BaseModel: from Pydantic, the data-validation library FastAPI is built on.
# Subclassing BaseModel lets us describe the *shape* of JSON data we expect
# to receive or send. FastAPI uses these classes to automatically validate
# incoming requests and to auto-generate API documentation - we don't hand
# -write any of that parsing/validation ourselves.
from pydantic import BaseModel

# Path: Python's modern way of handling filesystem paths. We use it to
# reliably locate the "static" folder next to this file, no matter which
# directory you happen to run the `uvicorn` command from.
from pathlib import Path

# get_ai_reply: our own function (app/llm.py) that sends a conversation to
# the LLM and returns its text reply. Importing app.llm ALSO runs the code
# at the top of that file - including app.config's "fail loudly if
# ANTHROPIC_API_KEY is missing" check - so a missing .env is caught the
# moment the server starts, not on someone's first chat message.
from app.llm import get_ai_reply

# add_message / get_conversation_history: our own functions (app/database.py)
# for saving and retrieving conversation history from SQLite. Importing
# app.database ALSO runs init_db() at the bottom of that file, creating the
# messages table if it doesn't exist yet - before any route can use it.
from app.database import add_message, get_connection, get_conversation_history
from app.auth import get_user_from_request, router as auth_router
from app.admin import router as admin_router, sync_admin_account
from app.projects import router as projects_router, save_quote


# --- App setup ---------------------------------------------------------------

# This single line creates our actual application object. Every route we
# define below "attaches" itself to this one `app` object via decorators.
app = FastAPI(
    title="Kowshi Builders - Learning Project",
    description="Stage 3: FastAPI backend + Anthropic's Claude API + SQLite-backed conversation memory.",
    version="0.3.0",
)

# Because FastAPI auto-generates interactive API docs for free, once the
# server is running you can browse them at:
#   http://localhost:8000/docs   (Swagger UI - click "Try it out" on any
#                                  route to fire a real request from the
#                                  browser, no curl needed)
#   http://localhost:8000/redoc  (a read-only, nicer-looking alternative)

# `Path(__file__)` = the path to THIS file (app/main.py).
# `.resolve()` = turn it into an absolute path.
# `.parent` = the folder containing this file -> ".../app"
# `.parent` again = the project root -> "D:/Kowshi builders agent"
# then "/ static" points at our sibling "static" folder.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


# --- Data models: the "shape" of our JSON --------------------------------

# When the frontend sends a chat message to the backend, it will POST JSON
# that looks like:
#     { "message": "hello", "session_id": "a1b2c3d4-..." }
#
# `session_id` is new in Stage 3 - it identifies WHICH conversation this
# message belongs to (see static/script.js for how the frontend generates
# and remembers it). Without it, we'd have no way to tell two different
# visitors' conversations apart, or to know which past messages belong
# with this new one.
#
# Declaring this class tells FastAPI: "expect a JSON object with exactly
# these two fields, both strings." If the frontend ever sends something
# that doesn't match (missing field, wrong type, junk data), FastAPI
# automatically rejects it with a clear 422 error - we never wrote a
# single line of that validation ourselves.
class ChatRequest(BaseModel):
    message: str
    session_id: str


# Likewise, our reply will be JSON shaped like:
#     { "reply": "You said: hello" }
#
# Declaring the response shape (in addition to the request shape) keeps
# our API's "contract" explicit, and it shows up automatically in the
# /docs page mentioned above.
class ChatResponse(BaseModel):
    reply: str
    # Set when this reply contained a freshly calculated quote, so the
    # frontend can show the sign-up / sign-in prompt (or, if the visitor
    # is already signed in, a link to the project on their dashboard).
    quote_id: int | None = None
    project_id: int | None = None


# One message, as returned by GET /api/history/{session_id} below - the
# same {"role": ..., "content": ...} shape app/database.py already uses
# internally, just formalized as a Pydantic model so FastAPI validates
# and documents it like everything else.
class HistoryMessage(BaseModel):
    role: str
    content: str


class HistoryResponse(BaseModel):
    messages: list[HistoryMessage]
    # Latest quote in this chat that nobody has claimed yet - lets the
    # sign-up prompt reappear after a page reload.
    unclaimed_quote_id: int | None = None


# --- Routes ------------------------------------------------------------------
# A "route" is a (HTTP method, URL path) pair mapped to a Python function.
# The @app.get(...) / @app.post(...) lines are "decorators" - a bit of
# Python syntax that says "register the function right below this line
# as the handler for this route."

@app.get("/", include_in_schema=False)
def serve_frontend() -> FileResponse:
    """
    GET /

    When someone opens http://localhost:8000/ in a browser, the browser
    sends an HTTP GET request for the path "/". This function handles
    that by returning our index.html file. The browser then parses that
    HTML, sees it references /static/style.css and /static/script.js,
    and fires off two MORE GET requests to fetch those (handled below by
    the StaticFiles mount) - all before anything renders on screen.
    """
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health_check() -> dict:
    """
    GET /api/health

    A "health check" endpoint is a near-universal backend convention. It
    answers exactly one question: "is this server up and responding?"
    Deploy pipelines, monitoring tools, and load balancers ping this
    constantly and expect a fast, boring answer.

    Whatever plain Python value we return (here, a dict) FastAPI
    automatically serializes to JSON and sends back with the header
    `Content-Type: application/json` - we never call `json.dumps`
    ourselves.
    """
    return {"status": "ok"}


@app.get("/api/history/{session_id}")
def get_history(session_id: str) -> HistoryResponse:
    """
    GET /api/history/{session_id}

    Returns every past message for one conversation, oldest first. The
    frontend calls this once, right when the page first loads, to
    re-populate the chat window with whatever was said in earlier visits
    - without this, the AI would remember the conversation (it's in
    SQLite), but the user would see an empty chat log after every page
    reload, which would be confusing and would make Stage 3's whole
    point invisible.

    `{session_id}` here is a "path parameter" - part of the URL itself,
    not a query string or request body. FastAPI matches the `{session_id}`
    placeholder in the route's path to this function's `session_id`
    argument automatically, based on the matching parameter name. E.g. a
    request to /api/history/abc-123 calls this function with
    session_id="abc-123".

    This is a GET request (not POST) because it only READS data - it
    doesn't create or change anything server-side. That distinction
    (GET = read, POST = write/create) is a core HTTP convention, not
    just a FastAPI one.
    """
    history = get_conversation_history(session_id)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT max(id) AS id FROM quotes WHERE chat_session_id = %s AND user_id IS NULL",
            (session_id,),
        ).fetchone()
    conn.close()
    return HistoryResponse(messages=history, unclaimed_quote_id=row["id"])


@app.post("/api/chat")
def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    """
    POST /api/chat

    This is the endpoint our frontend chat box calls. As of Stage 3, it
    remembers the conversation: every message is saved to SQLite, and
    every request to Claude includes the FULL history for that session -
    not just the newest message.

    HOW THIS FUNCTION ACTUALLY GETS CALLED, STEP BY STEP:
      1. Frontend JS runs:
             fetch("/api/chat", { method: "POST", body: JSON.stringify(...) })
         including both the new message AND this browser's session_id.
      2. The browser sends a real HTTP POST request over the network to
         our server.
      3. Uvicorn accepts the raw HTTP request and hands it to FastAPI.
      4. FastAPI reads the JSON body and builds a `ChatRequest` object
         from it (Pydantic validation happens automatically here).
      5. We save the user's new message to SQLite (add_message).
      6. We load the ENTIRE conversation for this session_id back out of
         SQLite (get_conversation_history) - which now includes the
         message we just saved, in the right order.
      7. We send that whole history to Claude (get_ai_reply) - this is
         ANOTHER HTTP request, from OUR backend out to Anthropic's API.
      8. We save Claude's reply to SQLite too, under the same
         session_id, so the NEXT request's history will include it.
      9. Whatever `ChatResponse` we return gets serialized to JSON and
         sent to the browser.

    Every message from here on makes the conversation one step longer -
    both in the database, and in what gets sent to Claude next time.
    """
    # Step 1: save the user's message BEFORE calling the AI. This matters
    # for ordering - by the time we read the history back in step 2, this
    # new message needs to already be the last row for this session_id.
    add_message(request.session_id, "user", request.message)

    # Step 2: load the full conversation - every message ever sent under
    # this session_id, oldest first, including the one we just saved.
    history = get_conversation_history(request.session_id)

    try:
        reply_text, quote = get_ai_reply(history)
    except RuntimeError as error:
        # HTTPException is FastAPI's way of returning a proper HTTP error
        # response (a status code + a JSON error body) instead of the
        # function just returning normally. Raising it here immediately
        # stops execution and sends the error response - the frontend's
        # `fetch()` call will see `response.ok === false`, and the
        # `if (!response.ok)` check already written in script.js will
        # catch it and show a friendly error bubble.
        #
        # 502 Bad Gateway is the conventional HTTP status for "we tried to
        # reach an upstream/external service and IT failed" - distinct
        # from 400 (the user's own request was malformed) or 500 (we have
        # a bug in our own code).
        #
        # Note: we don't save anything to the "assistant" side of the
        # conversation if this fails - there's no reply to remember, and
        # the user's message (already saved above) stays in history so
        # they can just try again without repeating themselves.
        raise HTTPException(status_code=502, detail=str(error))

    # Step 3: save the assistant's reply too, so it's part of the history
    # the NEXT call to get_conversation_history() will return.
    add_message(request.session_id, "assistant", reply_text)

    quote_id = project_id = None
    if quote is not None:
        # Remember the quote. If the visitor is already a signed-in
        # customer it becomes a dashboard project immediately; otherwise
        # it waits (keyed by this chat's session_id) until they sign up
        # or in, at which point app/auth.py claims it.
        user = get_user_from_request(http_request)
        owner_id = user["id"] if user and user["role"] == "customer" else None
        with get_connection() as conn:
            quote_id = save_quote(conn, request.session_id, quote, owner_id)
            if owner_id is not None:
                project_id = conn.execute(
                    "SELECT id FROM projects WHERE quote_id = %s", (quote_id,)
                ).fetchone()["id"]
            conn.commit()
        conn.close()

    return ChatResponse(reply=reply_text, quote_id=quote_id, project_id=project_id)


sync_admin_account()
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(projects_router)


@app.get("/admin", include_in_schema=False)
def serve_admin() -> FileResponse:
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/dashboard", include_in_schema=False)
def serve_dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


# --- Static file mounting ---------------------------------------------------
# `app.mount(...)` hands off an entire URL prefix to another piece of code.
# Here, any request to /static/<anything> (e.g. /static/style.css) is
# served directly from the matching file on disk in our STATIC_DIR - we
# don't write a route for every single asset by hand.
#
# We mount this AFTER defining our own routes above on purpose: FastAPI
# checks routes in the order they were registered, and we want "/" and
# "/api/..." to be handled by our own functions first.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
