# Fieldbook — editable community knowledge

**Status:** v1 built 2026-09-24 (`server/services/fieldbook/`, `server/api/fieldbook_routes.py`,
`web/portal/fieldbook.html`). Waylink ops in [protocol.md](protocol.md#fieldbook-fieldbook--m5--2026-09-24-sim).

Fieldbook is the wiki: pages people edit together, with every revision kept. It is **not**
Archive (imported reference content, read-only) — see [naming.md](naming.md).

## What v1 is

- **Pages** keyed by a slug (`well-maintenance`), with a title and a plain-text/Markdown-ish
  body. Slugs are lowercase letters, digits and dashes; the portal derives one from the title.
- **Revisions.** Every save appends a `wiki_revisions` row (body, author, summary, time) and
  bumps `wiki_pages.revision`. Nothing is ever rewritten in place. History and any past
  revision are readable; any two revisions can be diffed (unified diff).
- **Sections.** A body splits on ATX headings (`# Location`, `## Pump`); section 0 is any
  preamble before the first heading. Sections are addressable by index or heading text and
  concatenate back to the exact body, so a Pocket can fetch or replace one without the rest.
- **Search** is a case-insensitive substring match over title and body; results are headers
  plus a ~120-char snippet, never bodies. Title hits sort first.
- **Author** comes from the session over HTTP and from the device binding over Waylink —
  never from the payload.

## The progressive path

Bandwidth philosophy ([architecture.md](architecture.md#bandwidth-philosophy)): never send a
payload because it exists. Fieldbook's ladder over LoRa:

```text
WIKI_SEARCH {q}                       → compact hits (slug, title, revision, snippet)
WIKI_GET {slug, outline:true}         → title, revision, [heading, level, size] per section
WIKI_GET {slug, section:"Pump"}       → just that section's text
WIKI_GET {slug, since:N}              → unchanged:true, or a unified diff N → current
WIKI_UPDATE {slug, base_revision, section, section_text}
                                      → new revision, compact ack (no body echoed)
```

Full-page `WIKI_GET {slug}` exists and the portal uses it over Wi‑Fi; a Pocket should prefer
the rungs above.

## Conflicts

An edit carries the `base_revision` it was made against. If that is no longer current:

- **HTTP:** `409` with `{error: "revision_conflict", current: <full page>}`. The portal keeps
  the editor's text, shows who saved what and when, offers "Show what changed" (diff from the
  editor's base to the current revision) and "Load their version" (rebase the editor onto the
  current revision — the user re-applies their change and saves again).
- **Waylink:** `ERROR` reply `{error: "revision_conflict", current_revision, updated_by,
  outline}` — outline rather than body, so the Pocket can decide which section to re-fetch
  with `since`/`section` before retrying.

A save that changes nothing (same title and body) returns the current page and does **not**
create a revision. A page can never lose its history; there is no delete in v1.

## Storage

```text
wiki_pages     slug PK, title, body (current), revision, created_by/at, updated_by/at
wiki_revisions (slug, revision) PK, title, body, author, summary, created_at
```

Current body lives on the page row so reads never join; revisions are the audit trail and
the diff source.

## Deferred (deliberately)

- **Offline edit queueing on Pocket** — M5's "offline edits via shared sync" criterion. The
  primitive it needs (base-revision conflict detection) is here; the queue itself belongs to
  the shared offline-sync subsystem ([offline-sync.md](offline-sync.md)) that only Dispatch has
  adopted so far. Fieldbook should adopt those states, not grow a private queue.
- **Group-scoped pages** — same injected `is_group_member` pattern Locker uses
  ([groups-and-permissions.md](groups-and-permissions.md)); nothing in M5 asked for it yet.
- **Full-text search (FTS5)** — LIKE is fine at community-wiki scale; swap the store's
  `search()` when it isn't.
- **Rich Markdown** — the portal renders headings, paragraphs, `-` lists and fenced code.
  Links, tables and images wait until someone needs them.
- **Page rename / delete / redirects** — slugs are permanent in v1.
- **BookStack adapter** — the roadmap's "later" option; the revision model here is
  compatible with importing from one if that ever happens.
