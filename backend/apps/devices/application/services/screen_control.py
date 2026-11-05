"""Validation for consented remote-screen control intents.

Control is an elevation of an existing live screen-view session. The paired
device must explicitly approve each grant; these helpers only sanitize the
gesture payload that the viewer may send *after* that approval. They do not
authorize anything by themselves.

Supported actions (gestures / navigation only — no keylogging, clipboard,
or password capture):
  tap, long_press, swipe, back, home, recents
Coordinates are normalized 0..1 relative to the streamed frame.
"""

from __future__ import annotations

from typing import Any

ALLOWED_ACTIONS = frozenset(
    {"tap", "long_press", "swipe", "back", "home", "recents"}
)
POINT_ACTIONS = frozenset({"tap", "long_press"})
DEFAULT_DURATION_MS = {
    "tap": 50,
    "long_press": 600,
    "swipe": 250,
}
MIN_DURATION_MS = 20
MAX_DURATION_MS = 1500


def _is_norm(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return 0.0 <= number <= 1.0


def _clamp_duration(value: Any, default: int) -> int:
    try:
        duration = int(value)
    except (TypeError, ValueError):
        return default
    return max(MIN_DURATION_MS, min(MAX_DURATION_MS, duration))


def validate_control_intent(data: Any) -> dict | None:
    """Return a cleaned intent dict, or None if the payload is rejected."""
    if not isinstance(data, dict):
        return None
    action = data.get("action")
    if action not in ALLOWED_ACTIONS:
        return None

    cleaned: dict[str, Any] = {"action": action}
    seq = data.get("seq")
    if seq is not None:
        try:
            cleaned["seq"] = int(seq)
        except (TypeError, ValueError):
            return None

    if action in POINT_ACTIONS:
        if not _is_norm(data.get("x")) or not _is_norm(data.get("y")):
            return None
        cleaned["x"] = round(float(data["x"]), 4)
        cleaned["y"] = round(float(data["y"]), 4)
        cleaned["duration_ms"] = _clamp_duration(
            data.get("duration_ms"), DEFAULT_DURATION_MS[action]
        )
        return cleaned

    if action == "swipe":
        if not all(
            _is_norm(data.get(key)) for key in ("x", "y", "x2", "y2")
        ):
            return None
        cleaned["x"] = round(float(data["x"]), 4)
        cleaned["y"] = round(float(data["y"]), 4)
        cleaned["x2"] = round(float(data["x2"]), 4)
        cleaned["y2"] = round(float(data["y2"]), 4)
        cleaned["duration_ms"] = _clamp_duration(
            data.get("duration_ms"), DEFAULT_DURATION_MS["swipe"]
        )
        return cleaned

    # back / home / recents — no coordinates
    return cleaned
