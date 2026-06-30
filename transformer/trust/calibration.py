"""Self-calibrating trust.

The static SOURCE_WEIGHT table encodes our prior belief about how much to trust
each source. But the recruiters using the review console tell us, every time they
override a value, that a source got something wrong. This module turns that signal
into a *learned* weight: a source that is frequently corrected loses trust, damped
relative to how often it is actually relied on.

    override_rate(source)   = overrides(source) / exposure(source)
    calibrated_weight       = base * max(floor, 1 - damping * override_rate)

* ``overrides``  -- how many times this source's winning value was corrected.
* ``exposure``   -- how many fields this source currently wins (so a source that
                    wins a lot isn't unfairly punished for a few corrections).

Deterministic and bounded: weights never drop below ``floor`` x base, and with no
corrections the function returns the static defaults unchanged.
"""

from __future__ import annotations

from ..merge.confidence import SOURCE_WEIGHT

DAMPING = 0.6        # how hard corrections pull a weight down
FLOOR_FRACTION = 0.4  # a source never falls below 40% of its base weight


def _rate(overrides: dict, exposure: dict, source: str) -> float:
    return overrides.get(source, 0) / max(1, exposure.get(source, 0))


def calibrated_weights(overrides: dict, exposure: dict, damping: float = DAMPING) -> dict:
    """Return {source: learned_weight}. Static defaults when there are no overrides."""
    out = {}
    for source, base in SOURCE_WEIGHT.items():
        factor = max(FLOOR_FRACTION, 1.0 - damping * _rate(overrides, exposure, source))
        out[source] = round(base * factor, 4)
    return out


def report(overrides: dict, exposure: dict) -> list:
    """Human-facing calibration table: base vs learned weight per source."""
    weights = calibrated_weights(overrides, exposure)
    rows = []
    for source, base in SOURCE_WEIGHT.items():
        rows.append({
            "source": source,
            "base_weight": base,
            "calibrated_weight": weights[source],
            "overrides": overrides.get(source, 0),
            "exposure": exposure.get(source, 0),
            "override_rate": round(_rate(overrides, exposure, source), 4),
        })
    return rows
