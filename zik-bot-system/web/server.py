from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import asyncpg
import pytz
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse

from config import Config
from database import now_baku


app = FastAPI(title="ZIK Bot Web Server")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _connect() -> asyncpg.Connection:
    if not Config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return await asyncpg.connect(Config.DATABASE_URL)


@app.get("/")
async def root():
    return {"status": "ok", "service": "zik-web", "time": now_baku().isoformat()}


@app.get("/health")
async def health():
    return {"status": "healthy", "time": now_baku().isoformat()}


@app.get("/zik/{slug}")
async def zik_redirect(slug: str, t: Optional[str] = None, token: Optional[str] = None):
    """Redirector endpoint.

    The bot sends users to the per-account custom URL like:
        https://<your-domain>/zik/<slug>?t=<uuid>

    We then redirect to the real ZIK login URL, preserving the token in the query.
    The Chrome extension reads this token and asks /api/session/<token> for credentials.
    """

    session_token = (t or token or "").strip()
    target = Config.ZIK_LOGIN_URL
    if session_token:
        # Keep token under a stable name for the extension
        sep = "&" if "?" in target else "?"
        target = f"{target}{sep}zik_token={session_token}"
    return RedirectResponse(url=target, status_code=302)


@app.get("/api/session/{token}")
async def api_get_session(token: str):
    """Return credentials for an active session token."""
    conn = await _connect()
    try:
        row = await conn.fetchrow(
            """
            SELECT s.state, s.session_end_at, s.user_id, s.account_id,
                   a.email, a.password, a.account_name
            FROM sessions s
            JOIN zik_accounts a ON a.account_id=s.account_id
            WHERE s.token=$1
            LIMIT 1
            """,
            token,
        )
        if not row:
            raise HTTPException(status_code=404, detail="session_not_found")
        if row["state"] != "active":
            raise HTTPException(status_code=403, detail="session_not_active")
        end_at = row["session_end_at"]
        now = now_baku()
        remaining = int((end_at - now).total_seconds()) if end_at else 0
        if remaining < 0:
            remaining = 0
        return {
            "ok": True,
            "account_name": row["account_name"],
            "email": row["email"],
            "password": row["password"],
            "session_end_at": end_at.isoformat() if end_at else None,
            "server_time": now.isoformat(),
            "remaining_seconds": remaining,
        }
    finally:
        await conn.close()


@app.post("/api/heartbeat/{token}")
async def api_heartbeat(token: str):
    """Tab heartbeat from the extension."""
    conn = await _connect()
    try:
        await conn.execute(
            "UPDATE sessions SET last_heartbeat_at=NOW() WHERE token=$1 AND state='active'",
            token,
        )
        return {"ok": True, "time": now_baku().isoformat()}
    finally:
        await conn.close()


@app.get("/api/time")
async def api_time():
    return {"time": now_baku().isoformat()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
