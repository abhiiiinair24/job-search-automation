import pytest

from jobsearch.filters.sponsorship import annotate_sponsorship, detect_sponsorship
from jobsearch.models import SponsorshipStatus


@pytest.mark.parametrize(
    "text,expected_status",
    [
        # --- originally-supported phrasing -----------------------------
        ("We are unable to sponsor visas for this role.", SponsorshipStatus.NOT_AVAILABLE),
        ("No visa sponsorship is provided for this position.", SponsorshipStatus.NOT_AVAILABLE),
        ("This role does not offer visa sponsorship.", SponsorshipStatus.NOT_AVAILABLE),
        ("Visa sponsorship is available for qualified candidates.", SponsorshipStatus.AVAILABLE),
        ("We will sponsor H-1B for this role.", SponsorshipStatus.AVAILABLE),
        ("Open to sponsoring international candidates.", SponsorshipStatus.AVAILABLE),
        ("This is a great backend role with Kafka and AWS.", SponsorshipStatus.UNKNOWN),
        ("", SponsorshipStatus.UNKNOWN),
        # --- new variants from this refinement pass ---------------------
        ("We offer immigration sponsorship for this role.", SponsorshipStatus.AVAILABLE),
        ("H-1B sponsorship available for the right candidate.", SponsorshipStatus.AVAILABLE),
        ("Sponsorship is not available for this position.", SponsorshipStatus.NOT_AVAILABLE),
        (
            "Candidates must be eligible to work without sponsorship; "
            "not eligible for immigration sponsorship.",
            SponsorshipStatus.NOT_AVAILABLE,
        ),
        ("We do not sponsor employment visas of any kind.", SponsorshipStatus.NOT_AVAILABLE),
        ("Unfortunately we cannot provide sponsorship at this time.", SponsorshipStatus.NOT_AVAILABLE),
        (
            "This position will not sponsor now or in the future.",
            SponsorshipStatus.NOT_AVAILABLE,
        ),
        # --- unknown: bare mention with no available/unavailable verb ---
        ("Please indicate your visa sponsorship needs in the application.", SponsorshipStatus.UNKNOWN),
        ("Competitive salary and great benefits await the right candidate.", SponsorshipStatus.UNKNOWN),
    ],
)
def test_detect_sponsorship_status(text, expected_status):
    status, _evidence = detect_sponsorship(text)
    assert status == expected_status


def test_detect_sponsorship_returns_evidence_text_when_matched():
    status, evidence = detect_sponsorship("Sorry, we cannot sponsor visas for this position.")
    assert status == SponsorshipStatus.NOT_AVAILABLE
    assert evidence is not None
    assert "sponsor" in evidence.lower()


def test_detect_sponsorship_no_evidence_when_unknown():
    status, evidence = detect_sponsorship("Great team, great mission.")
    assert status == SponsorshipStatus.UNKNOWN
    assert evidence is None


def test_annotate_sponsorship_sets_fields_on_job(make_job):
    job = make_job(description="We do not provide visa sponsorship for this role.")
    annotate_sponsorship(job)
    assert job.sponsorship_status == SponsorshipStatus.NOT_AVAILABLE
    assert job.sponsorship_evidence is not None


def test_annotate_sponsorship_available_case(make_job):
    job = make_job(description="We offer H-1B sponsorship for exceptional candidates.")
    annotate_sponsorship(job)
    assert job.sponsorship_status == SponsorshipStatus.AVAILABLE


def test_annotate_sponsorship_unknown_case(make_job):
    job = make_job(description="Join our fast-growing engineering team.")
    annotate_sponsorship(job)
    assert job.sponsorship_status == SponsorshipStatus.UNKNOWN
    assert job.sponsorship_evidence is None
