"""Beacon — emergency / high-priority alerts."""

from server.services.beacon.service import BeaconService
from server.services.beacon.store import BeaconStore

__all__ = ["BeaconService", "BeaconStore"]
