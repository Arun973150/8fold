"""LLM-assisted extraction (optional).

Used only for what the deterministic heuristics can't reach -- structured
experience/education and skills buried in prose. It is strictly *extractive*: the
model is instructed to copy, not infer, and every value it returns is verified to
actually appear in the source text before we keep it. Anything ungrounded is
dropped. If no GROQ_API_KEY is configured (or the call fails), extraction returns
None and the caller falls back to the heuristic parser -- the LLM never becomes a
hard dependency and never blocks a run.
"""

from .llm_resume import extract, is_enabled  # noqa: F401
