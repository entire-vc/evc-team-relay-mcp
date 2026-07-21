"""EVC Team Relay MCP Server.

Provides MCP tools for reading and writing Obsidian vault documents
via the EVC Team Relay control plane REST API.

Supports stdio (local) and streamable-http (remote) transports.

Usage:
    uv run relay_mcp.py                    # stdio (default)
    uv run relay_mcp.py --transport http   # HTTP server on port 8888
    uv run relay_mcp.py --port 9000        # HTTP on custom port
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ── Server setup ─────────────────────────────────────────────
mcp = FastMCP(
    "evc-relay",
    instructions=(
        "EVC Team Relay tools for reading and writing Obsidian vault documents. "
        "Start by calling `authenticate` to get a token, then use `list_shares` "
        "to discover available shares. For folder shares, use `read_file`, "
        "`list_files` and `tr_search` with file paths (agent-key mode also "
        "supports writing via `upsert_file`). DOC-share content, per-file "
        "delete, and JWT-mode writes have no backend route yet — those tools "
        "raise a clear error rather than silently failing; see TR-05."
    ),
)

# ── Internal state ───────────────────────────────────────────
_token: str | None = None
_token_expires: float = 0
_refresh_token: str | None = None


def _get_base_url() -> str:
    url = os.environ.get("RELAY_CP_URL", "")
    if not url:
        raise ValueError("RELAY_CP_URL environment variable not set")
    return url.rstrip("/")


def _parse_agent_keys() -> dict[str, str]:
    """Parse RELAY_AGENT_KEYS=share1:key1,share2:key2 into {share_ref: key}.

    Reads fresh from env on each call (safe across monkeypatch in tests).
    In production the env never changes, so cost is negligible.
    """
    raw = os.environ.get("RELAY_AGENT_KEYS", "").strip()
    if not raw:
        return {}
    result: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        share_ref, _, key = entry.partition(":")
        share_ref = share_ref.strip()
        key = key.strip()
        if share_ref and key:
            result[share_ref] = key
    return result


def _get_agent_key() -> str | None:
    """Return RELAY_AGENT_KEY global single key, if set."""
    return os.environ.get("RELAY_AGENT_KEY", "").strip() or None


def _get_key_for_share(share_id: str) -> str | None:
    """Return agent key for a specific share.

    Lookup order: per-share RELAY_AGENT_KEYS map → global RELAY_AGENT_KEY fallback.
    """
    keys = _parse_agent_keys()
    if share_id in keys:
        return keys[share_id]
    return _get_agent_key()


def _is_agent_key_mode() -> bool:
    """True if any agent key is configured (RELAY_AGENT_KEYS or RELAY_AGENT_KEY)."""
    return bool(_parse_agent_keys() or _get_agent_key())


def _agent_headers(key: str) -> dict[str, str]:
    return {"X-Agent-Key": key}


def _resolve_share_kind(share_id: str, agent_key: str) -> str:
    """Return 'folder' or 'doc' for the given share using agent-key auth.

    Falls back to 'folder' if the endpoint is unavailable — upsert_file
    is a folder-share tool, so this is the safe default.
    """
    try:
        with _get_client() as client:
            r = client.get(
                f"{_get_base_url()}/v1/web/shares/{share_id}",
                headers=_agent_headers(agent_key),
            )
            if r.status_code == 200:
                return r.json().get("kind", "folder")
    except Exception:
        pass
    return "folder"


def _get_client() -> httpx.Client:
    # Disable keep-alive: Caddy sends GOAWAY on idle connections,
    # httpx tries to reuse the stale socket and hangs.
    limits = httpx.Limits(max_keepalive_connections=0)
    return httpx.Client(timeout=30.0, limits=limits)


def _ensure_token() -> str:
    """Return a valid JWT token, refreshing if needed."""
    global _token, _token_expires, _refresh_token

    if _token and time.time() < _token_expires - 60:
        return _token

    # Try refresh first
    if _refresh_token:
        try:
            with _get_client() as client:
                r = client.post(
                    f"{_get_base_url()}/v1/auth/refresh",
                    json={"refresh_token": _refresh_token},
                )
                if r.status_code == 200:
                    data = r.json()
                    _token = data["access_token"]
                    _refresh_token = data.get("refresh_token", _refresh_token)
                    _token_expires = time.time() + data.get("expires_in", 3600)
                    return _token
        except Exception:
            pass

    # Full login
    email = os.environ.get("RELAY_EMAIL", "")
    password = os.environ.get("RELAY_PASSWORD", "")
    if not email or not password:
        raise ValueError("RELAY_EMAIL and RELAY_PASSWORD must be set")

    with _get_client() as client:
        r = client.post(
            f"{_get_base_url()}/v1/auth/login",
            json={"email": email, "password": password},
        )
        r.raise_for_status()
        data = r.json()

    _token = data["access_token"]
    _refresh_token = data.get("refresh_token")
    _token_expires = time.time() + data.get("expires_in", 3600)
    return _token


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_ensure_token()}"}


def _jwt_list_files(share_id: str) -> dict[str, dict]:
    """Fetch the CAS sync-artifact file index for a folder share (email/password mode).

    Uses GET /v1/shares/{share_id}/files-index (Bearer JWT) — the real, working
    counterpart to the agent-key /v1/web/shares/{id}/files-index endpoint. Only
    items uploaded via sync-upload (source=sync-artifact) are returned; this is
    a server-side filter on the shared endpoint, not a client limitation.

    Returns {path: {type, size, modified_at, sha256}}.
    """
    with _get_client() as client:
        r = client.get(
            f"{_get_base_url()}/v1/shares/{share_id}/files-index",
            headers=_headers(),
        )
        r.raise_for_status()
        items = r.json()
    return {
        item["path"]: {
            "type": item.get("type", "doc"),
            "size": item.get("size"),
            "modified_at": item.get("updated_at"),
            "sha256": item.get("sha256"),
        }
        for item in items
    }


_NO_DOCUMENTS_API = (
    "{tool} is not available: the control-plane has no REST route for this "
    "operation. relay_mcp.py was written against a /v1/documents/* API that "
    "was never implemented server-side (confirmed absent across the full git "
    "history of evc-team-relay-cp) — only agent-key CAS sync "
    "(list_files/read_file/upsert_file for FOLDER shares, agent-key mode) and "
    "JWT read of that same CAS index (list_files/tr_search/read_file, "
    "email/password mode) are real. DOC-share live content and any per-file "
    "delete have no backend route in either auth mode; a JWT-mode folder-share "
    "write has no route either. See Mesh task TR-05 (#0cdd5328) follow-up."
)


# ── MCP Tools ────────────────────────────────────────────────


@mcp.tool()
def authenticate() -> str:
    """Authenticate with the Relay Control Plane.

    In agent-key mode (RELAY_AGENT_KEY is set): no login is needed —
    each request carries X-Agent-Key directly.

    In email/password mode: uses RELAY_EMAIL and RELAY_PASSWORD env vars.
    The token is managed internally; subsequent tool calls use it automatically.
    """
    if _is_agent_key_mode():
        multi = _parse_agent_keys()
        if multi:
            shares_desc = ", ".join(multi.keys())
            suffix = " + global fallback key" if _get_agent_key() else ""
            return (
                f"Agent key mode active — {len(multi)} share-specific keys "
                f"({shares_desc}){suffix}. Call list_shares to see accessible shares."
            )
        return "Agent key mode active — no email/password authentication required."
    token = _ensure_token()
    return f"Authenticated successfully. Token length: {len(token)}"


@mcp.tool()
def list_shares(kind: str = "", owned_only: bool = False) -> str:
    """List all accessible shares.

    In multi-key mode (RELAY_AGENT_KEYS set): returns metadata for every share
    that has a configured key, fetched via per-share agent-key auth.

    In single-key mode (RELAY_AGENT_KEY only): returns an empty list — the
    single key is tied to one share but its identity is unknown; call list_files
    or tr_search directly with the known share_id.

    In email/password mode: returns all shares the user has access to.

    Args:
        kind: Filter by share type — "doc" or "folder". Empty for all.
        owned_only: If true, only return shares owned by the user (email/password mode only).

    Returns:
        JSON array of shares with id, kind, path, visibility, user_role.
    """
    import json

    multi_keys = _parse_agent_keys()

    if multi_keys:
        shares: list[Any] = []
        for share_ref, key in multi_keys.items():
            try:
                with _get_client() as client:
                    r = client.get(
                        f"{_get_base_url()}/v1/web/shares/{share_ref}",
                        headers=_agent_headers(key),
                    )
                    if r.status_code == 200:
                        data = r.json()
                        if not kind or data.get("kind") == kind:
                            shares.append(data)
            except Exception:
                pass
        return json.dumps(shares)

    if _get_agent_key():
        return json.dumps([])

    params: dict[str, Any] = {}
    if kind:
        params["kind"] = kind
    if owned_only:
        params["owned_only"] = "true"

    with _get_client() as client:
        r = client.get(
            f"{_get_base_url()}/v1/shares",
            headers=_headers(),
            params=params,
        )
        r.raise_for_status()
    return r.text


@mcp.tool()
def list_files(share_id: str) -> str:
    """List files in a folder share.

    In agent-key mode (RELAY_AGENT_KEYS or RELAY_AGENT_KEY is set): uses the
    agent-key endpoint; share_id may be a UUID or web slug.

    In email/password mode: share_id must be a UUID.

    Args:
        share_id: UUID or web slug of the folder share.

    Returns:
        JSON with share_id and files map (path -> metadata).
    """
    import json

    agent_key = _get_key_for_share(share_id)
    if agent_key:
        with _get_client() as client:
            r = client.get(
                f"{_get_base_url()}/v1/web/shares/{share_id}/files-index",
                headers=_agent_headers(agent_key),
            )
            r.raise_for_status()
        return r.text

    files = _jwt_list_files(share_id)
    return json.dumps({"share_id": share_id, "files": files})


@mcp.tool()
def tr_search(share_id: str, query: str, limit: int = 20) -> str:
    """Search TR docs by path/name within a folder share.

    In agent-key mode (RELAY_AGENT_KEY is set): share_id may be UUID or web slug.
    In email/password mode: share_id must be a UUID.

    Args:
        share_id: UUID or web slug of the folder share.
        query: Search string matched case-insensitively against file paths.
        limit: Max results to return (default 20).

    Returns:
        JSON list of matching files:
        [{"id": doc_id_or_null, "title": filename_without_ext, "path": full_path,
          "relay_url": "relay://<slug>/<path>", "updated_at": null}]
    """
    import json
    from pathlib import Path

    agent_key = _get_key_for_share(share_id)

    if agent_key:
        with _get_client() as client:
            r = client.get(
                f"{_get_base_url()}/v1/web/shares/{share_id}/files-index",
                headers=_agent_headers(agent_key),
            )
            r.raise_for_status()
            files_data = r.json()

        files = files_data.get("files", {})
        q = query.lower()
        matches = [
            {
                "id": None,
                "title": Path(path).stem,
                "path": path,
                "relay_url": f"relay://{share_id}/{path}",
                "updated_at": meta.get("modified_at"),
            }
            for path, meta in sorted(files.items())
            if q in path.lower()
        ]
        return json.dumps(matches[:limit])

    # Email/password mode
    files = _jwt_list_files(share_id)

    # Resolve share slug for relay:// URL; falls back to UUID on error
    slug = share_id
    try:
        with _get_client() as client:
            rs = client.get(f"{_get_base_url()}/v1/shares", headers=_headers())
            if rs.status_code == 200:
                for s in rs.json():
                    if s.get("id") == share_id and s.get("slug"):
                        slug = s["slug"]
                        break
    except Exception:
        pass

    q = query.lower()
    matches = [
        {
            "id": None,
            "title": Path(path).stem,
            "path": path,
            "relay_url": f"relay://{slug}/{path}",
            "updated_at": meta.get("modified_at"),
        }
        for path, meta in sorted(files.items())
        if q in path.lower()
    ]
    return json.dumps(matches[:limit])


@mcp.tool()
def read_file(share_id: str, file_path: str) -> str:
    """Read a file from a folder share by its path.

    In agent-key mode (RELAY_AGENT_KEY is set): fetches via the agent-key
    download endpoint; share_id may be a UUID or web slug.

    In email/password mode: fetches via the same CAS download endpoint used by
    agent-key mode, over Bearer JWT instead of X-Agent-Key; share_id must be a UUID.

    Args:
        share_id: UUID or web slug of the folder share.
        file_path: File path within the folder (e.g. "Marketing/plan.md").

    Returns:
        JSON with content, format, and path.
    """
    import json

    agent_key = _get_key_for_share(share_id)
    if agent_key:
        with _get_client() as client:
            r = client.get(
                f"{_get_base_url()}/v1/web/shares/{share_id}/download",
                headers=_agent_headers(agent_key),
                params={"path": file_path},
            )
            if r.status_code == 404:
                return json.dumps({"error": f"File not found: {file_path}"})
            r.raise_for_status()
        content_type = r.headers.get("content-type", "text/plain")
        fmt = "markdown" if "text/" in content_type else "binary"
        return json.dumps({"path": file_path, "content": r.text, "format": fmt})

    # Email/password mode
    with _get_client() as client:
        r = client.get(
            f"{_get_base_url()}/v1/shares/{share_id}/download",
            headers=_headers(),
            params={"path": file_path},
        )
        if r.status_code == 404:
            return json.dumps({"error": f"File not found: {file_path}"})
        r.raise_for_status()
    content_type = r.headers.get("content-type", "text/plain")
    fmt = "markdown" if "text/" in content_type else "binary"
    return json.dumps({"path": file_path, "content": r.text, "format": fmt})


@mcp.tool()
def read_document(share_id: str, doc_id: str = "", key: str = "contents") -> str:
    """NOT CURRENTLY AVAILABLE — always raises.

    The control-plane has no REST route for reading a document's live content
    by ID for either DOC-kind shares or a folder-share file's doc_id (that
    concept doesn't exist in the current CAS-based folder sync model). Use
    read_file for folder shares in agent-key mode. See TR-05 follow-up.

    Args:
        share_id: UUID of the share (for ACL check).
        doc_id: Document UUID. Defaults to share_id for doc shares.
        key: Yjs shared type key. Default "contents".
    """
    if not doc_id:
        doc_id = share_id
    raise ValueError(_NO_DOCUMENTS_API.format(tool="read_document"))


@mcp.tool()
def upsert_file(share_id: str, file_path: str, content: str) -> str:
    """Create or update a file in a folder share.

    Two authentication modes:

    **Agent key mode** (RELAY_AGENT_KEY is set):
    - share_id may be the share UUID or web slug (e.g. "research-vault")
    - Folder shares use /sync-upload → file enters the CRDT sync store and
      appears in subscribers' local Obsidian vaults on the next sync cycle
    - Doc shares fall back to /upload (web-publish only)
    - list_files, read_file, and tr_search also work with the same agent key

    **Email/password mode** — NOT CURRENTLY AVAILABLE, always raises.
    The control-plane has no write route reachable by JWT for an arbitrary
    (non-web-published) folder share. Use agent-key mode instead. See TR-05.

    Args:
        share_id: Share UUID (email/password mode) or web slug (agent key mode).
        file_path: File path within the share (e.g. "notes/todo.md").
        content: Full text content to write.

    Returns:
        JSON with path, size/operation, and optional public_url (agent-key mode).
    """
    import json

    agent_key = _get_key_for_share(share_id)
    if agent_key:
        # Route to sync-upload for folder shares (writes into CRDT sync store →
        # subscribers' local vaults); fall back to upload for doc shares.
        share_kind = _resolve_share_kind(share_id, agent_key)
        upload_path = "sync-upload" if share_kind == "folder" else "upload"
        with _get_client() as client:
            r = client.post(
                f"{_get_base_url()}/v1/web/shares/{share_id}/{upload_path}",
                headers={
                    "X-Agent-Key": agent_key,
                    "Content-Type": "text/plain; charset=utf-8",
                },
                params={"path": file_path},
                content=content.encode("utf-8"),
            )
            r.raise_for_status()
            result = r.json()
        result["operation"] = "uploaded"
        return json.dumps(result)

    # Email/password mode: no backend write route exists (see _NO_DOCUMENTS_API).
    # Note: even /v1/web/shares/{slug}/files (JWT-capable) is not a safe substitute —
    # it writes items without source=sync-artifact, which the files-index read path
    # (both agent-key and JWT) filters out, so the write would silently vanish from
    # every subsequent list_files/read_file call. An honest error beats that.
    raise ValueError(_NO_DOCUMENTS_API.format(tool="upsert_file (email/password mode)"))


@mcp.tool()
def write_document(
    share_id: str, doc_id: str, content: str, key: str = "contents"
) -> str:
    """NOT CURRENTLY AVAILABLE — always raises.

    The control-plane has no REST route for writing a document's live content
    by ID (doc-share content is CRDT/WebSocket-only). See TR-05 follow-up.

    Args:
        share_id: UUID of the share (for ACL check).
        doc_id: Document UUID.
        content: Full text content to write (replaces entire document).
        key: Yjs shared type key. Default "contents".
    """
    raise ValueError(_NO_DOCUMENTS_API.format(tool="write_document"))


@mcp.tool()
def delete_file(share_id: str, file_path: str) -> str:
    """NOT CURRENTLY AVAILABLE — always raises.

    The control-plane has no DELETE route for an individual folder-share file
    in ANY auth mode (agent-key or JWT) — this isn't a JWT-vs-agent-key gap,
    per-file deletion simply isn't implemented server-side yet. See TR-05.

    Args:
        share_id: UUID of the folder share.
        file_path: File path within the folder (e.g. "old-note.md").
    """
    raise ValueError(_NO_DOCUMENTS_API.format(tool="delete_file"))


# ── Entry point ──────────────────────────────────────────────

def main():
    transport = "stdio"
    port = 8888
    host = "127.0.0.1"  # localhost-only by default; use --host 0.0.0.0 behind a reverse proxy

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ("--transport", "-t"):
            transport = args[i + 1]
            i += 2
        elif args[i] in ("--port", "-p"):
            port = int(args[i + 1])
            i += 2
        elif args[i] in ("--host",):
            host = args[i + 1]
            i += 2
        else:
            i += 1

    if transport in ("http", "streamable-http"):
        mcp.settings.host = host
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
