"""Cost estimates use the rates for the configured deployment name."""

from __future__ import annotations

import pytest

from football_insights.agent.pricing import estimate


def test_gpt_5_mini_deployment_has_nonzero_cost_estimate() -> None:
    # 800 uncached input, 200 cached input, and 100 output tokens.
    # ($0.25/M * 800) + ($0.025/M * 200) + ($2.00/M * 100) = $0.000405.
    assert estimate("gpt-5-mini-1", input_tokens=1000, cached_tokens=200, output_tokens=100) == pytest.approx(
        0.000405
    )
