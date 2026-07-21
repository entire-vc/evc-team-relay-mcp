"""Tests for upsert_file routing: sync-upload for folder shares, upload for doc shares."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


BASE_URL = "https://relay.example.com"
AGENT_KEY = "test-agent-key-abc123"
SHARE_ID = "research-vault"
FILE_PATH = "notes/test.md"
CONTENT = "# Test\n\nHello world."


def _make_response(status: int, body: dict) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = body
    mock.raise_for_status = MagicMock()
    return mock


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("RELAY_CP_URL", BASE_URL)
    monkeypatch.setenv("RELAY_AGENT_KEY", AGENT_KEY)
    monkeypatch.delenv("RELAY_EMAIL", raising=False)
    monkeypatch.delenv("RELAY_PASSWORD", raising=False)


class TestResolvShareKind:
    def test_returns_folder_when_api_says_folder(self, monkeypatch):
        import relay_mcp

        resp = _make_response(200, {"kind": "folder", "id": SHARE_ID})
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = resp

        with patch.object(relay_mcp, "_get_client", return_value=mock_client):
            kind = relay_mcp._resolve_share_kind(SHARE_ID, AGENT_KEY)

        assert kind == "folder"
        mock_client.get.assert_called_once_with(
            f"{BASE_URL}/v1/web/shares/{SHARE_ID}",
            headers={"X-Agent-Key": AGENT_KEY},
        )

    def test_returns_doc_when_api_says_doc(self, monkeypatch):
        import relay_mcp

        resp = _make_response(200, {"kind": "doc", "id": SHARE_ID})
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = resp

        with patch.object(relay_mcp, "_get_client", return_value=mock_client):
            kind = relay_mcp._resolve_share_kind(SHARE_ID, AGENT_KEY)

        assert kind == "doc"

    def test_defaults_to_folder_on_404(self, monkeypatch):
        import relay_mcp

        resp = _make_response(404, {"error": "not found"})
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = resp

        with patch.object(relay_mcp, "_get_client", return_value=mock_client):
            kind = relay_mcp._resolve_share_kind(SHARE_ID, AGENT_KEY)

        assert kind == "folder"

    def test_defaults_to_folder_on_network_error(self, monkeypatch):
        import relay_mcp

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = Exception("network failure")

        with patch.object(relay_mcp, "_get_client", return_value=mock_client):
            kind = relay_mcp._resolve_share_kind(SHARE_ID, AGENT_KEY)

        assert kind == "folder"

    def test_defaults_to_folder_when_kind_missing_from_response(self, monkeypatch):
        import relay_mcp

        resp = _make_response(200, {"id": SHARE_ID})  # no 'kind' key
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = resp

        with patch.object(relay_mcp, "_get_client", return_value=mock_client):
            kind = relay_mcp._resolve_share_kind(SHARE_ID, AGENT_KEY)

        assert kind == "folder"


class TestUpsertFileAgentKey:
    def _mock_client_seq(self, responses: list) -> MagicMock:
        """Return a mock client that yields responses in order across __enter__ calls."""
        call_count = 0
        instances = []
        for resp in responses:
            m = MagicMock()
            m.__enter__ = MagicMock(return_value=m)
            m.__exit__ = MagicMock(return_value=False)
            m.get.return_value = resp
            m.post.return_value = resp
            instances.append(m)
        side_effect = iter(instances)

        factory = MagicMock(side_effect=lambda: next(side_effect))
        return factory

    def test_folder_share_uses_sync_upload(self):
        import relay_mcp

        kind_resp = _make_response(200, {"kind": "folder"})
        upload_resp = _make_response(200, {"path": FILE_PATH, "size": len(CONTENT)})

        kind_client = MagicMock()
        kind_client.__enter__ = MagicMock(return_value=kind_client)
        kind_client.__exit__ = MagicMock(return_value=False)
        kind_client.get.return_value = kind_resp

        upload_client = MagicMock()
        upload_client.__enter__ = MagicMock(return_value=upload_client)
        upload_client.__exit__ = MagicMock(return_value=False)
        upload_client.post.return_value = upload_resp

        clients = iter([kind_client, upload_client])

        with patch.object(relay_mcp, "_get_client", side_effect=lambda: next(clients)):
            result_raw = relay_mcp.upsert_file(SHARE_ID, FILE_PATH, CONTENT)

        result = json.loads(result_raw)
        assert result["operation"] == "uploaded"

        upload_client.post.assert_called_once()
        call_args = upload_client.post.call_args
        assert f"/v1/web/shares/{SHARE_ID}/sync-upload" in call_args[0][0]

    def test_doc_share_uses_upload(self):
        import relay_mcp

        kind_resp = _make_response(200, {"kind": "doc"})
        upload_resp = _make_response(200, {"path": FILE_PATH, "size": len(CONTENT)})

        kind_client = MagicMock()
        kind_client.__enter__ = MagicMock(return_value=kind_client)
        kind_client.__exit__ = MagicMock(return_value=False)
        kind_client.get.return_value = kind_resp

        upload_client = MagicMock()
        upload_client.__enter__ = MagicMock(return_value=upload_client)
        upload_client.__exit__ = MagicMock(return_value=False)
        upload_client.post.return_value = upload_resp

        clients = iter([kind_client, upload_client])

        with patch.object(relay_mcp, "_get_client", side_effect=lambda: next(clients)):
            result_raw = relay_mcp.upsert_file(SHARE_ID, FILE_PATH, CONTENT)

        result = json.loads(result_raw)
        assert result["operation"] == "uploaded"

        upload_client.post.assert_called_once()
        call_args = upload_client.post.call_args
        assert f"/v1/web/shares/{SHARE_ID}/upload" in call_args[0][0]
        assert "sync-upload" not in call_args[0][0]

    def test_kind_resolution_failure_defaults_to_sync_upload(self):
        """When share metadata is unavailable, default 'folder' → sync-upload."""
        import relay_mcp

        kind_resp = _make_response(404, {"error": "not found"})
        upload_resp = _make_response(200, {"path": FILE_PATH, "size": len(CONTENT)})

        kind_client = MagicMock()
        kind_client.__enter__ = MagicMock(return_value=kind_client)
        kind_client.__exit__ = MagicMock(return_value=False)
        kind_client.get.return_value = kind_resp

        upload_client = MagicMock()
        upload_client.__enter__ = MagicMock(return_value=upload_client)
        upload_client.__exit__ = MagicMock(return_value=False)
        upload_client.post.return_value = upload_resp

        clients = iter([kind_client, upload_client])

        with patch.object(relay_mcp, "_get_client", side_effect=lambda: next(clients)):
            result_raw = relay_mcp.upsert_file(SHARE_ID, FILE_PATH, CONTENT)

        result = json.loads(result_raw)
        assert result["operation"] == "uploaded"

        upload_client.post.assert_called_once()
        call_args = upload_client.post.call_args
        assert f"/v1/web/shares/{SHARE_ID}/sync-upload" in call_args[0][0]

    def test_agent_key_passed_in_header(self):
        import relay_mcp

        kind_resp = _make_response(200, {"kind": "folder"})
        upload_resp = _make_response(200, {"path": FILE_PATH, "size": len(CONTENT)})

        kind_client = MagicMock()
        kind_client.__enter__ = MagicMock(return_value=kind_client)
        kind_client.__exit__ = MagicMock(return_value=False)
        kind_client.get.return_value = kind_resp

        upload_client = MagicMock()
        upload_client.__enter__ = MagicMock(return_value=upload_client)
        upload_client.__exit__ = MagicMock(return_value=False)
        upload_client.post.return_value = upload_resp

        clients = iter([kind_client, upload_client])

        with patch.object(relay_mcp, "_get_client", side_effect=lambda: next(clients)):
            relay_mcp.upsert_file(SHARE_ID, FILE_PATH, CONTENT)

        headers = upload_client.post.call_args[1]["headers"]
        assert headers["X-Agent-Key"] == AGENT_KEY
        assert "Content-Type" in headers

    def test_content_encoded_as_utf8(self):
        import relay_mcp

        unicode_content = "# Привет\n\nMärchen café"
        kind_resp = _make_response(200, {"kind": "folder"})
        upload_resp = _make_response(200, {"path": FILE_PATH, "size": 42})

        kind_client = MagicMock()
        kind_client.__enter__ = MagicMock(return_value=kind_client)
        kind_client.__exit__ = MagicMock(return_value=False)
        kind_client.get.return_value = kind_resp

        upload_client = MagicMock()
        upload_client.__enter__ = MagicMock(return_value=upload_client)
        upload_client.__exit__ = MagicMock(return_value=False)
        upload_client.post.return_value = upload_resp

        clients = iter([kind_client, upload_client])

        with patch.object(relay_mcp, "_get_client", side_effect=lambda: next(clients)):
            relay_mcp.upsert_file(SHARE_ID, FILE_PATH, unicode_content)

        body = upload_client.post.call_args[1]["content"]
        assert body == unicode_content.encode("utf-8")


class TestUpsertFileEmailPassword:
    """Email/password mode has no backend write route (TR-05, #0cdd5328) — must
    raise clearly instead of hitting the nonexistent /v1/documents/* API these
    tests used to mock. The old mocked "success" here never worked against a
    real server; asserting a raise is the honest behavior.
    """

    @pytest.fixture(autouse=True)
    def email_env(self, monkeypatch):
        monkeypatch.delenv("RELAY_AGENT_KEY", raising=False)
        monkeypatch.setenv("RELAY_EMAIL", "test@example.com")
        monkeypatch.setenv("RELAY_PASSWORD", "secret")

    def test_raises_with_no_http_call(self, monkeypatch):
        import relay_mcp

        relay_mcp._token = "fake-jwt"
        relay_mcp._token_expires = float("inf")

        client = MagicMock()
        with patch.object(relay_mcp, "_get_client", return_value=client) as get_client:
            with pytest.raises(ValueError, match="upsert_file"):
                relay_mcp.upsert_file(SHARE_ID, FILE_PATH, CONTENT)
        get_client.assert_not_called()
