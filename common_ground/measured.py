"""Everything the key-day probe fixes, with the documented defaults it starts from.

No response data lives here. A name stays in UNVERIFIED until the probe has measured it, and a live
source refuses to run while that set is not empty. The probe prints a block that replaces the lines
below and empties the set; nothing else in the package may hard-code any of these.
"""
from __future__ import annotations

from .refusal import Refusal

# P1: the `types` values /search should be asked for, and whether they go as one comma-joined
# value or as a repeated parameter. Never `person`.
FAVOURITE_TYPES = (
    "urn:entity:place",
    "urn:entity:artist",
    "urn:entity:movie",
    "urn:entity:tv_show",
    "urn:entity:book",
    "urn:entity:brand",
    "urn:entity:podcast",
    "urn:entity:video_game",
)
TYPES_FORM = "comma"

# P3, P4: the parameter that carried each condition and changed the result. None means the probe
# found the condition ignored, so it is neither sent nor offered.
CONDITIONS_OK = {
    "location": "filter.location.query",
    "day": "filter.hours",
    "price": "filter.price_level",
    "kind": "filter.tags",
}

# P3: the sample group's city, with the second the probe tries when the first returns under 30 places.
SAMPLE_CITY = "New York City"
FALLBACK_CITY = "Los Angeles"

# P5: places asked of the group search and sent to each ranking (50, or 25 if that is the most a
# ranking call accepted).
LONG_LIST = 50

# P3, P5: where a place's affinity and explainability sit inside a result, and where the aggregate
# explainability sits in the response. None means absent (T4, T5).
AFFINITY_PATH = ("query", "affinity")
EXPLAIN_PATH = ("query", "explainability")
LEAN_PATH = ("query", "explainability")

# P5: smallest and largest affinity seen per member, to one decimal; None until measured.
AFFINITY_SCALE = None

# P1 to P5: the readers in records.py that the probe saw accept a real response.
RESPONSE_SHAPES = frozenset()

UNVERIFIED = frozenset({
    "FAVOURITE_TYPES",
    "TYPES_FORM",
    "CONDITIONS_OK",
    "SAMPLE_CITY",
    "LONG_LIST",
    "AFFINITY_PATH",
    "EXPLAIN_PATH",
    "LEAN_PATH",
    "AFFINITY_SCALE",
    "RESPONSE_SHAPES",
})


def require_verified() -> None:
    """A live source calls this before it spends a request, and only the probe is exempt."""
    if UNVERIFIED:
        raise Refusal("shapes_unverified", ", ".join(sorted(UNVERIFIED)))
