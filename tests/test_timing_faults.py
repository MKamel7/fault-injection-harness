"""Jitter and drift, and why they are not the fixed delay in a hat.

`delay_response` already existed and holds every reply by the same number of
steps. That is the easy case: it is either always inside the timeout or always
outside it, so a threshold tuned once catches it or never does.

The two faults here are the ones that defeat a counter-and-timeout scheme in
the field, and they defeat it in opposite ways:

  jitter  the delay varies, so most exchanges are comfortably inside the budget
          and a few are not. A scheme validated on the mean looks correct and
          fails on the tail.

  drift   no single reply is late, but the far end's clock runs fast so the
          lateness accumulates. Every frame is individually perfect.

The campaign catches the first and does not catch the second, which is recorded
as FLT-T07's residual rationale. These tests pin the injection behaviour that
makes that result mean something.
"""

from __future__ import annotations

from fih.injection.transport import (
    FaultyTransport,
    drift_response_clock,
    jitter_response,
)


class Echo:
    """A transport that answers every request with its own sequence number."""

    def __init__(self) -> None:
        self.seen = 0

    def request(self, line: str) -> str:
        self.seen += 1
        return f"OK {self.seen}"


def latencies(tx: FaultyTransport, exchanges: int) -> list[int]:
    """How far behind the reply to each request is, in exchanges.

    A delivered reply carries the sequence number of the request it answers, so
    the lag is the difference. A blank exchange means nothing came back at all,
    which puts the link exactly one exchange further behind than it already was;
    counting it as the request number instead would report a lag of 40 on the
    40th exchange and make every drift measurement meaningless.
    """
    lag, behind = [], 0
    for issued in range(1, exchanges + 1):
        reply = tx.request("GET_SPEED")
        behind = behind + 1 if not reply else issued - int(reply.split()[1])
        lag.append(behind)
    return lag


# ---- jitter -----------------------------------------------------------------

def test_jitter_varies_the_delay_rather_than_fixing_it():
    """The whole point. A constant lag would be delay_response again."""
    tx = FaultyTransport(Echo())
    jitter_response(tx, max_steps=14, seed=7)

    lag = latencies(tx, 60)

    assert len(set(lag)) > 1, "jitter produced a constant lag, which is a fixed delay"


def test_jitter_is_reproducible_from_its_seed():
    """A campaign whose verdict depends on an unseeded draw is not evidence.

    This repository's output is an argument about what the design detects. If
    the same commit reported a different result on different days, the argument
    would be unfalsifiable rather than strong.
    """
    first, second = FaultyTransport(Echo()), FaultyTransport(Echo())
    jitter_response(first, max_steps=14, seed=7)
    jitter_response(second, max_steps=14, seed=7)

    assert latencies(first, 40) == latencies(second, 40)


def test_a_different_seed_gives_a_different_draw():
    """Otherwise the seed is decoration and the test above proves nothing."""
    first, second = FaultyTransport(Echo()), FaultyTransport(Echo())
    jitter_response(first, max_steps=14, seed=7)
    jitter_response(second, max_steps=14, seed=99)

    assert latencies(first, 40) != latencies(second, 40)


def test_jitter_eventually_exceeds_a_budget_a_mean_would_clear():
    """Why a step-counted timeout can see jitter at all.

    The mean lag sits well inside the ten step timeout; the tail does not, and
    the tail is what an FTTI has to be argued from.
    """
    tx = FaultyTransport(Echo())
    jitter_response(tx, max_steps=14, seed=7)

    lag = latencies(tx, 120)
    assert sum(lag) / len(lag) < 14
    assert max(lag) > 10, "no exchange ever exceeded the timeout, so nothing to detect"


# ---- drift ------------------------------------------------------------------

def test_drift_accumulates_instead_of_spiking():
    """The property that makes it invisible to a counter and a timeout.

    Lateness grows monotonically. There is no exchange at which the link looks
    anomalous, because at every instant it is only one step worse than it was.
    """
    tx = FaultyTransport(Echo())
    drift_response_clock(tx, every=4)

    lag = latencies(tx, 80)
    early, late = lag[:20], lag[-20:]

    assert max(late) > max(early), "the lateness did not accumulate"
    # No single step jumps: that is what separates drift from jitter.
    # Not strict=True: adjacent pairs come from slices one element apart.
    assert all(b - a <= 1 for a, b in zip(lag, lag[1:]))  # noqa: B905


def test_drift_holds_one_extra_step_at_the_stated_rate():
    """every=4 means one extra held step per four exchanges, not per one."""
    tx = FaultyTransport(Echo())
    drift_response_clock(tx, every=4)

    lag = latencies(tx, 40)

    # 40 exchanges at one extra step per four is ten steps of accumulated lag,
    # allowing one for where the boundary falls.
    assert 9 <= max(lag) <= 11, f"accumulated {max(lag)} steps, expected about 10"


def test_neither_hook_disturbs_a_clean_link():
    """Both are off by default, so an unarmed transport is transparent."""
    tx = FaultyTransport(Echo())

    assert [tx.request("GET_SPEED") for _ in range(5)] == [
        "OK 1", "OK 2", "OK 3", "OK 4", "OK 5"]
