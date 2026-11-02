# Kowshi Builders - Chat Agent (Learning Project)

This is a from-scratch, stage-by-stage learning project. The end goal is a
website with an AI chat agent for a construction business, but we're
building every layer ourselves, in order, so nothing is a black box.

See the project plan / full staged roadmap in the chat history with
Claude - this README only documents what's actually built so far.

## Stage 1 - plumbing, no AI

**Goal:** understand, end to end, how a browser talks to a Python backend
over HTTP/JSON - before any LLM, database, or framework magic gets added.

```
Browser (HTML/CSS/JS)  --fetch()-->  FastAPI  -->  Python function  -->  JSON response
```

### What's here

```
app/
  __init__.py     # marks "app" as an importable Python package
  main.py         # the FastAPI backend: routes, request/response shapes
static/
  index.html      # page structure
  style.css       # page appearance
  script.js       # page behaviour (talks to the backend via fetch)
requirements.txt  # third-party Python packages this project needs
.gitignore        # files Git should never track (venv, caches, .env)
```

There is no database, no LLM, and no persistence yet. The `/api/chat`
route just echoes back whatever you type, prefixed with "You said:" - the
whole point of Stage 1 is to see the real request/response cycle working,
with nothing hidden behind it.

### Running it

```bash
# 1. Activate the virtual environment (created once with: python -m venv .venv)
.venv\Scripts\activate

# 2. Install dependencies (only needed once, or after requirements.txt changes)
pip install -r requirements.txt

# 3. Start the server. --reload restarts it automatically whenever you
#    save a change to app/main.py during development.
uvicorn app.main:app --reload --port 8000
```

Then open:
- `http://localhost:8000/` - the chat UI
- `http://localhost:8000/api/health` - a plain JSON health check
- `http://localhost:8000/docs` - FastAPI's auto-generated interactive API docs

### Concepts covered in this stage

- Python virtual environments (`.venv`) and why we isolate project
  dependencies per-project instead of installing everything globally
- `requirements.txt` as a reproducible dependency list
- HTTP requests/responses, and the specific methods GET vs POST
- JSON as the data format frontend and backend agree on
- FastAPI routes, and how Pydantic (`BaseModel`) validates request/response
  shapes automatically
- Serving static files (HTML/CSS/JS) from a Python backend
- The DOM, event listeners, and `fetch()` in plain JavaScript
- Why business logic and secrets belong on the backend, never the frontend
- `.gitignore` and why generated/machine-specific files shouldn't be
  committed to version control

### Not yet covered (later stages)

- Calling an LLM API (Stage 2)
- Conversation memory across messages (Stage 3)
- Deterministic construction calculators as callable "tools" (Stage 4)
- Retrieval-augmented generation over our own documents (Stage 5)
- LangGraph-based agent orchestration (Stage 6)
- A production frontend framework, auth, and deployment (Stage 7)
