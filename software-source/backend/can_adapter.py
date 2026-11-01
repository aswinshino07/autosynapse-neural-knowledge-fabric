"""Optional read-only python-can input adapter. Never imported by the public demo path."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator


def read_frames(interface: str, channel: str, bitrate: int = 500_000) -> Iterator[dict]:
    try:
        import can
    except ImportError as exc:
        raise RuntimeError("Install python-can and the interface driver before enabling CAN input.") from exc
    # Explicit parameters are required; the demo never opens a physical bus by default.
    bus = can.Bus(interface=interface, channel=channel, bitrate=bitrate)
    try:
        for message in bus:
            yield {
                "timestamp": datetime.fromtimestamp(message.timestamp, tz=timezone.utc).isoformat(),
                "arbitration_id": int(message.arbitration_id),
                "is_extended_id": bool(message.is_extended_id),
                "data_hex": bytes(message.data).hex(),
                "source": f"CAN:{interface}:{channel}",
            }
    finally:
        bus.shutdown()
