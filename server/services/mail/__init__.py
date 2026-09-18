"""Postbox / mail service package."""

from server.services.mail.service import PostboxService
from server.services.mail.store import MailStore, addr_for_user

__all__ = ["PostboxService", "MailStore", "addr_for_user"]
