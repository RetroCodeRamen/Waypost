"""M2e — RNode LoRa interface config + Signal link security (no RNS needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.transports import create_transport
from server.transports.reticulum import RNodeRadio, _default_config


def test_rnode_config_written(tmp_path: Path):
    radio = RNodeRadio(port="/dev/ttyACM0", frequency=868_000_000, txpower=10)
    _default_config(tmp_path, interface="rnode", rnode=radio)
    cfg = (tmp_path / "config").read_text()
    assert "type = RNodeInterface" in cfg
    assert "port = /dev/ttyACM0" in cfg
    assert "frequency = 868000000" in cfg
    assert "bandwidth = 125000" in cfg
    assert "txpower = 10" in cfg
    assert "spreadingfactor = 8" in cfg
    assert "codingrate = 5" in cfg
    assert "AutoInterface" not in cfg


def test_existing_config_not_overwritten(tmp_path: Path):
    (tmp_path / "config").write_text("# hand-tuned\n")
    _default_config(tmp_path, interface="rnode")
    assert (tmp_path / "config").read_text() == "# hand-tuned\n"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"frequency": 1_000},
        {"bandwidth": 100_000},
        {"txpower": 30},
        {"spreadingfactor": 13},
        {"codingrate": 4},
    ],
)
def test_rnode_rejects_bad_params(kwargs):
    with pytest.raises(ValueError):
        RNodeRadio(**kwargs)


def test_create_transport_rnode_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WAYPOST_RNS_INTERFACE", "rnode")
    monkeypatch.setenv("WAYPOST_RNS_CONFIG", str(tmp_path))
    monkeypatch.setenv("WAYPOST_RNS_FREQUENCY", "915500000")
    monkeypatch.setenv("WAYPOST_RNS_SF", "10")
    t = create_transport("reticulum", device_path="/dev/ttyUSB3")
    assert t.interface == "rnode"
    assert t.rnode.port == "/dev/ttyUSB3"
    assert t.rnode.frequency == 915_500_000
    assert t.rnode.spreadingfactor == 10
