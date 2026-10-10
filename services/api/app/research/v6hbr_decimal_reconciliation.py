"""Exact Decimal aggregation for modeled trade accounting.

Do not use default 28-digit context summation for post-hoc cohort totals.
Addition order differs across chronologically ordered portfolios vs lane-grouped
attribution; finite-precision addition can therefore make correct accounts
appear irreconcilable.

This helper retains the entire supplied Decimal coefficient and exponent and
adds inputs without rounding. It does NOT change cost assumptions, individual
fills or economic outcomes. The caller still compares totals with strict ==.
"""
from __future__ import annotations

from decimal import Decimal as D, InvalidOperation


def exact_reference_sum(values) -> D:
    numbers = []
    for raw in values:
        if isinstance(raw, bool):
            raise ValueError("Boolean cannot be a reference accounting amount")
        try:
            value = D(str(raw))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("Invalid reference accounting amount") from exc
        if not value.is_finite():
            raise ValueError("Nonfinite reference accounting amount")
        numbers.append(value)
    if not numbers:
        return D(0)

    # Form an exact base-10 integer sum at the smallest fractional exponent.
    # Construct a Decimal from its integer coefficient tuple so even the final
    # result is not rounded by the ambient decimal context.
    common_exp = min(value.as_tuple().exponent for value in numbers)
    total = 0
    for value in numbers:
        digits = value.as_tuple()
        coefficient = int("".join(map(str, digits.digits)))
        if digits.sign:
            coefficient = -coefficient
        total += coefficient * (10 ** (digits.exponent - common_exp))
    if total == 0:
        return D(0)
    output_digits = tuple(int(char) for char in str(abs(total)))
    return D((1 if total < 0 else 0, output_digits, common_exp))
