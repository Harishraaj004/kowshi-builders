# app/__init__.py
# ================
# An empty file, but its PRESENCE matters: it's what tells Python that the
# "app" folder is a "package" - a folder of Python modules that can be
# imported as a unit (e.g. `from app.main import app`, or the command
# `uvicorn app.main:app` we use to start the server).
#
# Without this file, Python (in most setups) would just see "app" as a
# random folder, not something importable as "app.main".
