"""Optional CARLA snapshot adapter. Requires the CARLA Python API and a local CARLA server."""
from __future__ import annotations


def vehicle_snapshot(host: str = "127.0.0.1", port: int = 2000, timeout_s: float = 2.0) -> dict:
    try:
        import carla
    except ImportError as exc:
        raise RuntimeError("Install the CARLA Python API that matches your simulator version.") from exc
    client = carla.Client(host, port)
    client.set_timeout(timeout_s)
    world = client.get_world()
    vehicles = world.get_actors().filter("vehicle.*")
    return {
        "source": "CARLA",
        "frame": int(world.get_snapshot().frame),
        "vehicles": [{"actor_id": int(v.id), "type": v.type_id,
                       "speed_mps": round(v.get_velocity().length(), 3),
                       "location": {"x": round(v.get_location().x, 2), "y": round(v.get_location().y, 2),
                                    "z": round(v.get_location().z, 2)}} for v in vehicles],
    }
