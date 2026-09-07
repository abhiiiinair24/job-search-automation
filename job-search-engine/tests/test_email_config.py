import pytest

from jobsearch.email.config import EmailConfig, EmailConfigError


def test_from_env_success(monkeypatch):
    monkeypatch.setenv("JOBSEARCH_RECIPIENT_EMAIL", "someone@example.com")
    monkeypatch.delenv("JOBSEARCH_SENDER_EMAIL", raising=False)
    monkeypatch.delenv("JOBSEARCH_EMAIL_SUBJECT_PREFIX", raising=False)

    config = EmailConfig.from_env()

    assert config.recipient_email == "someone@example.com"
    assert config.sender_email is None
    assert config.subject_prefix == ""


def test_from_env_includes_optional_sender_and_prefix(monkeypatch):
    monkeypatch.setenv("JOBSEARCH_RECIPIENT_EMAIL", "someone@example.com")
    monkeypatch.setenv("JOBSEARCH_SENDER_EMAIL", "bot@example.com")
    monkeypatch.setenv("JOBSEARCH_EMAIL_SUBJECT_PREFIX", "[JobBot] ")

    config = EmailConfig.from_env()

    assert config.sender_email == "bot@example.com"
    assert config.subject_prefix == "[JobBot] "


def test_from_env_raises_when_recipient_missing(monkeypatch):
    monkeypatch.delenv("JOBSEARCH_RECIPIENT_EMAIL", raising=False)

    with pytest.raises(EmailConfigError) as exc_info:
        EmailConfig.from_env()

    assert "JOBSEARCH_RECIPIENT_EMAIL" in str(exc_info.value)


def test_from_env_treats_empty_recipient_as_missing(monkeypatch):
    monkeypatch.setenv("JOBSEARCH_RECIPIENT_EMAIL", "")

    with pytest.raises(EmailConfigError):
        EmailConfig.from_env()


def test_no_email_address_hard_coded_in_config_module():
    # Guard against regressions: the recipient must only ever come from
    # the environment, never a literal address in source. Check for an
    # actual email-address pattern, not just the "@" in decorators like
    # @dataclass / @classmethod.
    import inspect
    import re

    import jobsearch.email.config as config_module

    source = inspect.getsource(config_module)
    email_pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    assert email_pattern.search(source) is None
