from __future__ import annotations

import unittest

from alpabridge.cli.numeric import int_or_zero, optional_int


class NumericCoercionTests(unittest.TestCase):
    def test_optional_int_passes_through_ordinary_values(self) -> None:
        self.assertEqual(5, optional_int(5))
        self.assertEqual(5, optional_int(5.0))
        self.assertEqual(5, optional_int("5"))
        self.assertEqual(1, optional_int(True))
        self.assertIsNone(optional_int(None))

    def test_optional_int_rejects_non_finite_floats_instead_of_crashing(self) -> None:
        # A summary JSON's NaN/inf literal (json.loads accepts both by
        # default) used to crash every one of the four near-identical
        # copies of this helper that used to exist across
        # promote_batch_summary.py/benchmark_readiness.py/
        # benchmark_summary.py/batch_summary.py - one didn't catch
        # ValueError at all (NaN), all four missed OverflowError (inf).
        self.assertIsNone(optional_int(float("nan")))
        self.assertIsNone(optional_int(float("inf")))
        self.assertIsNone(optional_int(float("-inf")))

    def test_optional_int_rejects_malformed_input(self) -> None:
        self.assertIsNone(optional_int("not-a-number"))
        self.assertIsNone(optional_int([1, 2]))

    def test_int_or_zero_falls_back_to_zero_for_missing_or_invalid_values(self) -> None:
        self.assertEqual(0, int_or_zero(None))
        self.assertEqual(0, int_or_zero(float("nan")))
        self.assertEqual(0, int_or_zero(float("inf")))
        self.assertEqual(7, int_or_zero(7))


if __name__ == "__main__":
    unittest.main()
