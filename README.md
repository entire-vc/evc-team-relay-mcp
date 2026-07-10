# EVC Team Relay - MCP Server

[![PyPI](https://img.shields.io/pypi/v/evc-team-relay-mcp)](https://pypi.org/project/evc-team-relay-mcp/)
[![Docker Hub](https://img.shields.io/docker/v/deadalusevc/evc-team-relay-mcp?label=docker)](https://hub.docker.com/r/deadalusevc/evc-team-relay-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-server-4A90D9)](https://modelcontextprotocol.io)
[![Install via Spark](https://spark.entire.vc/badges/evc-team-relay-mcp/install.svg)](https://spark.entire.vc/assets/evc-team-relay-mcp?utm_source=github&utm_medium=readme)

**Give your AI agent read/write access to your Obsidian vault.**

> Your agent reads your notes, creates new ones, and stays in sync — all through the [Team Relay](https://github.com/entire-vc/evc-team-relay) API.

Works with **Claude Code**, **Codex CLI**, **OpenCode**, and any [MCP](https://modelcontextprotocol.io)-compatible client.

<a href="https://glama.ai/mcp/servers/@entire-vc/evc-team-relay-mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@entire-vc/evc-team-relay-mcp/badge" alt="evc-team-relay-mcp MCP server" />
</a>

---

## Quick Start

### 1. Install

**Option A — from PyPI (recommended):**

No installation needed — `uvx` downloads and runs automatically. Skip to step 2.

**Option B — from source:**

```bash
git clone https://github.com/entire-vc/evc-team-relay-mcp.git
cd evc-team-relay-mcp
uv sync   # or: pip install .
```

### 2. Configure your AI tool

Add the MCP server to your tool's config. Choose one authentication method:

**Agent key** (recommended) — create a key in the Obsidian plugin → Team Relay settings → **Agent Keys**. Supports read and write: `list_files`, `read_file`, `tr_search`, and `upsert_file` all work with a single key. [Quickstart →](https://github.com/entire-vc/evc-team-relay/blob/main/docs/agent-keys.md)

**Email + password** — use a dedicated agent account on your Relay instance.

<details>
<summary><b>Claude Code — agent key</b></summary>

Add to `.mcp.json` in your project root or `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "evc-relay": {
      "command": "uvx",
      "args": ["evc-team-relay-mcp"],
      "env": {
        "RELAY_CP_URL": "https://cp.yourdomain.com",
        "RELAY_AGENT_KEY": "tr_agent_your_key_here"
      }
    }
  }
}
```

</details>

<details>
<summary><b>Claude Code — email/password</b></summary>

```json
{
  "mcpServers": {
    "evc-relay": {
      "command": "uvx",
      "args": ["evc-team-relay-mcp"],
      "env": {
        "RELAY_CP_URL": "https://cp.yourdomain.com",
        "RELAY_EMAIL": "agent@yourdomain.com",
        "RELAY_PASSWORD": "your-password"
      }
    }
  }
}
```

</details>

<details>
<summary><b>Codex CLI</b></summary>

Add to your `codex.json`:

```json
{
  "mcp_servers": {
    "evc-relay": {
      "type": "stdio",
      "command": "uvx",
      "args": ["evc-team-relay-mcp"],
      "env": {
        "RELAY_CP_URL": "https://cp.yourdomain.com",
        "RELAY_AGENT_KEY": "tr_agent_your_key_here"
      }
    }
  }
}
```

</details>

<details>
<summary><b>OpenCode</b></summary>

Add to `opencode.json`:

```json
{
  "mcpServers": {
    "evc-relay": {
      "command": "uvx",
      "args": ["evc-team-relay-mcp"],
      "env": {
        "RELAY_CP_URL": "https://cp.yourdomain.com",
        "RELAY_AGENT_KEY": "tr_agent_your_key_here"
      }
    }
  }
}
```

</details>

<details>
<summary><b>From source (all tools)</b></summary>

If you installed from source instead of PyPI, replace `"command": "uvx"` / `"args": ["evc-team-relay-mcp"]` with:

```json
"command": "uv",
"args": ["run", "--directory", "/path/to/evc-team-relay-mcp", "relay_mcp.py"]
```

</details>

**Environment variables:**

| Variable | Required | Description |
|----------|----------|-------------|
| `RELAY_CP_URL` | Yes | Control plane base URL |
| `RELAY_AGENT_KEY` | One of | Agent key from plugin settings — read + write (recommended) |
| `RELAY_EMAIL` | One of | Account email (email/password mode) |
| `RELAY_PASSWORD` | One of | Account password (email/password mode) |

Ready-to-copy config templates are also in `config/`.

### 3. Use it

Your AI agent now has these tools:

| Tool | Description |
|------|-------------|
| `authenticate` | Authenticate with credentials (auto-managed) |
| `list_shares` | List accessible shares (filter by kind, ownership) |
| `list_files` | List files in a folder share |
| **`read_file`** | Read a file by path from a folder share |
| `read_document` | Read document by doc_id (low-level) |
| **`upsert_file`** | Create or update a file by path |
| `write_document` | Write to a document by doc_id |
| `delete_file` | Delete a file from a folder share |

**Typical workflow:** `list_shares` -> `list_files` -> `read_file` / `upsert_file`

Authentication is automatic — the server logs in and refreshes tokens internally.

---

## Remote Deployment (HTTP Transport)

For shared or server-side deployments, run as an HTTP server:

```bash
# Direct
uv run relay_mcp.py --transport http --port 8888

# Docker (pulls from Docker Hub automatically)
RELAY_CP_URL=https://cp.yourdomain.com \
RELAY_EMAIL=agent@yourdomain.com \
RELAY_PASSWORD=your-password \
docker compose up -d

# Or pull explicitly
docker pull deadalusevc/evc-team-relay-mcp:latest
```

**By default the server binds to `127.0.0.1` (localhost-only)** — the endpoint is not
reachable over the network even if the host has a public IP. This matches the common
case of a single MCP client on the same machine as the server.

Then configure your MCP client to connect via HTTP:

```json
{
  "mcpServers": {
    "evc-relay": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8888/mcp"
    }
  }
}
```

### Remote access via SSH tunnel (recommended)

If your MCP client runs on a different machine than the server, tunnel to the
localhost-bound port instead of exposing it publicly:

```bash
# From the client machine, forward local 8888 to the server's localhost:8888
ssh -N -L 8888:127.0.0.1:8888 user@your-server
```

Then point the client config at `http://127.0.0.1:8888/mcp` as above — traffic
goes through the SSH tunnel, and the server's bind address never needs to change.

### Public / reverse-proxy binding (opt-in)

If you genuinely need the server to accept connections from other hosts directly
(e.g. it sits behind a reverse proxy that terminates TLS and handles auth), pass
`--host` explicitly:

```bash
uv run relay_mcp.py --transport http --port 8888 --host 0.0.0.0
```

Only do this behind a reverse proxy or firewall — the MCP HTTP endpoint itself
has no built-in authentication, so binding it to `0.0.0.0` on an open network
exposes every relay tool call to anyone who can reach the port.

---

## Security

The MCP server provides significant security advantages over shell-based integrations:

- **No shell execution** — all operations are Python function calls via JSON-RPC, eliminating command injection risks
- **No CLI arguments** — credentials and tokens are never passed as process arguments (invisible in `ps` output)
- **Automatic token management** — the server handles login, JWT refresh, and token lifecycle internally; the agent never touches raw tokens
- **Typed inputs** — all parameters are validated against JSON Schema before execution
- **Single persistent process** — no per-call shell spawning, no environment leakage between invocations

> **Note:** If you're using the [OpenClaw skill](https://github.com/entire-vc/evc-team-relay-openclaw-skill) (bash scripts), consider migrating to this MCP server for a more secure and maintainable integration.

---

## How It Works

```
┌─────────────┐      MCP        ┌──────────────┐     REST API     ┌──────────────┐     Yjs CRDT      ┌──────────────┐
│  AI Agent   │ ◄────────────► │  MCP Server  │ ◄─────────────► │  Team Relay  │ ◄──────────────► │   Obsidian   │
│ (any tool)  │  stdio / HTTP  │ (this repo)  │    read/write   │   Server     │    real-time     │    Client    │
└─────────────┘                └──────────────┘                 └──────────────┘      sync         └──────────────┘
```

The MCP server wraps Team Relay's REST API into standard MCP tools. Team Relay stores documents as Yjs CRDTs and syncs them to Obsidian clients in real-time. Changes made by the agent appear in Obsidian instantly — and vice versa.

---

## Prerequisites

- Python 3.10+ with [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A running [EVC Team Relay](https://github.com/entire-vc/evc-team-relay) instance (self-hosted or [hosted](https://entire.vc))
- A user account on the Relay control plane

---

## Part of the Entire VC Toolbox

| Product | What it does | Link |
|---------|-------------|------|
| **Team Relay** | Self-hosted collaboration server | [repo](https://github.com/entire-vc/evc-team-relay) |
| **Team Relay Plugin** | Obsidian plugin for Team Relay | [repo](https://github.com/entire-vc/evc-team-relay-obsidian-plugin) |
| **Relay MCP** | MCP server for AI agents | this repo |
| **OpenClaw Skill** | OpenClaw agent skill (bash) | [repo](https://github.com/entire-vc/evc-team-relay-openclaw-skill) |
| **Local Sync** | Vault <-> AI dev tools sync | [repo](https://github.com/entire-vc/evc-local-sync-plugin) |
| **Spark MCP** | MCP server for AI workflow catalog | [repo](https://github.com/entire-vc/evc-spark-mcp) |

## Community

- [entire.vc](https://entire.vc)
- [Discussions](https://github.com/entire-vc/.github/discussions)
- in@entire.vc

[//]: # (mcp-name: io.github.entire-vc/evc-team-relay-mcp)

## License

MIT
