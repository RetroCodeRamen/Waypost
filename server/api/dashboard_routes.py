"""Home dashboard aggregate — friendly overview for the community portal."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Request

from server.api.deps import actor_username, get_current_user


def _sync_status(dispatch: Any, mail_status: dict[str, Any]) -> dict[str, Any]:
    """Cross-app "what's still waiting" — was Dispatch-only. Not a shared
    offline-sync subsystem (that's real scope of its own, see
    docs/priority-review.md #2/#4) — just an honest aggregate of the
    per-app pending counts each service already tracks."""
    base = dispatch.sync_status() if hasattr(dispatch, "sync_status") else {}
    outbox = int(mail_status.get("outbox") or 0)
    base = dict(base)
    base["pending_mail_outbox"] = outbox
    base["pending_total"] = int(base.get("pending_dispatch") or 0) + outbox
    return base


def build_dashboard_router() -> APIRouter:
    router = APIRouter(tags=["dashboard"])

    @router.get("/api/dashboard")
    def dashboard(
        request: Request,
        user=Depends(get_current_user),
        username: str = "aj",
    ):
        db = request.app.state.db
        dispatch = request.app.state.dispatch
        postbox = request.app.state.postbox
        commons = request.app.state.commons
        noticeboard = request.app.state.noticeboard
        beacon = request.app.state.beacon
        locker = request.app.state.locker
        rollcall = request.app.state.rollcall

        username = actor_username(request, user, username)
        db.ensure_user(username)
        rollcall.touch(username, via="wifi")

        mail = postbox.status(username)
        convs = dispatch.list_conversations(username)
        people = rollcall.list_people()
        commons_new = commons.recent_count(hours=24.0, exclude_author=username)
        notices_unread = noticeboard.count_unacked(username)
        active_beacon = beacon.get_active()
        locker_shared = locker.count_shared()

        new_messages = 0
        activity: list[dict[str, Any]] = []

        if active_beacon:
            activity.append(
                {
                    "actor": active_beacon.get("author"),
                    "text": active_beacon.get("title"),
                    "service": "Beacon",
                    "accent": "beacon",
                    "ts": active_beacon.get("created_at"),
                    "href": "/beacon.html",
                }
            )

        for conv in convs[:8]:
            last = conv.get("last_message")
            if not last:
                continue
            # Count peer messages as "new-ish" if recent (< 24h) — soft metric for cards
            age = time.time() - float(last.get("created_at") or 0)
            if age < 86400 and last.get("sender", "").lower() != username.lower():
                new_messages += 1
            activity.append(
                {
                    "actor": last.get("sender"),
                    "text": last.get("body"),
                    "service": "Dispatch",
                    "accent": "dispatch",
                    "ts": last.get("created_at"),
                    "href": "/dispatch.html",
                }
            )

        inbox = postbox.list_headers(username, folder="INBOX", limit=5)
        for msg in inbox:
            activity.append(
                {
                    "actor": msg.get("from"),
                    "text": msg.get("subject") or "(no subject)",
                    "service": "Postbox",
                    "accent": "postbox",
                    "ts": msg.get("created_at"),
                    "href": "/postbox.html",
                }
            )

        for post in commons.list_posts(limit=5):
            preview = post.get("title") or post.get("body") or ""
            if len(preview) > 120:
                preview = preview[:117] + "…"
            activity.append(
                {
                    "actor": post.get("author"),
                    "text": preview,
                    "service": "Commons",
                    "accent": "commons",
                    "ts": post.get("created_at"),
                    "href": "/commons.html",
                }
            )

        for notice in noticeboard.list_notices(active_only=True, limit=5):
            activity.append(
                {
                    "actor": notice.get("author"),
                    "text": notice.get("title"),
                    "service": "Noticeboard",
                    "accent": "notice",
                    "ts": notice.get("created_at"),
                    "href": "/noticeboard.html",
                }
            )

        for item in locker.list_files(scope="shared", viewer=username, limit=5):
            activity.append(
                {
                    "actor": item.get("owner"),
                    "text": item.get("filename"),
                    "service": "Locker",
                    "accent": "locker",
                    "ts": item.get("created_at"),
                    "href": "/locker.html",
                }
            )

        activity.sort(key=lambda a: float(a.get("ts") or 0), reverse=True)
        activity = activity[:10]

        online = [
            p
            for p in people
            if p
            and (
                "wifi" in (p.get("reachability") or "")
                or "lora" in (p.get("reachability") or "")
            )
        ]

        health = {
            "status": "ok",
            "transport": getattr(request.app.state.settings, "waypost_transport", "mock"),
            "ssid": getattr(request.app.state.settings, "waypost_ssid", "WAYPOST"),
        }

        return {
            "user": {
                "username": username,
                "display_name": (db.get_user_by_username(username) or {}).get(
                    "display_name", username
                ),
            },
            "cards": {
                "dispatch": {"value": new_messages, "label": "New Messages", "service": "Dispatch"},
                "postbox": {
                    "value": mail.get("unread", 0),
                    "label": "Unread Emails",
                    "service": "Postbox",
                },
                "commons": {
                    "value": commons_new,
                    "label": "New Posts",
                    "service": "Commons",
                },
                "noticeboard": {
                    "value": notices_unread,
                    "label": "Unread Notices",
                    "service": "Noticeboard",
                },
            },
            "activity": activity,
            "active_beacon": active_beacon,
            "network": {
                "station": "Online",
                "outposts_online": 0,
                "outposts_total": 0,
                "users_online": len(online),
                "users_total": len(people),
                "transport": health["transport"],
                "ssid": health["ssid"],
                "note": "Outpost counts appear when Waylink hardware is connected.",
            },
            "sync": _sync_status(dispatch, mail),
            "quick_links": [
                {"label": "Locker", "href": "/locker.html", "icon": "locker"},
                {"label": "Beacon", "href": "/beacon.html", "icon": "beacon"},
                {"label": "Commons", "href": "/commons.html", "icon": "commons"},
                {"label": "Signal", "href": "/signal.html", "icon": "signal"},
            ],
            "locker_shared": locker_shared,
        }

    return router
