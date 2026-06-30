"""Trust layer.

The engine's job is to produce a profile; the trust layer's job is to say how
much you should believe it and why. It reuses data the resolver already computed
(per-field decisions with winners AND losers) to deliver three things:

* explain  -- a field-level audit trail of every merge decision
* report   -- per-candidate data-quality + conflict report, plus a batch rollup
* gating   -- route low-confidence / incomplete profiles to a review queue

This is the embodiment of "wrong-but-confident is worse than honestly-empty":
nothing is hidden, and a shaky profile is flagged rather than trusted silently.
"""

from .build import build_trust, quality_report, explain  # noqa: F401
