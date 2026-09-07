import base64
import email as email_lib
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest

from jobsearch.email.config import EmailConfig
from jobsearch.email.gmail_auth import GmailAuthConfig
from jobsearch.email.gmail_sender import (
    GmailSendError,
    build_raw_message,
    send_email,
    send_search_result_email,
)
from jobsearch.engine import SearchResult
from jobsearch.models import Job, SourceType

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _job(job_id="1", title="AI/ML Engineer") -> Job:
    return Job(
        source=SourceType.GREENHOUSE,
        source_job_id=job_id,
        company="Acme",
        title=title,
        location="Buffalo, NY",
        url="https://example.com/apply/1",
        description="",
        date_updated=NOW,
        fit_score=10.0,
        fit_explanation="matches on: rag",
        matched_keywords=["rag"],
    )


def _result(jobs) -> SearchResult:
    return SearchResult(
        jobs=jobs, total_fetched=len(jobs), total_after_filters=len(jobs),
        failed_sources=[], new_jobs=jobs, already_seen_jobs=[],
    )


def _auth_config() -> GmailAuthConfig:
    return GmailAuthConfig(client_id="client-1", client_secret="secret-1", refresh_token="refresh-1")


# --- build_raw_message -------------------------------------------------------


def test_build_raw_message_is_valid_base64url():
    raw = build_raw_message("someone@example.com", "Test Subject", "<p>hi</p>")
    # Should decode without error (urlsafe alphabet), and the resulting
    # RFC 2822 message should carry our HTML body once its own
    # (separate) content-transfer-encoding is decoded.
    decoded = base64.urlsafe_b64decode(raw.encode("utf-8"))
    message = email_lib.message_from_bytes(decoded)
    assert b"hi" in message.get_payload(decode=True)


def test_build_raw_message_contains_to_and_subject_headers():
    raw = build_raw_message("someone@example.com", "My Subject", "<p>body</p>")
    decoded = base64.urlsafe_b64decode(raw.encode("utf-8"))
    message = email_lib.message_from_bytes(decoded)
    assert message["to"] == "someone@example.com"
    assert message["subject"] == "My Subject"


def test_build_raw_message_includes_html_body_content():
    raw = build_raw_message("someone@example.com", "Subj", "<p>Hello World</p>")
    decoded = base64.urlsafe_b64decode(raw.encode("utf-8"))
    message = email_lib.message_from_bytes(decoded)
    assert message.get_content_type() == "text/html"
    assert "Hello World" in message.get_payload(decode=True).decode("utf-8")


def test_build_raw_message_omits_from_header_when_not_provided():
    raw = build_raw_message("someone@example.com", "Subj", "<p>x</p>")
    decoded = base64.urlsafe_b64decode(raw.encode("utf-8"))
    message = email_lib.message_from_bytes(decoded)
    assert message["from"] is None


def test_build_raw_message_includes_from_header_when_provided():
    raw = build_raw_message(
        "someone@example.com", "Subj", "<p>x</p>", from_address="bot@example.com"
    )
    decoded = base64.urlsafe_b64decode(raw.encode("utf-8"))
    message = email_lib.message_from_bytes(decoded)
    assert message["from"] == "bot@example.com"


# --- send_email --------------------------------------------------------------


def _mock_gmail_service(response=None):
    """Build a Mock replicating service.users().messages().send(...).execute()."""
    service = MagicMock()
    service.users.return_value.messages.return_value.send.return_value.execute.return_value = (
        response or {"id": "msg-123"}
    )
    return service


def test_send_email_calls_gmail_api_with_expected_args():
    with patch("jobsearch.email.gmail_sender.build_credentials") as mock_build_creds, patch(
        "googleapiclient.discovery.build"
    ) as mock_build_service:
        mock_build_creds.return_value = Mock()
        mock_service = _mock_gmail_service({"id": "msg-abc"})
        mock_build_service.return_value = mock_service

        response = send_email(
            to_address="someone@example.com",
            subject="Job Search Update",
            html_body="<p>hi</p>",
            auth_config=_auth_config(),
        )

    assert response == {"id": "msg-abc"}
    mock_build_service.assert_called_once()
    _, kwargs = mock_build_service.call_args
    assert kwargs["credentials"] is mock_build_creds.return_value

    send_call = mock_service.users.return_value.messages.return_value.send
    send_call.assert_called_once()
    _, send_kwargs = send_call.call_args
    assert send_kwargs["userId"] == "me"
    assert "raw" in send_kwargs["body"]


def test_send_email_never_makes_real_network_call():
    # No real network access is possible in this sandbox anyway, but this
    # test documents the expectation explicitly: if the mocks below were
    # ever removed, this test would hang/fail on network access rather
    # than silently succeeding against a real Gmail account.
    with patch("jobsearch.email.gmail_sender.build_credentials") as mock_build_creds, patch(
        "googleapiclient.discovery.build"
    ) as mock_build_service:
        mock_build_creds.return_value = Mock()
        mock_build_service.return_value = _mock_gmail_service()
        send_email("a@example.com", "s", "<p>x</p>", auth_config=_auth_config())
        assert mock_build_service.called


def test_send_email_raises_gmail_send_error_on_http_error():
    from googleapiclient.errors import HttpError

    with patch("jobsearch.email.gmail_sender.build_credentials") as mock_build_creds, patch(
        "googleapiclient.discovery.build"
    ) as mock_build_service:
        mock_build_creds.return_value = Mock()
        mock_service = MagicMock()
        resp = Mock(status=403)
        mock_service.users.return_value.messages.return_value.send.return_value.execute.side_effect = (
            HttpError(resp, b'{"error": "forbidden"}', uri="https://gmail.googleapis.com/x")
        )
        mock_build_service.return_value = mock_service

        with pytest.raises(GmailSendError):
            send_email("a@example.com", "s", "<p>x</p>", auth_config=_auth_config())


def test_send_email_raises_gmail_send_error_on_unexpected_exception():
    with patch("jobsearch.email.gmail_sender.build_credentials") as mock_build_creds, patch(
        "googleapiclient.discovery.build"
    ) as mock_build_service:
        mock_build_creds.return_value = Mock()
        mock_build_service.side_effect = RuntimeError("connection reset")

        with pytest.raises(GmailSendError):
            send_email("a@example.com", "s", "<p>x</p>", auth_config=_auth_config())


def test_send_email_passes_from_address_into_raw_message():
    with patch("jobsearch.email.gmail_sender.build_credentials") as mock_build_creds, patch(
        "googleapiclient.discovery.build"
    ) as mock_build_service:
        mock_build_creds.return_value = Mock()
        mock_service = _mock_gmail_service()
        mock_build_service.return_value = mock_service

        send_email(
            "a@example.com", "s", "<p>x</p>", from_address="bot@example.com",
            auth_config=_auth_config(),
        )

    send_call = mock_service.users.return_value.messages.return_value.send
    _, send_kwargs = send_call.call_args
    raw = send_kwargs["body"]["raw"]
    decoded = base64.urlsafe_b64decode(raw.encode("utf-8"))
    message = email_lib.message_from_bytes(decoded)
    assert message["from"] == "bot@example.com"


# --- send_search_result_email (formatter + sender composition) -------------


def test_send_search_result_email_composes_subject_and_body():
    result = _result([_job()])
    email_config = EmailConfig(recipient_email="someone@example.com")

    with patch("jobsearch.email.gmail_sender.send_email") as mock_send_email:
        mock_send_email.return_value = {"id": "msg-1"}
        response = send_search_result_email(
            result,
            email_config=email_config,
            auth_config=_auth_config(),
            generated_at=NOW,
        )

    assert response == {"id": "msg-1"}
    mock_send_email.assert_called_once()
    _, kwargs = mock_send_email.call_args
    assert kwargs["to_address"] == "someone@example.com"
    assert "1 new match" in kwargs["subject"]
    assert "AI/ML Engineer" in kwargs["html_body"]


def test_send_search_result_email_applies_subject_prefix():
    result = _result([_job()])
    email_config = EmailConfig(recipient_email="someone@example.com", subject_prefix="[JobBot] ")

    with patch("jobsearch.email.gmail_sender.send_email") as mock_send_email:
        mock_send_email.return_value = {"id": "msg-1"}
        send_search_result_email(
            result, email_config=email_config, auth_config=_auth_config(), generated_at=NOW
        )

    _, kwargs = mock_send_email.call_args
    assert kwargs["subject"].startswith("[JobBot] ")


def test_send_search_result_email_uses_sender_email_override():
    result = _result([_job()])
    email_config = EmailConfig(recipient_email="someone@example.com", sender_email="bot@example.com")

    with patch("jobsearch.email.gmail_sender.send_email") as mock_send_email:
        mock_send_email.return_value = {"id": "msg-1"}
        send_search_result_email(
            result, email_config=email_config, auth_config=_auth_config(), generated_at=NOW
        )

    _, kwargs = mock_send_email.call_args
    assert kwargs["from_address"] == "bot@example.com"


def test_send_search_result_email_handles_zero_new_jobs():
    result = _result([])
    email_config = EmailConfig(recipient_email="someone@example.com")

    with patch("jobsearch.email.gmail_sender.send_email") as mock_send_email:
        mock_send_email.return_value = {"id": "msg-1"}
        send_search_result_email(
            result, email_config=email_config, auth_config=_auth_config(), generated_at=NOW
        )

    _, kwargs = mock_send_email.call_args
    assert "no new matches" in kwargs["subject"]
    assert "No new matching jobs" in kwargs["html_body"]


def test_send_search_result_email_never_marks_anything_as_seen():
    # There is no seen_store parameter at all on this function - marking
    # jobs as seen is entirely the orchestration layer's responsibility,
    # not this module's. This test documents that by construction: the
    # function signature has no way to touch a SeenJobStore.
    import inspect

    from jobsearch.email.gmail_sender import send_search_result_email as target

    params = inspect.signature(target).parameters
    assert "seen_store" not in params
    assert not any("seen" in name.lower() for name in params)
