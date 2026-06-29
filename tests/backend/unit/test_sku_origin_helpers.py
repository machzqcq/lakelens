"""Unit tests for routers.sku_origin pure helpers.

The router is mostly SQL aggregation (covered at the integration layer).
The two pieces that have non-trivial pure logic are:
- `_top_pct`: handles empty list, all-zeros, mixed Decimals
- `_bucket_index`: maps a date into a sparkline bucket [0, n_buckets)
- `_default_window`: defaults to "last 90 days" when not provided
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from routers.sku_origin import _bucket_index, _default_window, _top_pct


class TestTopPct:
    def test_empty_returns_none(self):
        assert _top_pct([], 1) is None

    def test_all_zero_returns_none(self):
        assert _top_pct([Decimal(0), Decimal(0), Decimal(0)], 1) is None

    def test_top_one_pct(self):
        vals = [Decimal(80), Decimal(15), Decimal(5)]
        assert _top_pct(vals, 1) == pytest.approx(80.0)

    def test_top_three_pct(self):
        vals = [Decimal(50), Decimal(30), Decimal(15), Decimal(5)]
        assert _top_pct(vals, 3) == pytest.approx(95.0)

    def test_n_larger_than_list(self):
        vals = [Decimal(70), Decimal(30)]
        # Asking for top-5 with 2 values should give 100%.
        assert _top_pct(vals, 5) == pytest.approx(100.0)

    def test_decimal_does_not_break_arithmetic(self):
        # Regression: this used to throw TypeError because Decimal * float was
        # attempted. _top_pct now coerces to float internally.
        vals = [Decimal("123.456"), Decimal("0.001")]
        assert isinstance(_top_pct(vals, 1), float)


class TestBucketIndex:
    def test_clamps_to_zero_for_before_start(self):
        start = date(2026, 1, 1)
        assert _bucket_index(date(2025, 12, 31), start, 1.0, 10) == 0

    def test_first_day_is_bucket_zero(self):
        start = date(2026, 1, 1)
        # 30 days, 30 buckets => 1 day per bucket
        assert _bucket_index(date(2026, 1, 1), start, 1.0, 30) == 0

    def test_last_day_is_last_bucket(self):
        start = date(2026, 1, 1)
        # 30 days, 30 buckets, day 30 -> idx 29 (clamped)
        assert _bucket_index(date(2026, 1, 30), start, 1.0, 30) == 29

    def test_proportional_mid_period(self):
        start = date(2026, 1, 1)
        # 90 days, 10 buckets => 9 days/bucket
        # day 18 (delta=17) => idx=int(17/9)=1
        assert _bucket_index(date(2026, 1, 18), start, 9.0, 10) == 1

    def test_clamps_to_last_bucket_if_past_end(self):
        start = date(2026, 1, 1)
        # Way past the end of a 5-bucket / 5-day window
        assert _bucket_index(date(2027, 1, 1), start, 1.0, 5) == 4


class TestDefaultWindow:
    def test_returns_provided_dates(self):
        s, e = _default_window(date(2026, 1, 1), date(2026, 3, 1))
        assert s == date(2026, 1, 1)
        assert e == date(2026, 3, 1)

    def test_defaults_to_90_day_lookback(self):
        s, e = _default_window(None, None)
        # 89 days back PLUS today = 90-day window
        assert (e - s) == timedelta(days=89)

    def test_swaps_if_inverted(self):
        s, e = _default_window(date(2026, 6, 1), date(2026, 1, 1))
        assert s < e
