import pytest

from jobsearch.keyword_match import contains_keyword


@pytest.mark.parametrize(
    "haystack,keyword,expected",
    [
        # The bug this module fixes: "rag" as a plain substring incorrectly
        # matched inside ordinary words.
        ("this includes an average calculation", "rag", False),
        ("we store files in cold storage", "rag", False),
        ("please read the paragraph below", "rag", False),
        ("this role will leverage your skills", "rag", False),
        ("we build RAG pipelines with LangChain", "rag", True),
        ("RAG-based retrieval is core to this role", "rag", True),
        # Case-insensitivity.
        ("Experience with rag pipelines", "RAG", True),
        # Substring risk for another short keyword: "sql" inside "mysql".
        ("we use MySQL as our primary datastore", "sql", False),
        ("we use SQL extensively", "sql", True),
        # Punctuation-containing keywords should still match as whole units.
        ("experience with Next.js required", "next.js", True),
        ("experience with C++ required", "c++", True),
        # Multi-word phrases.
        ("built with Spring Boot and Kafka", "spring boot", True),
        ("built with Spring MVC", "spring boot", False),
        # Empty inputs never match.
        ("", "rag", False),
        ("some text", "", False),
    ],
)
def test_contains_keyword(haystack, keyword, expected):
    assert contains_keyword(haystack, keyword) is expected


def test_contains_keyword_at_start_and_end_of_string():
    assert contains_keyword("rag pipelines are great", "rag") is True
    assert contains_keyword("great pipelines use rag", "rag") is True


def test_contains_keyword_does_not_match_within_longer_word_at_boundary():
    # "rag" immediately followed by a letter shouldn't count as a match.
    assert contains_keyword("ragged edges", "rag") is False
