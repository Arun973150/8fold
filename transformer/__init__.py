"""Multi-source candidate data transformer.

Turns messy inputs from many sources into one clean, canonical profile per
candidate: fixed fields, normalized formats, deduplicated, with provenance and
confidence. Guiding rule: wrong-but-confident is worse than honestly-empty --
unknown values become null, never invented.
"""

__version__ = "0.1.0"
