"""USD token pricing for the models the incident graph calls.

Rates are USD per 1,000,000 tokens as ``(input, output)``. They are editable and
deliberately live in code so a run is reproducible; update them to match the
account's real contract before quoting a number. Cached input tokens are billed
at ``cached`` when given, otherwise at the normal input rate.

A model missing from the table contributes ``None`` to a sample's cost and is
surfaced in ``unpriced_models`` so the aggregate never hides a guess.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input_usd_per_1m: float
    output_usd_per_1m: float
    cached_input_usd_per_1m: float | None = None


# Keys must match ``settings.verification_model_name`` / ``report_model_name`` /
# ``qwen_vlm_model_name`` exactly (that is the value recorded on each ModelActivity).
# The current .env runs "gpt-5.6-luna" (verification + report) and "qwen3.7-plus"
# (VLM). "cached_input" here is the implicit/automatic cache-read rate; batch and
# explicit-cache rates are not used by the eval and are intentionally omitted.
MODEL_PRICES_USD_PER_1M: dict[str, ModelPrice] = {
    "gpt-5.6-luna": ModelPrice(0.20, 1.20, cached_input_usd_per_1m=0.02),
    "qwen3.7-plus": ModelPrice(0.03, 0.13, cached_input_usd_per_1m=0.006),
    "gpt-4o-mini": ModelPrice(0.15, 0.60, cached_input_usd_per_1m=0.075),
    # ESTIMATE — replace with the DashScope contract rate for qwen3-vl-flash.
    "qwen3-vl-flash": ModelPrice(0.05, 0.20),
}


def model_cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> float | None:
    """Return the USD cost of one call, or ``None`` when the model is unpriced."""
    price = MODEL_PRICES_USD_PER_1M.get(model)
    if price is None:
        return None
    billable_input = max(input_tokens - cached_tokens, 0)
    cached_rate = (
        price.cached_input_usd_per_1m
        if price.cached_input_usd_per_1m is not None
        else price.input_usd_per_1m
    )
    return (
        billable_input / 1_000_000 * price.input_usd_per_1m
        + cached_tokens / 1_000_000 * cached_rate
        + output_tokens / 1_000_000 * price.output_usd_per_1m
    )
