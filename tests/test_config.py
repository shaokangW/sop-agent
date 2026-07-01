"""Tests for settings assembly, esp. reading bailian creds from opencode config."""
import json

from sopagent.config import BAILIAN_DEFAULT_BASE_URL, Settings, _read_opencode_provider_options


def _write_opencode(tmp_path, options):
    (tmp_path / "opencode.json").write_text(
        json.dumps({"provider": {"bailian": {"options": options}}}), encoding="utf-8"
    )


def test_read_bailian_options_from_opencode(tmp_path, monkeypatch):
    _write_opencode(tmp_path, {"apiKey": "sk-test-123", "baseURL": "https://example.com/v1"})
    monkeypatch.setattr("sopagent.config._opencode_config_dir", lambda: tmp_path)

    opts = _read_opencode_provider_options("bailian")
    assert opts["apiKey"] == "sk-test-123"
    assert opts["baseURL"] == "https://example.com/v1"


def test_env_api_key_overrides_opencode_file(tmp_path, monkeypatch):
    _write_opencode(tmp_path, {"apiKey": "sk-from-file", "baseURL": "https://from-file/v1"})
    monkeypatch.setattr("sopagent.config._opencode_config_dir", lambda: tmp_path)
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-from-env")

    s = Settings.from_env()
    assert s.providers["bailian"].name == "bailian"
    assert s.providers["bailian"].api_key == "sk-from-env"
    assert s.providers["bailian"].base_url == "https://from-file/v1"


def test_default_base_url_when_nothing_configured(tmp_path, monkeypatch):
    monkeypatch.setattr("sopagent.config._opencode_config_dir", lambda: tmp_path)
    monkeypatch.delenv("BAILIAN_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    s = Settings.from_env()
    assert s.providers["bailian"].base_url == BAILIAN_DEFAULT_BASE_URL
    assert s.providers["bailian"].api_key is None


def test_jsonc_comments_stripped(tmp_path, monkeypatch):
    (tmp_path / "opencode.jsonc").write_text(
        '// header comment\n{"provider":{"bailian":{"options":{"apiKey":"sk-x",'
        '"baseURL":"https://x/v1",}}}}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("sopagent.config._opencode_config_dir", lambda: tmp_path)

    s = Settings.from_env()
    assert s.providers["bailian"].api_key == "sk-x"
    assert s.providers["bailian"].base_url == "https://x/v1"
