"""Shared test fixtures.

The LLM résumé extractor auto-enables when GROQ_API_KEY is set. To keep the whole
suite deterministic and offline regardless of the developer's environment, disable
it for every test. Tests that exercise the LLM path opt in explicitly (use_llm=True)
and mock the model call.
"""

import pytest


@pytest.fixture(autouse=True)
def _disable_llm(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
