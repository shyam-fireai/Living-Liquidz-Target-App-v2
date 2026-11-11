import json

import pytest

import config

ENV_KEYS = [
    "CLICKHOUSE_HOST",
    "CLICKHOUSE_PORT",
    "CLICKHOUSE_USER",
    "CLICKHOUSE_PASSWORD",
    "CLICKHOUSE_DATABASE",
    "CLICKHOUSE_SECURE",
    "FIREAI_BASE_URL",
    "FIREAI_API_KEY",
    "ALLOWED_EMAILS",
    "COOKIE_SECRET",
    "SESSION_HOURS",
]

GOOD_FILE = {
    "data_clickhouse": {
        "host": "localhost",
        "port": 8123,
        "username": "u",
        "password": "p",
        "database": "d",
        "secure": False,
    },
    "FIREAI_BASE_URL": "https://auth.example",
    "FIREAI_API_KEY": "k",
    "ALLOWED_EMAILS": "A@x.com, b@x.com",
    "COOKIE_SECRET": "x" * 64,
}


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Point config at a temp secrets file and a clean environment."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    def use(data):
        path = tmp_path / "secrets.json"
        path.write_text(json.dumps(data))
        monkeypatch.setattr(config, "SECRETS_PATH", path)
        config.load_secrets.cache_clear()

    yield use
    config.load_secrets.cache_clear()


def test_valid_file_has_no_problems(settings):
    settings(GOOD_FILE)
    assert config.validate_settings() == []
    assert config.get_allowed_emails() == ["a@x.com", "b@x.com"]
    assert config.session_seconds() == 3600


def test_env_overrides_file(settings, monkeypatch):
    settings(GOOD_FILE)
    monkeypatch.setenv("CLICKHOUSE_HOST", "db.internal")
    monkeypatch.setenv("CLICKHOUSE_PORT", "8443")
    monkeypatch.setenv("CLICKHOUSE_SECURE", "true")
    monkeypatch.setenv("SESSION_HOURS", "8")
    db = config.get_db_settings()
    assert (db["host"], db["port"], db["secure"], db["username"]) == ("db.internal", 8443, True, "u")
    assert config.session_seconds() == 8 * 3600


def test_env_only_without_file(settings, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SECRETS_PATH", tmp_path / "missing.json")
    config.load_secrets.cache_clear()
    env = {
        "CLICKHOUSE_HOST": "h",
        "CLICKHOUSE_USER": "u",
        "CLICKHOUSE_DATABASE": "d",
        "FIREAI_BASE_URL": "https://a",
        "FIREAI_API_KEY": "k",
        "ALLOWED_EMAILS": "a@x.com",
        "COOKIE_SECRET": "s" * 32,
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert config.validate_settings() == []
    assert config.get_db_settings()["port"] == 8123


def test_problems_listed_without_leaking_values(settings):
    bad = dict(GOOD_FILE, COOKIE_SECRET="short-secret-value", ALLOWED_EMAILS="")
    bad["data_clickhouse"] = dict(GOOD_FILE["data_clickhouse"], host="")
    settings(bad)
    problems = config.validate_settings()
    assert any("CLICKHOUSE_HOST" in p for p in problems)
    assert any("ALLOWED_EMAILS" in p for p in problems)
    assert any("COOKIE_SECRET" in p for p in problems)
    assert not any("short-secret-value" in p for p in problems)


def test_unknown_table_rejected():
    with pytest.raises(ValueError):
        config.get_table("system.users")
