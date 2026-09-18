# Stalwart Mail Server adapter (Phase 4+)
#
# Preferred production Postbox backend. This repo currently uses a local
# SQLite mailbox (`server/services/mail`) so LoRa progressive MAIL_* ops
# can be developed without Docker/Pi.
#
# When wiring Stalwart:
# - Deploy via docker-compose (profile `mail`)
# - Map MAIL_STATUS/LIST/GET/SEND/REPLY through JMAP
# - Keep addresses like user@waypost (or configured domain)
# - Do not change Pocket progressive retrieval semantics

"""Stalwart adapter placeholder."""
