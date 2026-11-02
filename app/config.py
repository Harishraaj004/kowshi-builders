"""
app/config.py
==============
Centralizes configuration and secrets loading.

WHY A SEPARATE CONFIG FILE?
-----------------------------
As soon as we depend on something environment-specific (an API key, in
this case), we need a place to load it from that:
  1. Keeps the secret OUT of our source code, so it never gets committed
     to Git - different people/machines/environments can each use their
     own key without editing code.
  2. Gives every other file in the project ONE place to import settings
     from, instead of each file reading os.environ directly and
     duplicating "did the user forget to set this?" checks.

HOW SECRETS FLOW IN THIS PROJECT:
------------------------------------
    .env file (git-ignored, lives only on your machine)
        |
        | python-dotenv reads it and loads each KEY=value line into
        | the process's environment variables
        v
    os.environ / os.getenv()
        |
        | we read it once here, at import time
        v
    ANTHROPIC_API_KEY constant, imported by app/llm.py
"""

import os
from dotenv import load_dotenv

# load_dotenv() looks for a file named ".env" in the current directory (or
# a parent directory) and loads each "KEY=value" line into the process's
# environment variables - as if you'd typed `export KEY=value` in your
# terminal before running the app. It's a no-op (does nothing, raises no
# error) if the file doesn't exist, which matters for production setups
# where secrets get injected a different way (e.g. by the hosting
# platform) instead of a .env file.
load_dotenv()

# os.getenv(name) reads an environment variable, returning None if it's
# not set (unlike os.environ[name], which would raise an error). We read
# it once here, at MODULE IMPORT TIME - this line runs exactly once, the
# first time anything does `import app.config`, no matter how many other
# files import it afterward.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# We fail LOUDLY and IMMEDIATELY if the key is missing, rather than
# waiting for the first chat request to mysteriously fail. This is a
# deliberate "fail fast" pattern: a missing secret is a setup problem, and
# setup problems should surface at startup, not three steps into a demo.
if not ANTHROPIC_API_KEY:
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and "
        "paste in your real Anthropic API key (create one at "
        "https://console.anthropic.com/settings/keys)."
    )

# The model we're calling. Centralizing it here (instead of hardcoding it
# inside app/llm.py) means swapping models later is a one-line change.
#
# Pricing (per 1M tokens, input / output, at time of writing) if you want
# to swap for a cheaper option while testing:
#   claude-opus-5    - $5.00  / $25.00  (most capable - our default)
#   claude-sonnet-5  - $3.00  / $15.00  (strong, cheaper, great default
#                       for a production app once you're past learning)
#   claude-haiku-4-5 - $1.00  / $5.00   (fastest/cheapest - fine for
#                       simple, high-volume tasks)
ANTHROPIC_MODEL_ID = "claude-opus-5"

# --- Database connection ---------------------------------------------------
# A "connection string" (also called a DSN - Data Source Name) packs
# everything needed to reach a Postgres server into one URL:
#   postgresql://<user>:<password>@<host>:<port>/<database name>
# This replaces SQLite's setup entirely - there's no local .db FILE
# anymore; app/database.py now connects over the network (even though,
# here, that network happens to be your own machine - "localhost") to a
# separate Postgres SERVER PROCESS that has to already be running.
#
# We provide a default matching this project's local dev database, but
# still read from the environment first - so a teammate, or a real
# deployment, can point at a completely different Postgres server just by
# setting DATABASE_URL, with zero code changes.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:root@localhost:5433/kowshi_builders",
)

# --- Accounts & dashboard --------------------------------------------------
# Google Sign-In: the OAuth "Web application" client ID from
# https://console.cloud.google.com/apis/credentials (authorised JavaScript
# origin must include the URL the site is served from). Optional - if it's
# unset the Google button is simply hidden and email sign-in still works.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

# Comma-separated emails that are promoted to the "admin" role the moment
# they sign up / sign in. This is how the FIRST admin gets created (every
# other signup is a plain customer); that admin can then promote engineers
# and other admins from the dashboard.
ADMIN_EMAILS = {
    email.strip().lower()
    for email in os.getenv("ADMIN_EMAILS", "").split(",")
    if email.strip()
}

# The admin console login (/admin). On every server start the account with
# this email is created (or updated) with this password and the admin role,
# so changing the values here and restarting is how you rotate them. Leave
# either empty to skip. Keep the real values in .env only.
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

# Set to "true" when serving over HTTPS so the session cookie is only ever
# sent over encrypted connections. Left off by default because plain
# http://localhost would otherwise never receive the cookie.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "14"))

# Where customer-uploaded approval documents are stored on disk.
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")

# --- Email (signup OTP) -----------------------------------------------------
# SMTP server used to send verification codes. Leave SMTP_HOST empty in local
# development and the code is printed to the server console instead of being
# emailed (never do that in production - anyone could sign up as anyone).
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "no-reply@kowshibuilders.local")
