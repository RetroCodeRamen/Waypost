"""Fieldbook protocol constants — see docs/protocol.md "Fieldbook"."""

OP_WIKI_SEARCH = "WIKI_SEARCH"
OP_WIKI_GET = "WIKI_GET"
OP_WIKI_UPDATE = "WIKI_UPDATE"
OP_WIKI_CREATE = "WIKI_CREATE"

MAX_SLUG = 64
MAX_TITLE = 120
MAX_BODY = 64_000
MAX_SUMMARY = 200

# Compact search results: enough to decide which page to fetch, not the page.
SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 50
SNIPPET_CHARS = 120
