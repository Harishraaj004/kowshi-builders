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
from fastapi import FastAPI

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


# --- App setup ---------------------------------------------------------------

# This single line creates our actual application object. Every route we
# define below "attaches" itself to this one `app` object via decorators.
app = FastAPI(
    title="Kowshi Builders - Learning Project",
    description="Stage 1: plain FastAPI backend + static HTML/CSS/JS frontend. No AI yet.",
    version="0.1.0",
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
#     { "message": "hello" }
#
# Declaring this class tells FastAPI: "expect a JSON object with exactly
# one field, `message`, which must be a string." If the frontend ever
# sends something that doesn't match (missing field, wrong type, junk
# data), FastAPI automatically rejects it with a clear 422 error - we
# never wrote a single line of that validation ourselves.
class ChatRequest(BaseModel):
    message: str


# Likewise, our reply will be JSON shaped like:
#     { "reply": "You said: hello" }
#
# Declaring the response shape (in addition to the request shape) keeps
# our API's "contract" explicit, and it shows up automatically in the
# /docs page mentioned above.
class ChatResponse(BaseModel):
    reply: str


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


@app.post("/api/chat")
def chat(request: ChatRequest) -> ChatResponse:
    """
    POST /api/chat

    This is the endpoint our frontend chat box calls. There is
    deliberately NO AI here yet - Stage 1 is about seeing the full
    request/response cycle clearly, before anything is hidden behind an
    LLM call.

    HOW THIS FUNCTION ACTUALLY GETS CALLED, STEP BY STEP:
      1. Frontend JS runs:
             fetch("/api/chat", { method: "POST", body: JSON.stringify(...) })
      2. The browser sends a real HTTP POST request over the network to
         our server.
      3. Uvicorn accepts the raw HTTP request and hands it to FastAPI.
      4. FastAPI sees the path/method matches this route, reads the JSON
         request body, and tries to build a `ChatRequest` object from it
         (this is where Pydantic validation happens automatically).
      5. If validation succeeds, THIS function runs - `request` arrives
         already parsed into a real Python object, so we just read
         `request.message` like a normal attribute. No manual JSON
         parsing, no manual error-checking for missing fields.
      6. Whatever `ChatResponse` object we return gets serialized back to
         JSON automatically and sent to the browser.

    For now we just echo the message back with a canned prefix, purely to
    prove the full loop (browser -> FastAPI -> Python -> browser) works
    end to end. Stage 2 is where a real LLM call replaces this line.
    """
    canned_reply = f"You said: {request.message}"
    return ChatResponse(reply=canned_reply)


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
