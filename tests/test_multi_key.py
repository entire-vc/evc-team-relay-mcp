"""Tests for RELAY_AGENT_KEYS multi-share agent-key support."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

BASE_URL = "https://relay.example.com"
SHARE_MESH = "mesh"
SHARE_SPARK = "spark"
KEY_MESH = "key-for-mesh-abc"
KEY_SPARK = "key-for-spark-xyz"
MULTI_KEYS_ENV = f"{SHARE_MESH}:{KEY_MESH},{SHARE_SPARK}:{KEY_SPARK}"


def _mock_response(status: int, body: dict | list | str) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    if isinstance(body, str):
        m.text = body
        m.json.return_value = json.loads(body)
    else:
        m.text = json.dumps(body)
        m.json.return_value = body
    m.raise_for_status = MagicMock()
    return m


def _mock_client(get_resp=None, post_resp=None) -> MagicMock:
    c = MagicMock()
    c.__enter__ = MagicMock(return_value=c)
    c.__exit__ = MagicMock(return_value=False)
    if get_resp is not None:
        c.get.return_value = get_resp
    if post_resp is not None:
        c.post.return_value = post_resp
    return c


@pytest.fixture(autouse=True)
def base_env(monkeypatch):
    monkeypatch.setenv("RELAY_CP_URL", BASE_URL)
    monkeypatch.delenv("RELAY_AGENT_KEY", raising=False)
    monkeypatch.delenv("RELAY_AGENT_KEYS", raising=False)
    monkeypatch.delenv("RELAY_EMAIL", raising=False)
    monkeypatch.delenv("RELAY_PASSWORD", raising=False)


class TestParseAgentKeys:
    def test_empty_env_returns_empty_dict(self):
        import relay_mcp
        assert relay_mcp._parse_agent_keys() == {}

    def test_single_pair(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", f"{SHARE_MESH}:{KEY_MESH}")
        assert relay_mcp._parse_agent_keys() == {SHARE_MESH: KEY_MESH}

    def test_multiple_pairs(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)
        result = relay_mcp._parse_agent_keys()
        assert result == {SHARE_MESH: KEY_MESH, SHARE_SPARK: KEY_SPARK}

    def test_ignores_malformed_entry(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", f"{SHARE_MESH}:{KEY_MESH},bad-entry,{SHARE_SPARK}:{KEY_SPARK}")
        result = relay_mcp._parse_agent_keys()
        assert SHARE_MESH in result
        assert SHARE_SPARK in result
        assert len(result) == 2

    def test_key_with_colon_uses_first_colon_as_separator(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", f"{SHARE_MESH}:key:with:colons")
        result = relay_mcp._parse_agent_keys()
        assert result == {SHARE_MESH: "key:with:colons"}

    def test_strips_whitespace(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", f" {SHARE_MESH} : {KEY_MESH} , {SHARE_SPARK} : {KEY_SPARK} ")
        result = relay_mcp._parse_agent_keys()
        assert result == {SHARE_MESH: KEY_MESH, SHARE_SPARK: KEY_SPARK}


class TestGetKeyForShare:
    def test_multi_key_returns_share_specific_key(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)
        assert relay_mcp._get_key_for_share(SHARE_MESH) == KEY_MESH
        assert relay_mcp._get_key_for_share(SHARE_SPARK) == KEY_SPARK

    def test_falls_back_to_global_key_when_share_not_in_map(self, monkeypatch):
        import relay_mcp
        global_key = "global-key-xyz"
        monkeypatch.setenv("RELAY_AGENT_KEYS", f"{SHARE_MESH}:{KEY_MESH}")
        monkeypatch.setenv("RELAY_AGENT_KEY", global_key)
        assert relay_mcp._get_key_for_share(SHARE_SPARK) == global_key

    def test_returns_global_key_when_no_multi_key_map(self, monkeypatch):
        import relay_mcp
        global_key = "global-only-key"
        monkeypatch.setenv("RELAY_AGENT_KEY", global_key)
        assert relay_mcp._get_key_for_share(SHARE_MESH) == global_key

    def test_returns_none_when_no_keys_configured(self):
        import relay_mcp
        assert relay_mcp._get_key_for_share(SHARE_MESH) is None

    def test_map_takes_priority_over_global_key(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)
        monkeypatch.setenv("RELAY_AGENT_KEY", "global-fallback")
        assert relay_mcp._get_key_for_share(SHARE_MESH) == KEY_MESH
        assert relay_mcp._get_key_for_share(SHARE_SPARK) == KEY_SPARK


class TestIsAgentKeyMode:
    def test_true_when_global_key_set(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEY", "some-key")
        assert relay_mcp._is_agent_key_mode() is True

    def test_true_when_multi_keys_set(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)
        assert relay_mcp._is_agent_key_mode() is True

    def test_false_when_no_keys(self):
        import relay_mcp
        assert relay_mcp._is_agent_key_mode() is False


class TestAuthenticateMultiKey:
    def test_describes_multi_key_shares(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)
        result = relay_mcp.authenticate()
        assert "2 share-specific keys" in result
        assert SHARE_MESH in result
        assert SHARE_SPARK in result

    def test_no_suffix_when_global_key_absent(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)
        result = relay_mcp.authenticate()
        assert "global fallback" not in result

    def test_suffix_when_global_key_also_set(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)
        monkeypatch.setenv("RELAY_AGENT_KEY", "global-key")
        result = relay_mcp.authenticate()
        assert "global fallback key" in result

    def test_single_key_mode_unchanged(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEY", "single-key")
        result = relay_mcp.authenticate()
        assert "Agent key mode active" in result
        assert "share-specific" not in result


class TestListSharesMultiKey:
    def test_fetches_metadata_for_each_share(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)

        mesh_data = {"id": "uuid-mesh", "kind": "folder", "path": "mesh"}
        spark_data = {"id": "uuid-spark", "kind": "folder", "path": "spark"}

        mesh_client = _mock_client(get_resp=_mock_response(200, mesh_data))
        spark_client = _mock_client(get_resp=_mock_response(200, spark_data))
        clients = iter([mesh_client, spark_client])

        with patch.object(relay_mcp, "_get_client", side_effect=lambda: next(clients)):
            result = json.loads(relay_mcp.list_shares())

        assert len(result) == 2
        ids = {s["id"] for s in result}
        assert "uuid-mesh" in ids
        assert "uuid-spark" in ids

    def test_uses_per_share_key_in_header(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)

        mesh_client = _mock_client(get_resp=_mock_response(200, {"id": "m", "kind": "folder"}))
        spark_client = _mock_client(get_resp=_mock_response(200, {"id": "s", "kind": "folder"}))
        clients = iter([mesh_client, spark_client])

        with patch.object(relay_mcp, "_get_client", side_effect=lambda: next(clients)):
            relay_mcp.list_shares()

        mesh_client.get.assert_called_once()
        assert mesh_client.get.call_args[1]["headers"] == {"X-Agent-Key": KEY_MESH}
        spark_client.get.assert_called_once()
        assert spark_client.get.call_args[1]["headers"] == {"X-Agent-Key": KEY_SPARK}

    def test_filters_by_kind(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)

        mesh_client = _mock_client(get_resp=_mock_response(200, {"id": "m", "kind": "folder"}))
        spark_client = _mock_client(get_resp=_mock_response(200, {"id": "s", "kind": "doc"}))
        clients = iter([mesh_client, spark_client])

        with patch.object(relay_mcp, "_get_client", side_effect=lambda: next(clients)):
            result = json.loads(relay_mcp.list_shares(kind="folder"))

        assert len(result) == 1
        assert result[0]["kind"] == "folder"

    def test_skips_failed_share_fetch(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)

        mesh_client = _mock_client(get_resp=_mock_response(403, {"error": "forbidden"}))
        spark_client = _mock_client(get_resp=_mock_response(200, {"id": "s", "kind": "folder"}))
        clients = iter([mesh_client, spark_client])

        with patch.object(relay_mcp, "_get_client", side_effect=lambda: next(clients)):
            result = json.loads(relay_mcp.list_shares())

        assert len(result) == 1
        assert result[0]["id"] == "s"

    def test_single_key_mode_returns_empty_list(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEY", "single-key")
        result = json.loads(relay_mcp.list_shares())
        assert result == []


class TestListFilesMultiKey:
    def test_uses_share_specific_key(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)

        files_resp = _mock_response(200, {"share_id": SHARE_SPARK, "files": {}})
        client = _mock_client(get_resp=files_resp)

        with patch.object(relay_mcp, "_get_client", return_value=client):
            relay_mcp.list_files(SHARE_SPARK)

        call_args = client.get.call_args
        assert call_args[1]["headers"] == {"X-Agent-Key": KEY_SPARK}
        assert f"/v1/web/shares/{SHARE_SPARK}/files-index" in call_args[0][0]


class TestTrSearchMultiKey:
    def test_uses_share_specific_key(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)

        files_resp = _mock_response(200, {"files": {"notes/hello.md": {"modified_at": None}}})
        client = _mock_client(get_resp=files_resp)

        with patch.object(relay_mcp, "_get_client", return_value=client):
            relay_mcp.tr_search(SHARE_MESH, "hello")

        assert client.get.call_args[1]["headers"] == {"X-Agent-Key": KEY_MESH}


class TestReadFileMultiKey:
    def test_uses_share_specific_key(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)

        download_resp = MagicMock()
        download_resp.status_code = 200
        download_resp.text = "# Hello"
        download_resp.headers = {"content-type": "text/plain"}
        download_resp.raise_for_status = MagicMock()

        client = _mock_client(get_resp=download_resp)

        with patch.object(relay_mcp, "_get_client", return_value=client):
            result = json.loads(relay_mcp.read_file(SHARE_SPARK, "notes/file.md"))

        assert result["content"] == "# Hello"
        assert client.get.call_args[1]["headers"] == {"X-Agent-Key": KEY_SPARK}


class TestUpsertFileMultiKey:
    def test_uses_share_specific_key(self, monkeypatch):
        import relay_mcp
        monkeypatch.setenv("RELAY_AGENT_KEYS", MULTI_KEYS_ENV)

        kind_resp = _mock_response(200, {"kind": "folder"})
        upload_resp = _mock_response(200, {"path": "file.md", "size": 10})

        kind_client = _mock_client(get_resp=kind_resp)
        upload_client = _mock_client(post_resp=upload_resp)
        clients = iter([kind_client, upload_client])

        with patch.object(relay_mcp, "_get_client", side_effect=lambda: next(clients)):
            relay_mcp.upsert_file(SHARE_MESH, "file.md", "content")

        upload_headers = upload_client.post.call_args[1]["headers"]
        assert upload_headers["X-Agent-Key"] == KEY_MESH
