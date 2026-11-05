"""Exact census ID validation before any lossy floating-point parsing.

CSV readers must retain the configured ID column as text until this validation.
Already floating-point API values can only be checked as supplied: precision
discarded by a caller before this boundary cannot be recovered.
"""
from decimal import Decimal, InvalidOperation
import numbers
import re


MAX_ZONE_ID = 2 ** 53
NUMERIC_ID = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def exact_zone_ids(values):
    """Return exact integer IDs, accepting integral decimal/scientific spelling."""
    result = []
    for value in values:
        if isinstance(value, bool):
            raise ValueError("Census zone IDs must be exactly representable integers, not booleans")
        if isinstance(value, numbers.Integral):
            number = int(value)
            if not -MAX_ZONE_ID <= number <= MAX_ZONE_ID:
                raise ValueError("Census zone IDs must be exactly representable integers within ±2**53")
            result.append(number)
            continue
        if isinstance(value, numbers.Real):
            # NumPy float32/extended-real shortest display is not necessarily
            # its exact numeric value. Do not parse str(value) or downcast it.
            if not -MAX_ZONE_ID <= value <= MAX_ZONE_ID:
                raise ValueError("Census zone IDs must be finite exactly representable integers within ±2**53")
            number = int(value)
            if value != number:
                raise ValueError("Census zone IDs must be finite exactly representable integers")
            result.append(number)
            continue
        if not isinstance(value, (str, Decimal)):
            raise ValueError("Census zone IDs must be real-valued exactly representable integers")
        if isinstance(value, str) and not NUMERIC_ID.fullmatch(value.strip()):
            raise ValueError("Census zone IDs must be numeric exactly representable integers")
        try:
            decimal = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, OverflowError) as exc:
            raise ValueError("Census zone IDs must be finite exactly representable integers") from exc
        if (not decimal.is_finite() or decimal < -MAX_ZONE_ID or decimal > MAX_ZONE_ID
                or decimal != decimal.to_integral_value()):
            raise ValueError("Census zone IDs must be finite exactly representable integers within ±2**53")
        result.append(int(decimal))
    return result
