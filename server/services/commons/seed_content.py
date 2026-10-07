"""Default Commons posts — a starter timeline for new Stations.

Fixed IDs keep seeding idempotent. Timestamps are relative offsets (seconds
before boot) so the feed looks lived-in without pinning absolute dates.
"""

from __future__ import annotations

# (id, author, title, body, age_seconds) — older posts have larger age
SEED_POSTS: list[tuple[str, str, str, str, float]] = [
    (
        "seed-commons-welcome",
        "station",
        "",
        "Welcome to Commons — the camp's shared timeline. Every signed-in member can post here; everyone sees the same feed, newest first. Share trail conditions, meal plans, gear finds, or a quick hello.",
        86400 * 7,
    ),
    (
        "seed-commons-fieldbook",
        "aj",
        "",
        "Fieldbook is live with first aid, shelter, plants, wayfinding, and kayaking pages. Worth a read before the weekend paddle — especially the cold-water notes.",
        86400 * 5 + 3600,
    ),
    (
        "seed-commons-trail",
        "bob",
        "",
        "North loop is muddy after last night's rain. Stream crossing at mile 2 is knee-deep but passable with poles. Will update if it rises.",
        86400 * 3 + 7200,
    ),
    (
        "seed-commons-meal",
        "aj",
        "",
        "Community dinner Saturday 6pm at the pavilion. Bring a side if you can — main pot is chili. Reply here if you're vegetarian so we can adjust.",
        86400 * 2,
    ),
    (
        "seed-commons-gear",
        "bob",
        "",
        "Extra MSR fuel canister in the gear locker if anyone needs it. Label says half full. Please log when you take it.",
        86400 + 18000,
    ),
    (
        "seed-commons-stargazing",
        "aj",
        "",
        "Clear sky forecast tonight. Moon sets around 10 — good window for Orion. Meet at the dock if anyone wants a quick constellations tour (no telescope, just eyes).",
        43200,
    ),
    (
        "seed-commons-water",
        "station",
        "",
        "Reminder: filter or boil backcountry water even when it looks clear. Fieldbook page water-purification has the camp's preferred methods.",
        14400,
    ),
    (
        "seed-commons-hello",
        "bob",
        "",
        "Morning all — coffee is on at the Outpost corkboard side table. Post here when you're heading to the river; looking for a shuttle buddy.",
        3600,
    ),
]
