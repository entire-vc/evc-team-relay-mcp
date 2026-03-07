# Contributing to EVC Team Relay MCP

Thanks for your interest in contributing! This is the MCP server for reading and writing Obsidian vault documents via EVC Team Relay.

## Getting Started

1. Fork the repository
2. Clone your fork locally
3. Install dependencies: `uv sync` (or `pip install -e .`)
4. Create a feature branch: `git checkout -b feature/my-feature`

## Development

```bash
# Install with uv (recommended)
uv sync

# Run the MCP server locally
uv run relay_mcp.py

# Run with Docker
docker compose up
```

## Testing

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check .
uv run mypy .
```

## Pull Requests

1. Create a branch from `main`
2. Make your changes
3. Ensure tests pass: `uv run pytest`
4. Ensure lint passes: `uv run ruff check .`
5. Write a clear PR description explaining what and why
6. Submit the PR

## Reporting Bugs

Use the [Bug Report](https://github.com/entire-vc/evc-team-relay-mcp/issues/new?template=bug_report.md) issue template.

## Requesting Features

Use the [Feature Request](https://github.com/entire-vc/evc-team-relay-mcp/issues/new?template=feature_request.md) issue template.

## Code Style

- Python 3.11+
- Use `ruff` for formatting and linting
- Type hints encouraged
- Keep changes focused and minimal

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
