#!/usr/bin/env python3
"""Build the MCPB bundle for evc-team-relay-mcp.

`packaging/mcpb/manifest.json` deliberately carries no `tools` array — the
per-tool schemas are generated here from the live `relay_mcp.mcp.list_tools()`
instead of being hand-copied, so they can never drift from the actual server.

This does NOT shell out to `mcpb pack`/`mcpb validate` (the official
@anthropic-ai/mcpb CLI): that validator rejects an `inputSchema` key on a
tool entry (arcadeai-labs/smithery-cli#787), but Smithery's own catalog
ingestion requires one on every tool to show parameters without running the
server. The bundle is a plain zip (manifest.json + relay_mcp.py at the
root) built directly with the stdlib, which both consumers accept.

manifest.json's own "version" and mcp_config.args pin are deliberately the
placeholder "0.0.0-unbuilt" — not the last-shipped version — so a build that
skips the version argument cannot silently tag a bundle with a real-looking
but stale version. Default here is server.json's version (the file every
release already bumps), not a second copy kept in sync by hand.

Not wired into any CI job: this is deliberately a manual, run-when-needed
step (whoever republishes to Smithery runs it, then uploads the .mcpb by
hand — Smithery publish itself stays a manual, lead-run action, not an
automated re-deploy). If a Smithery/registry publish step is ever automated,
call this script from that job rather than duplicating its logic there.

Usage:
    python3 packaging/mcpb/build_mcpb.py [version] [out_dir]

    version  Defaults to server.json's version at the repo root.
    out_dir  Defaults to ./dist relative to the repo root.
"""

from __future__ import annotations

import asyncio
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import relay_mcp  # noqa: E402  (needs ROOT on sys.path first)


def _tool_entries() -> list[dict]:
    """Introspect the live server for each tool's name/description/schema/annotations."""

    async def _list():
        return await relay_mcp.mcp.list_tools()

    tools = asyncio.run(_list())
    entries = []
    for t in tools:
        entry: dict = {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.inputSchema,
        }
        if t.outputSchema:
            entry["outputSchema"] = t.outputSchema
        if t.annotations:
            entry["annotations"] = t.annotations.model_dump(exclude_none=True)
        entries.append(entry)
    return entries


def _default_version() -> str:
    """Read the version to build from server.json — the file every release
    already bumps — instead of keeping a second copy in this package."""
    server_json = json.loads((ROOT / "server.json").read_text())
    return server_json["version"]


def build(version: str | None, out_dir: Path) -> Path:
    manifest_path = Path(__file__).with_name("manifest.json")
    manifest = json.loads(manifest_path.read_text())

    version = version or _default_version()
    manifest["version"] = version
    manifest["server"]["mcp_config"]["args"] = [f"evc-team-relay-mcp=={version}"]
    manifest["tools"] = _tool_entries()

    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = out_dir / f"evc-team-relay-mcp-{manifest['version']}.mcpb"

    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        zf.write(ROOT / "relay_mcp.py", "relay_mcp.py")

    return bundle_path


if __name__ == "__main__":
    cli_version = sys.argv[1] if len(sys.argv) > 1 else None
    cli_out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "dist"
    result_path = build(cli_version, cli_out_dir)
    print(f"built {result_path} ({result_path.stat().st_size} bytes)")
