# Copied from quantlib-migration tests/helpers/approx.py (the project author's own test helper),
# commit of the quantlib-migration checkout at the time of copying: 3cae567
"""Tolerance helpers: the BOOST semantics of the upstream cases, and the tiers of 4.3.

Two different jobs live here and must not be confused.

**1. The upstream tolerance (tier T1).** A transliterated case keeps the
upstream tolerance, never loosened - which means reproducing what the Boost
macro it came from actually does. Two traps, both of which silently turn a
test into a weaker one if you reach for `pytest.approx` instead:

* `BOOST_CHECK_CLOSE(a, b, t)` takes `t` as a **PERCENT**. Writing
  `pytest.approx(rel=1e-6)` where the C++ said `QL_CHECK_CLOSE(a, b, 1e-6)`
  is a hundred times too tight; writing `rel=t` where the C++ said `t` percent
  is a hundred times too loose.
* It is the **STRONG** form: `|a-b|/|a| <= t/100` **and** `|a-b|/|b| <= t/100`.
  The weak form (either one) is a different, looser test.

`close_pct`, `close_frac` and `small` below reproduce Boost's
`close_at_tolerance` and `check_is_small` exactly, including
`safe_fpt_division`, which is what makes `0` versus `0` pass while `0` versus
`1e-300` fails. That last property matters: an expected `0.0` must pass only
if the actual value is exactly `0.0`.

    QL_CHECK_CLOSE(a, b, t)          -> assert_close_pct(a, b, t)
    QL_CHECK_CLOSE_FRACTION(a, b, t) -> assert_close_frac(a, b, t)
    QL_CHECK_SMALL(v, t)             -> assert_small(v, t)

(`test-suite/utilities.hpp:62-64` defines those three wrappers over the Boost
macros.)

**2. The differential tiers (tier T2, 4.3).** A differential test compares the
port with the oracle, and its tolerance has nothing to do with the upstream
case's: closed-form scalar results agree to relative `1e-12` with an absolute
floor of `1e-14` near zero, and solver outputs to absolute `1e-11`, which is
below every solver accuracy in use (1e-10 in CashFlows / BondFunctions, 1e-8
in `Bond::yield`, `bond.hpp:179,211`) so that an iteration-path divergence is
visible rather than absorbed.

A work package may **TIGHTEN** a T2 tier (WP-09 uses 1e-14) and may never
loosen one: `assert_t2` rejects a `rel` or `abs_floor` larger than the tier,
naming `tests/tolerance_waivers.toml`, because a test that fails its tier but
would pass a looser one is a bug until root-caused. A version skew is never a
tolerance question either (rule QL-O1, 4.8): it is marked with its registry id
and answered by the v1.43 test named there.

**3. The soft-assert collector.** `BOOST_ERROR` reports and CONTINUES, which
is what the 540-bond loops of `bonds.cpp` `testYield` / `testAtmRate` /
`testZspread` rely on - a plain `assert` inside such a loop stops at the first
mismatch and hides the pattern (is it one bond, or all of them?). `soft()`
collects, then fails once with the count and the first failures.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Iterator
from contextlib import contextmanager

__all__ = [
    "T2_ABSOLUTE",
    "T2_RELATIVE",
    "T2_SOLVER",
    "SoftAssert",
    "assert_close_frac",
    "assert_close_pct",
    "assert_small",
    "assert_t2",
    "assert_t2_solver",
    "close_frac",
    "close_pct",
    "relative_error",
    "small",
    "soft",
]

# --------------------------------------------------------------------------- tier T2 (4.3)
#: Closed-form scalar results (year fractions, InterestRate factors, coupon
#: amounts, NPVs, prices): relative agreement with the oracle.
T2_RELATIVE = 1e-12
#: The absolute floor of the tier, for quantities near zero.
T2_ABSOLUTE = 1e-14
#: Solver outputs (yield, z-spread): absolute, below every solver accuracy in
#: use, so that an iteration-path divergence shows up instead of being
#: absorbed by the solver's own tolerance.
T2_SOLVER = 1e-11

_FLT_MAX = sys.float_info.max
_FLT_MIN = sys.float_info.min


# --------------------------------------------------------------------------- Boost semantics
def _safe_fpt_division(f1: float, f2: float) -> float:
    """Boost's `safe_fpt_division` (both arguments non-negative).

    It is what gives the percent check its behaviour at zero, so it is
    reproduced rather than approximated: dividing by an exact zero yields
    `DBL_MAX` (i.e. "infinitely far"), and a zero numerator yields 0.
    """
    # Avoid overflow.
    if f2 < 1.0 and f1 > f2 * _FLT_MAX:
        return _FLT_MAX
    # Avoid underflow.
    if f1 == 0.0 or (f2 > 1.0 and f1 < f2 * _FLT_MIN):
        return 0.0
    return f1 / f2


def _close_at_tolerance(left: float, right: float, fraction_tolerance: float) -> bool:
    """Boost's `close_at_tolerance`, STRONG form - both relative differences."""
    diff = math.fabs(left - right)
    d1 = _safe_fpt_division(diff, math.fabs(right))
    d2 = _safe_fpt_division(diff, math.fabs(left))
    return d1 <= fraction_tolerance and d2 <= fraction_tolerance


def close_pct(a: float, b: float, percent: float) -> bool:
    """`BOOST_CHECK_CLOSE(a, b, percent)` - the tolerance is a PERCENT."""
    return _close_at_tolerance(a, b, 0.01 * percent)


def close_frac(a: float, b: float, fraction: float) -> bool:
    """`BOOST_CHECK_CLOSE_FRACTION(a, b, fraction)` - the tolerance is a fraction."""
    return _close_at_tolerance(a, b, fraction)


def small(value: float, tolerance: float) -> bool:
    """`BOOST_CHECK_SMALL(value, tolerance)`: `|value| < tolerance`, STRICTLY."""
    return math.fabs(value) < tolerance


def relative_error(x1: float, x2: float, reference: float) -> float:
    """`relativeError` of `test-suite/utilities.cpp:132-138`, verbatim."""
    if reference != 0.0:
        return math.fabs(x1 - x2) / reference
    # fall back to absolute error
    return math.fabs(x1 - x2)


def _detail(a: float, b: float, tolerance: str) -> str:
    return f"\n    calculated: {a!r}\n    expected:   {b!r}\n    difference: {a - b!r}\n    tolerance:  {tolerance}"


def assert_close_pct(a: float, b: float, percent: float, message: str = "") -> None:
    """`QL_CHECK_CLOSE` (`utilities.hpp:63`). `percent` is a PERCENT."""
    if not close_pct(a, b, percent):
        raise AssertionError((message or "values are not close") + _detail(a, b, f"{percent} %"))


def assert_close_frac(a: float, b: float, fraction: float, message: str = "") -> None:
    """`QL_CHECK_CLOSE_FRACTION` (`utilities.hpp:64`). `fraction` is a fraction."""
    if not close_frac(a, b, fraction):
        raise AssertionError((message or "values are not close") + _detail(a, b, f"{fraction} (fraction)"))


def assert_small(value: float, tolerance: float, message: str = "") -> None:
    """`QL_CHECK_SMALL` (`utilities.hpp:62`)."""
    if not small(value, tolerance):
        raise AssertionError((message or "value is not small") + _detail(value, 0.0, f"{tolerance} (absolute, strict)"))


# --------------------------------------------------------------------------- tier T2
def _reject_loosening(rel: float, abs_floor: float) -> None:
    """A WP may TIGHTEN a T2 tier and may never loosen one (4.3)."""
    if rel > T2_RELATIVE or abs_floor > T2_ABSOLUTE:
        raise ValueError(
            f"T2 may be tightened, never loosened: rel={rel}, abs_floor={abs_floor} against the tier "
            f"rel={T2_RELATIVE}, abs_floor={T2_ABSOLUTE}. A differential test that fails its tier but "
            f"would pass a looser one is a BUG until root-caused; the only other legal outcome is an "
            f"approved line in tests/tolerance_waivers.toml (4.3). A version skew is not a tolerance "
            f"question at all - mark it with its registry id (rule QL-O1, 4.8)."
        )


def assert_t2(
    a: float,
    b: float,
    message: str = "",
    rel: float = T2_RELATIVE,
    abs_floor: float = T2_ABSOLUTE,
) -> None:
    """Tier T2 for a closed-form scalar: relative `rel` with an absolute floor.

    A tightened tier always states its absolute floor, which is why
    `abs_floor` is an explicit argument rather than something derived.
    """
    _reject_loosening(rel, abs_floor)
    bound = abs_floor if abs_floor > rel * max(math.fabs(a), math.fabs(b)) else rel * max(math.fabs(a), math.fabs(b))
    if not math.fabs(a - b) <= bound:
        raise AssertionError(
            (message or "T2: the port and the oracle disagree")
            + _detail(a, b, f"relative {rel}, absolute floor {abs_floor} (bound {bound!r})")
        )


def assert_t2_solver(a: float, b: float, message: str = "", bound: float = T2_SOLVER) -> None:
    """Tier T2 for a solver output (yield, z-spread): absolute `bound`."""
    if bound > T2_SOLVER:
        raise ValueError(
            f"T2 solver bound may be tightened, never loosened: {bound} against the tier {T2_SOLVER}. "
            f"The 2e-10 Newton-family bound of skew OS-10 that this release once forecast was never "
            f"written: tests/tolerance_waivers.toml is EMPTY BY APPROVAL (2026-09-25) and rule QL-O1 "
            f"forbids a waiver beside a marked test, so the answer to an oracle skew is "
            f"@skew_oracle, not a bound here (4.3, 4.8)."
        )
    if not math.fabs(a - b) <= bound:
        raise AssertionError((message or "T2: the port and the oracle disagree") + _detail(a, b, f"{bound} (absolute)"))


# --------------------------------------------------------------------------- soft assertions
class SoftAssert:
    """A `BOOST_ERROR` collector: report and continue, then fail once at the end.

    `bonds.cpp` `testYield`, `testAtmRate` and `testZspread` each sweep 540
    bonds and call `BOOST_ERROR` inside the loop, so the C++ run reports every
    mismatch. A plain `assert` would stop at the first one and hide whether
    the problem is one bond or the whole sweep.
    """

    #: How many individual failures a report prints before it summarises.
    SHOWN = 20

    def __init__(self, label: str = "") -> None:
        self.label = label
        self.failures: list[str] = []
        self.checks = 0

    # -- the collectors ----------------------------------------------------
    def error(self, message: str) -> None:
        """`BOOST_ERROR(message)`: record a failure and carry on."""
        self.failures.append(message)

    def check(self, condition: bool, message: str) -> bool:
        """`BOOST_CHECK(condition)`. Returns the condition, so a loop can skip on."""
        self.checks += 1
        if not condition:
            self.failures.append(message)
        return condition

    def close_pct(self, a: float, b: float, percent: float, message: str = "") -> bool:
        """`QL_CHECK_CLOSE` inside a loop."""
        self.checks += 1
        if close_pct(a, b, percent):
            return True
        self.failures.append((message or "values are not close") + _detail(a, b, f"{percent} %"))
        return False

    def close_frac(self, a: float, b: float, fraction: float, message: str = "") -> bool:
        """`QL_CHECK_CLOSE_FRACTION` inside a loop."""
        self.checks += 1
        if close_frac(a, b, fraction):
            return True
        self.failures.append((message or "values are not close") + _detail(a, b, f"{fraction} (fraction)"))
        return False

    def small(self, value: float, tolerance: float, message: str = "") -> bool:
        """`QL_CHECK_SMALL` inside a loop."""
        self.checks += 1
        if small(value, tolerance):
            return True
        self.failures.append((message or "value is not small") + _detail(value, 0.0, f"{tolerance} (absolute)"))
        return False

    def t2(
        self, a: float, b: float, message: str = "", rel: float = T2_RELATIVE, abs_floor: float = T2_ABSOLUTE
    ) -> bool:
        """Tier T2 inside a differential sweep."""
        self.checks += 1
        try:
            assert_t2(a, b, message, rel=rel, abs_floor=abs_floor)
        except AssertionError as exc:
            self.failures.append(str(exc))
            return False
        return True

    def t2_solver(self, a: float, b: float, message: str = "", bound: float = T2_SOLVER) -> bool:
        """Tier T2 for a SOLVER output inside a differential sweep.

        The in-collector form of `assert_t2_solver`, and it exists for the
        same reason `t2` does: a sweep that compares a `yield` or a
        `zSpread` row by row needs the bound to arrive through the guarded
        function rather than as a hand-rolled `check(fabs(a - b) <= bound)`.
        The hand-rolled spelling is correct until someone widens the number
        beside it, and `assert_t2_solver`'s refusal to be loosened (4.3) is
        precisely what a bare comparison walks around.
        """
        self.checks += 1
        try:
            assert_t2_solver(a, b, message, bound=bound)
        except AssertionError as exc:
            self.failures.append(str(exc))
            return False
        return True

    # -- the verdict -------------------------------------------------------
    def report(self) -> None:
        """Fail once, with the count and the first `SHOWN` failures."""
        if not self.failures:
            return
        head = f"{len(self.failures)} of {self.checks} check(s) failed"
        if self.label:
            head = f"{self.label}: {head}"
        shown = self.failures[: self.SHOWN]
        tail = "" if len(self.failures) <= self.SHOWN else f"\n  ... and {len(self.failures) - self.SHOWN} more"
        raise AssertionError(head + "\n  " + "\n  ".join(shown) + tail)


@contextmanager
def soft(label: str = "") -> Iterator[SoftAssert]:
    """`with soft('testYield') as s: ...` - collect inside the loop, fail once after it.

    An exception raised inside the block propagates unchanged and the
    collected failures are not reported over the top of it: the real error is
    the one that escaped.
    """
    collector = SoftAssert(label)
    yield collector
    collector.report()
