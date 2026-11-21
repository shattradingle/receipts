from __future__ import annotations

import pytest

from receipts.pipeline import expand_queries


def test_depth_one_is_the_question():
    question = "why do AI coding agents waste context window"
    assert expand_queries(question, 1) == [question]


def test_depth_two_gives_three_variants():
    question = "why do AI coding agents waste context window"
    variants = expand_queries(question, 2)
    assert len(variants) == 3
    assert variants[0] == '"why do AI coding agents waste context window"'
    assert "why" not in variants[1].split()
    assert "the" not in variants[1].split()
    assert variants[1] == "ai coding agents waste context window"
    assert variants[2] == "ai coding agents"


def test_expansion_is_deterministic():
    question = "what breaks when you self-host a search index"
    assert expand_queries(question, 3) == expand_queries(question, 3)


def test_expansion_dedupes_variants():
    variants = expand_queries("context window", 2)
    assert len(variants) == len(set(variants))


def test_empty_question_raises():
    with pytest.raises(ValueError):
        expand_queries("   ", 1)


def test_depth_three_uses_same_queries_as_two():
    question = "is remote work bad for junior engineers"
    assert expand_queries(question, 3) == expand_queries(question, 2)
