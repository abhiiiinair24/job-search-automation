import pytest

from jobsearch.filters.location import is_us_based


@pytest.mark.parametrize(
    "location,expected",
    [
        ("San Francisco, CA", True),
        ("New York, NY", True),
        ("Remote - US", True),
        ("Remote (US)", True),
        ("Remote", True),
        ("United States", True),
        ("Austin, TX / Remote", True),
        ("Bangalore, India", False),
        ("London, UK", False),
        ("Toronto, Canada", False),
        ("Remote - EMEA", False),
        ("Berlin, Germany", False),
    ],
)
def test_is_us_based(make_job, location, expected):
    job = make_job(location=location)
    assert is_us_based(job) is expected
