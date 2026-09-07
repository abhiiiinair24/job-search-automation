from unittest.mock import patch

import pytest

from jobsearch.email.gmail_auth import (
    GMAIL_SEND_SCOPE,
    GmailAuthConfig,
    GmailAuthConfigError,
    build_credentials,
)


# --- GmailAuthConfig.from_env() ---------------------------------------------


def test_from_env_success(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-123")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "secret-456")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-789")
    monkeypatch.delenv("GMAIL_TOKEN_URI", raising=False)

    config = GmailAuthConfig.from_env()

    assert config.client_id == "client-123"
    assert config.client_secret == "secret-456"
    assert config.refresh_token == "refresh-789"
    assert config.token_uri == "https://oauth2.googleapis.com/token"


def test_from_env_allows_token_uri_override(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-123")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "secret-456")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-789")
    monkeypatch.setenv("GMAIL_TOKEN_URI", "https://example.com/token")

    config = GmailAuthConfig.from_env()

    assert config.token_uri == "https://example.com/token"


def test_from_env_raises_when_all_vars_missing(monkeypatch):
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN", raising=False)

    with pytest.raises(GmailAuthConfigError) as exc_info:
        GmailAuthConfig.from_env()

    message = str(exc_info.value)
    assert "GMAIL_CLIENT_ID" in message
    assert "GMAIL_CLIENT_SECRET" in message
    assert "GMAIL_REFRESH_TOKEN" in message


def test_from_env_raises_when_one_var_missing(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-123")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "secret-456")
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN", raising=False)

    with pytest.raises(GmailAuthConfigError) as exc_info:
        GmailAuthConfig.from_env()

    message = str(exc_info.value)
    assert "GMAIL_REFRESH_TOKEN" in message
    # Only the actually-missing var should be listed as missing.
    assert "GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET" not in message


def test_from_env_treats_empty_string_as_missing(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "secret-456")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-789")

    with pytest.raises(GmailAuthConfigError):
        GmailAuthConfig.from_env()


def test_error_message_does_not_leak_secret_values(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-123")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "super-secret-value")
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN", raising=False)

    with pytest.raises(GmailAuthConfigError) as exc_info:
        GmailAuthConfig.from_env()

    # The error should name the missing *variable*, never any secret value
    # that happens to be set for the other variables.
    assert "super-secret-value" not in str(exc_info.value)
    assert "client-123" not in str(exc_info.value)


# --- build_credentials() ----------------------------------------------------


def test_build_credentials_passes_config_values_to_google_credentials():
    config = GmailAuthConfig(
        client_id="client-123",
        client_secret="secret-456",
        refresh_token="refresh-789",
        token_uri="https://oauth2.googleapis.com/token",
    )

    with patch("google.oauth2.credentials.Credentials") as mock_credentials_cls:
        build_credentials(config)

    mock_credentials_cls.assert_called_once_with(
        token=None,
        refresh_token="refresh-789",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client-123",
        client_secret="secret-456",
        scopes=[GMAIL_SEND_SCOPE],
    )


def test_build_credentials_uses_from_env_when_no_config_passed(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-abc")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "secret-def")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "refresh-ghi")

    with patch("google.oauth2.credentials.Credentials") as mock_credentials_cls:
        build_credentials()

    _, kwargs = mock_credentials_cls.call_args
    assert kwargs["client_id"] == "client-abc"
    assert kwargs["refresh_token"] == "refresh-ghi"


def test_build_credentials_requests_gmail_send_scope_only():
    config = GmailAuthConfig(client_id="a", client_secret="b", refresh_token="c")
    with patch("google.oauth2.credentials.Credentials") as mock_credentials_cls:
        build_credentials(config)
    _, kwargs = mock_credentials_cls.call_args
    assert kwargs["scopes"] == ["https://www.googleapis.com/auth/gmail.send"]
