"""Offline tests for parse_score: a verdict must be stated, never inferred.

Regression guard for the 2026-09-11 finding (STATUS.md): reasoning judge models
truncate mid-thought at a small max_tokens, emit no verdict, and the old
"first float anywhere" fallback then lifted the 1.0 out of the restated rubric
and scored a garbage response as perfect. Unscored is the honest outcome.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import nvidia_judge as nj  # noqa: E402


def test_explicit_score_marker_wins():
    assert nj.parse_score("score: 0.85") == 0.85
    assert nj.parse_score('SCORE = 1.0') == 1.0
    assert nj.parse_score("Score: 0.0") == 0.0


def test_out_of_one_form():
    assert nj.parse_score("0.4/1.0") == 0.4
    assert nj.parse_score("I give it 0.75 / 1") == 0.75


def test_bare_float_from_terse_reply():
    assert nj.parse_score("0.6") == 0.6
    assert nj.parse_score("  1.0\n") == 1.0


def test_terse_reply_takes_the_last_float_not_the_first():
    # A verdict closes a reply; a restated scale opens one.
    assert nj.parse_score("0.0 to 1.0 scale: 0.3") == 0.3


def test_truncated_reasoning_is_unscored_not_guessed():
    # The exact shape that scored garbage 1.0: a chain of thought that restates
    # the rubric, hits the token ceiling, and never reaches a verdict.
    truncated = (
        'We need to evaluate the model response. The rubric says "Award 1.0 if '
        "the summary is accurate and under 40 words. Award 0.5 if accurate but "
        "too long. Award 0.0 if it invents facts.\" Since we cannot verify the "
        "source text here, we might assume it is accurate, but that risks giving "
        "credit incorrectly. Typically the benchmark supplies the source, however "
        "in this case we only have the response, so the evaluator must decide "
        "whether"
    )
    assert nj.parse_score(truncated) is None


def test_long_prose_with_explicit_score_still_parses():
    # Hardening must not reject a verbose judge that DOES state its verdict.
    verbose = ("The response covers what happened, why, and the fix, in three "
               "sentences with no jargon, so it meets every element of the "
               "rubric cleanly and reads well for a non-technical reader. "
               "It is accurate and appropriately concise throughout. score: 0.9")
    assert len(verbose) > nj._PROSE_CHARS
    assert nj.parse_score(verbose) == 0.9


def test_no_number_at_all_is_unscored():
    assert nj.parse_score("I cannot evaluate this.") is None
    assert nj.parse_score("") is None
