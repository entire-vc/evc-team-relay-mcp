#!/usr/bin/env python3
"""Check the built MCPB bundle against Smithery's scoring criteria.

Verifies, per tool: every inputSchema property has a `description`, and the
tool has an `outputSchema`. Also verifies no `user_config` entry is
`required: true` (Smithery's config_is_optional criterion).

Usage:
    python3 packaging/mcpb/build_mcpb.py <version> /tmp/out
    python3 packaging/mcpb/check_quality.py /tmp/out/evc-team-relay-mcp-<version>.mcpb
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path


def check(bundle_path: Path) -> int:
    with zipfile.ZipFile(bundle_path) as zf:
        manifest = json.loads(zf.read("manifest.json"))

    tools = manifest.get("tools", [])
    with_param_docs = 0
    with_output_schema = 0
    for tool in tools:
        props = tool.get("inputSchema", {}).get("properties", {})
        if all("description" in p for p in props.values()):
            with_param_docs += 1
        if tool.get("outputSchema"):
            with_output_schema += 1

    required_config = [
        name for name, cfg in manifest.get("user_config", {}).items() if cfg.get("required")
    ]

    print(f"tools_with_parameter_docs: {with_param_docs}/{len(tools)}")
    print(f"tools_with_output_schemas: {with_output_schema}/{len(tools)}")
    print(f"config_is_optional: {'OK' if not required_config else f'FAIL ({required_config})'}")

    ok = with_param_docs == len(tools) and with_output_schema == len(tools) and not required_config
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(check(Path(sys.argv[1])))
