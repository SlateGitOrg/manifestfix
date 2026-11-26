"""Optional check against a real OpenAI-compatible endpoint. Skipped unless MANIFESTFIX_LIVE=1."""

from __future__ import annotations

import os

import pytest

from manifestfix.generator import generate_dataset
from manifestfix.model import OpenAICompatModel
from manifestfix.repair import CONFIGS, Pipeline

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("MANIFESTFIX_LIVE") != "1", reason="set MANIFESTFIX_LIVE=1"),
]


def test_live_model_extracts_a_clean_document():
    doc = generate_dataset(seed=7, count=30).docs[0]
    outcome = Pipeline(OpenAICompatModel(), CONFIGS["rules+targeted"]).run(doc.text)
    assert outcome.calls <= 3
    assert outcome.status in ("accepted", "review")
