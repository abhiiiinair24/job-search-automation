"""Gmail-based email delivery for job-search results.

Kept in three separate modules, each independently testable:

- formatter.py    Pure HTML rendering of a SearchResult - no Gmail/network
                  imports, so it's fully unit-testable without any Gmail
                  API access or credentials.
- gmail_auth.py    Loads OAuth2 credentials from environment variables and
                   builds a google-auth Credentials object. Never reads or
                   writes credential files.
- gmail_sender.py  Sends a message via the Gmail API (not SMTP). Depends
                   on gmail_auth.py and formatter.py, and is the only
                   module that makes real network calls.

None of these modules mark jobs as seen - that is the orchestration
layer's responsibility (send -> confirm -> mark_seen), not implemented
here yet.
"""
