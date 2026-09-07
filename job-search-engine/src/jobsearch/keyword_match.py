"""Shared word-boundary-aware keyword matching.

Plain substring search (`"rag" in text`) produces false positives for
short/ambiguous keywords - e.g. "rag" matching inside "average", "storage",
"leverage", or "paragraph". This module matches a keyword only when it
isn't immediately adjacent to another letter or digit, so short keywords
only match as whole words/phrases rather than as substrings of unrelated
words.
"""
from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=None)
def _compiled_pattern(keyword: str) -> re.Pattern:
    # Bounds are "not immediately preceded/followed by a letter or digit"
    # rather than regex \b, since \b doesn't reliably bound keywords that
    # start/end in punctuation (e.g. "c++", "c#", "next.js").
    return re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(keyword) + r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def contains_keyword(haystack: str, keyword: str) -> bool:
    """True if `keyword` appears in `haystack` as a whole word/phrase.

    Not a plain substring check: "rag" matches "RAG pipeline" but not
    "average", "storage", "leverage", or "paragraph". Multi-word phrases
    (e.g. "spring boot") and punctuation-containing keywords (e.g. "c++",
    "next.js") are matched literally, bounded only on the outside.
    """
    if not haystack or not keyword:
        return False
    return bool(_compiled_pattern(keyword).search(haystack))
