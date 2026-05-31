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
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

# ── Server setup ─────────────────────────────────────────────
mcp = FastMCP(
    "evc-relay",
    instructions=(
        "EVC Team Relay tools for reading and writing Obsidian vault documents. "
        "Start by calling `authenticate` to get a token, then use `list_shares` "
        "to discover available shares. For folder shares, use `read_file` and "
        "`upsert_file` with file paths. For doc shares, use `read_document` "
        "with the share_id as doc_id."
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


def _get_agent_key() -> str | None:
    return os.environ.get("RELAY_AGENT_KEY", "").strip() or None


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


# ── MCP Tools ────────────────────────────────────────────────


@mcp.tool()
def authenticate() -> str:
    """Authenticate with the Relay Control Plane.

    Uses RELAY_EMAIL and RELAY_PASSWORD env vars.
    Returns a status message. The token is managed internally —
    subsequent tool calls use it automatically.
    """
    token = _ensure_token()
    return f"Authenticated successfully. Token length: {len(token)}"


@mcp.tool()
def list_shares(kind: str = "", owned_only: bool = False) -> str:
    """List all accessible shares.

    Args:
        kind: Filter by share type — "doc" or "folder". Empty for all.
        owned_only: If true, only return shares owned by the user.

    Returns:
        JSON array of shares with id, kind, path, visibility, user_role.
    """
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

    Args:
        share_id: UUID of the folder share.

    Returns:
        JSON with doc_id and files map (path -> {doc_id, type}).
    """
    with _get_client() as client:
        r = client.get(
            f"{_get_base_url()}/v1/documents/{share_id}/files",
            headers=_headers(),
            params={"share_id": share_id},
        )
        r.raise_for_status()
    return r.text


@mcp.tool()
def tr_search(share_id: str, query: str, limit: int = 20) -> str:
    """Search published TR docs by path/name within a folder share.

    Args:
        share_id: UUID of the folder share.
        query: Search string matched case-insensitively against file paths.
        limit: Max results to return (default 20).

    Returns:
        JSON list of matching files:
        [{"id": doc_id, "title": filename_without_ext, "path": full_path,
          "relay_url": "relay://<slug>/<path>", "updated_at": null}]
    """
    import json
    from pathlib import Path

    with _get_client() as client:
        r = client.get(
            f"{_get_base_url()}/v1/documents/{share_id}/files",
            headers=_headers(),
            params={"share_id": share_id},
        )
        r.raise_for_status()
        files_data = r.json()

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

    files = files_data.get("files", {})
    q = query.lower()
    matches = [
        {
            "id": (meta.get("id") or meta.get("doc_id")),
            "title": Path(path).stem,
            "path": path,
            "relay_url": f"relay://{slug}/{path}",
            "updated_at": None,
        }
        for path, meta in sorted(files.items())
        if q in path.lower()
    ]
    return json.dumps(matches[:limit])


@mcp.tool()
def read_file(share_id: str, file_path: str) -> str:
    """Read a file from a folder share by its path.

    Resolves path -> doc_id automatically. This is the recommended
    way to read files from folder shares.

    Args:
        share_id: UUID of the folder share.
        file_path: File path within the folder (e.g. "Marketing/plan.md").

    Returns:
        JSON with doc_id, content, format, path.
    """
    import json

    # Step 1: resolve path -> doc_id
    with _get_client() as client:
        r = client.get(
            f"{_get_base_url()}/v1/documents/{share_id}/files",
            headers=_headers(),
            params={"share_id": share_id},
        )
        r.raise_for_status()
        files_data = r.json()

    files = files_data.get("files", {})
    file_meta = files.get(file_path)
    if not file_meta:
        available = list(files.keys())[:20]
        return json.dumps(
            {"error": f"File not found: {file_path}", "available_files": available}
        )

    doc_id = file_meta.get("id") or file_meta.get("doc_id")
    if not doc_id:
        return json.dumps({"error": f"No doc_id for file: {file_path}"})

    # Step 2: read content
    with _get_client() as client:
        r = client.get(
            f"{_get_base_url()}/v1/documents/{doc_id}/content",
            headers=_headers(),
            params={"share_id": share_id, "key": "contents"},
        )
        r.raise_for_status()
        content_data = r.json()

    content_data["path"] = file_path
    return json.dumps(content_data)


@mcp.tool()
def read_document(share_id: str, doc_id: str = "", key: str = "contents") -> str:
    """Read document content by doc_id (low-level).

    For doc shares, omit doc_id — it defaults to share_id.
    For folder shares, pass the file's doc_id from list_files.
    Prefer read_file for folder shares.

    Args:
        share_id: UUID of the share (for ACL check).
        doc_id: Document UUID. Defaults to share_id for doc shares.
        key: Yjs shared type key. Default "contents".

    Returns:
        JSON with doc_id, content, format.
    """
    if not doc_id:
        doc_id = share_id

    with _get_client() as client:
        r = client.get(
            f"{_get_base_url()}/v1/documents/{doc_id}/content",
            headers=_headers(),
            params={"share_id": share_id, "key": key},
        )
        r.raise_for_status()
    return r.text


@mcp.tool()
def upsert_file(share_id: str, file_path: str, content: str) -> str:
    """Create or update a file in a folder share.

    Two authentication modes:

    **Agent key mode** (RELAY_AGENT_KEY is set):
    - share_id must be the share's web slug (e.g. "research-vault"), not a UUID
    - Uses the upload endpoint with X-Agent-Key header — no password required
    - File appears in Obsidian on the next sync cycle
    - Write-only: list_shares, list_files, read_file still require credentials

    **Email/password mode** (RELAY_EMAIL + RELAY_PASSWORD are set):
    - share_id is the share UUID
    - Syncs in real-time via CRDT
    - Automatically detects create vs update

    Args:
        share_id: Share UUID (email/password mode) or web slug (agent key mode).
        file_path: File path within the share (e.g. "notes/todo.md").
        content: Full text content to write.

    Returns:
        JSON with path, size/operation, and optional public_url.
    """
    import json

    agent_key = _get_agent_key()
    if agent_key:
        # Agent key mode: upload endpoint, X-Agent-Key auth
        with _get_client() as client:
            r = client.post(
                f"{_get_base_url()}/v1/web/shares/{share_id}/upload",
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

    # Email/password mode: CRDT path
    # Check if file exists
    with _get_client() as client:
        r = client.get(
            f"{_get_base_url()}/v1/documents/{share_id}/files",
            headers=_headers(),
            params={"share_id": share_id},
        )
        r.raise_for_status()
        files_data = r.json()

    files = files_data.get("files", {})
    file_meta = files.get(file_path)
    existing_doc_id = None
    if file_meta:
        existing_doc_id = file_meta.get("id") or file_meta.get("doc_id")

    if existing_doc_id:
        # Update existing file
        with _get_client() as client:
            r = client.put(
                f"{_get_base_url()}/v1/documents/{existing_doc_id}/content",
                headers=_headers(),
                json={"share_id": share_id, "content": content, "key": "contents"},
            )
            r.raise_for_status()
            result = r.json()
        result["path"] = file_path
        result["operation"] = "updated"
        return json.dumps(result)
    else:
        # Create new file
        with _get_client() as client:
            r = client.post(
                f"{_get_base_url()}/v1/documents/{share_id}/files",
                headers=_headers(),
                json={"share_id": share_id, "path": file_path, "content": content},
            )
            r.raise_for_status()
            result = r.json()
        result["operation"] = "created"
        return json.dumps(result)


@mcp.tool()
def write_document(
    share_id: str, doc_id: str, content: str, key: str = "contents"
) -> str:
    """Write content to a document by doc_id (doc shares only).

    For folder shares, use upsert_file instead.

    Args:
        share_id: UUID of the share (for ACL check).
        doc_id: Document UUID.
        content: Full text content to write (replaces entire document).
        key: Yjs shared type key. Default "contents".

    Returns:
        JSON with doc_id, length.
    """
    with _get_client() as client:
        r = client.put(
            f"{_get_base_url()}/v1/documents/{doc_id}/content",
            headers=_headers(),
            json={"share_id": share_id, "content": content, "key": key},
        )
        r.raise_for_status()
    return r.text


@mcp.tool()
def delete_file(share_id: str, file_path: str) -> str:
    """Delete a file from a folder share.

    Removes the file from the folder's metadata registry.
    The file disappears from Obsidian on next sync.

    Args:
        share_id: UUID of the folder share.
        file_path: File path within the folder (e.g. "old-note.md").

    Returns:
        JSON with path and status.
    """
    encoded_path = quote(file_path, safe="")
    with _get_client() as client:
        r = client.delete(
            f"{_get_base_url()}/v1/documents/{share_id}/files/{encoded_path}",
            headers=_headers(),
            params={"share_id": share_id},
        )
        r.raise_for_status()
    return r.text


# ── Entry point ──────────────────────────────────────────────

def main():
    transport = "stdio"
    port = 8888

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ("--transport", "-t"):
            transport = args[i + 1]
            i += 2
        elif args[i] in ("--port", "-p"):
            port = int(args[i + 1])
            i += 2
        else:
            i += 1

    if transport in ("http", "streamable-http"):
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
