"""Normalizers: pure, total functions.

Every function here takes a raw value and returns a normalized value or ``None``.
None of them ever raise -- garbage in yields ``None`` out, so a single malformed
field can never crash a run. This is what makes the pipeline robust and is the
mechanical embodiment of "honestly-empty beats wrong-but-confident".
"""

from . import phones, dates, location, skills, emails  # noqa: F401
