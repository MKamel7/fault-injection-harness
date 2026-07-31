"""Latent fault plus primary fault.

The properties asserted here are about what makes a pair campaign mean anything,
not just about whether it runs. Two in particular:

  A latent fault must be SILENT ALONE. If it is detected or hazardous by itself
  then it is not latent, it is just a fault, and pairing it proves nothing.

  A latent fault must NOT change every outcome. The control pairs exist so the
  campaign cannot degenerate into "two faults are worse than one", which is true
  and says nothing.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from dut_sim.motor_controller import OVERHEAT_LIMIT_C

from fih.catalog import CatalogError, load_catalog
from fih.dual_point import load_pairs, run_all_pairs, run_pair, verdict

CATALOG = load_catalog()
BY_ID = {f.id: f for f in CATALOG}
PAIRS = load_pairs(known=BY_ID)
IDS = [p.id for p in PAIRS]


@pytest.fixture(scope="session")
def results() -> dict:
    return run_all_pairs(PAIRS, BY_ID)


@pytest.mark.parametrize("pair", PAIRS, ids=IDS)
def test_pair_meets_its_recorded_verdict(pair, results: dict) -> None:  # type: ignore[no-untyped-def]
    ok, why = verdict(pair, results[pair.id])
    assert ok, f"{pair.id} ({pair.title}): {why}"


@pytest.mark.parametrize("pair", PAIRS, ids=IDS)
def test_the_latent_member_really_is_latent(pair, results: dict) -> None:  # type: ignore[no-untyped-def]
    """Undetected AND harmless on its own, or the pair proves nothing."""
    result = results[pair.id]
    assert not result.latent_alone.detected, (
        f"{pair.latent} is detected on its own, so it is not latent"
    )
    assert result.latent_alone.true_temperature_c < OVERHEAT_LIMIT_C, (
        f"{pair.latent} is hazardous on its own, so it is a primary fault"
    )


@pytest.mark.parametrize("pair", PAIRS, ids=IDS)
def test_pairs_are_deterministic(pair) -> None:  # type: ignore[no-untyped-def]
    assert run_pair(pair, BY_ID) == run_pair(pair, BY_ID)


def test_at_least_one_pair_is_worse_than_either_member(results: dict) -> None:
    """Otherwise the pair campaign is not exercising latency at all."""
    changed = [p.id for p in PAIRS if results[p.id].caused_by_the_combination]
    assert changed, (
        "no pair changed the outcome, so nothing here demonstrates that a latent "
        "fault removes a safety mechanism"
    )


def test_at_least_one_control_pair_is_unchanged(results: dict) -> None:
    """The property that stops this reading as 'more faults are worse'.

    A latent fault is consequential only in combination with something that
    needed the mechanism it removed. If every pair got worse, the campaign would
    be measuring fault count rather than latency.
    """
    unchanged = [p.id for p in PAIRS if not results[p.id].caused_by_the_combination]
    assert unchanged, (
        "every pair changed its outcome, which means the 'latent' fault is "
        "affecting cases that never depended on it"
    )


def test_the_headline_pair_runs_away_undetected(results: dict) -> None:
    """DP-01 is the argument for counting latent faults separately.

    FLT-S01 alone is bounded at 207 C because the frame contradicts the lie.
    With the frame channel already dead there is nothing to contradict it, and a
    fault the design demonstrably handles becomes one it cannot see at all.
    """
    result = results["DP-01"]
    assert result.primary_alone.detected, "FLT-S01 alone should still be caught"
    assert not result.combined.detected, "the combination is no longer undetected"
    assert result.combined.true_temperature_c > result.primary_alone.true_temperature_c * 4, (
        f"the combination reached {result.combined.true_temperature_c:.0f} C "
        f"against {result.primary_alone.true_temperature_c:.0f} C alone; the gap "
        f"is the finding and it has narrowed"
    )


def test_a_pair_can_defeat_the_case_the_design_handles_best(results: dict) -> None:
    """DP-02, the pointed one.

    FLT-S08 is the entry that justifies the second temperature source: caught in
    time, inside the limit. A latent fault removes exactly that.
    """
    result = results["DP-02"]
    assert result.primary_alone.reached_safe_state
    assert result.primary_alone.true_temperature_c < OVERHEAT_LIMIT_C
    assert result.safety_goal_violated


# --- the pair loader, tested by breaking it ---------------------------------
GOOD = """
version: 1
pairs:
  - id: DP-X1
    title: A pair
    latent: FLT-S07
    primary: FLT-S01
    challenges: [SR-10]
    expectation: violated
    rationale: text
"""


def _load(tmp_path: Path, body: str):  # type: ignore[no-untyped-def]
    path = tmp_path / "dual_point.yaml"
    path.write_text(textwrap.dedent(body))
    return load_pairs(path, known=BY_ID)


def test_a_pair_referencing_an_unknown_fault_is_rejected(tmp_path: Path) -> None:
    """It would run nothing and still report a result."""
    with pytest.raises(CatalogError, match="not in the fault catalog"):
        _load(tmp_path, GOOD.replace("FLT-S07", "FLT-NOPE"))


def test_a_fault_paired_with_itself_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="paired with itself"):
        _load(tmp_path, GOOD.replace("primary: FLT-S01", "primary: FLT-S07"))


@pytest.mark.parametrize("mutation,replacement", [
    ("expectation: violated", "expectation: probably"),
    ("title: A pair", "titel: A pair"),
])
def test_malformed_pairs_are_rejected(tmp_path: Path, mutation: str,
                                      replacement: str) -> None:
    with pytest.raises(CatalogError):
        _load(tmp_path, GOOD.replace(mutation, replacement))


def test_a_missing_field_is_rejected(tmp_path: Path) -> None:
    body = "\n".join(ln for ln in GOOD.splitlines() if "rationale" not in ln)
    with pytest.raises(CatalogError, match="missing required field"):
        _load(tmp_path, body)


def test_duplicate_pair_ids_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="duplicate"):
        _load(tmp_path, GOOD + GOOD.split("pairs:")[1])


def test_a_file_that_is_not_a_pair_catalog_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="expected a mapping"):
        _load(tmp_path, "nope\n")


def test_an_empty_pair_catalog_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="empty"):
        _load(tmp_path, "version: 1\npairs: []\n")


def test_pairs_load_without_cross_checking_when_no_catalog_is_given(
    tmp_path: Path,
) -> None:
    """The check is opt in, so the loader stays usable on its own."""
    path = tmp_path / "dual_point.yaml"
    path.write_text(textwrap.dedent(GOOD.replace("FLT-S07", "FLT-WHATEVER")))
    assert load_pairs(path)[0].latent == "FLT-WHATEVER"


# --- the verdict, tested in both wrong directions ----------------------------
def _pair(**kw):  # type: ignore[no-untyped-def]
    import dataclasses
    return dataclasses.replace(PAIRS[0], **kw)


def _result(pair_id: str, **kw):  # type: ignore[no-untyped-def]
    import dataclasses
    base = run_pair(PAIRS[0], BY_ID)
    return dataclasses.replace(base, pair_id=pair_id, **kw)


def test_a_latent_member_that_is_not_silent_fails_the_verdict() -> None:
    """Pairing a fault that is hazardous alone measures nothing about latency."""
    from fih.campaign import run

    bad = _result("DP-X", latent_alone=run(BY_ID["FLT-A01"]))
    ok, why = verdict(PAIRS[0], bad)
    assert not ok and "not latent" in why


def test_a_pair_that_stops_violating_fails_the_verdict() -> None:
    """Same rule as a residual fault: good news is a stale record until updated.

    If a diagnostic is ever added that catches the latent fault, DP-01 stops
    violating and this must fail, forcing the entry and the safety argument to be
    rewritten rather than silently passing.
    """
    from fih.campaign import run

    fixed = _result("DP-01", combined=run(BY_ID["FLT-A01"]))
    ok, why = verdict(PAIRS[0], fixed)
    assert not ok and "stale" in why


def test_a_control_pair_that_starts_violating_fails_the_verdict() -> None:
    from fih.campaign import run

    handled = _pair(expectation="handled")
    broken = _result("DP-X", combined=run(BY_ID["FLT-S01"], latent=BY_ID["FLT-S07"]))
    ok, why = verdict(handled, broken)
    assert not ok and "recorded as handled" in why


def test_the_dual_point_report_shows_both_members_and_the_combination() -> None:
    """A table of combined outcomes alone would hide what makes a fault latent."""
    from fih.report import dual_point_markdown

    text = dual_point_markdown(PAIRS, run_all_pairs(PAIRS, BY_ID))
    for pair in PAIRS:
        assert pair.id in text
        assert pair.latent in text and pair.primary in text
    assert "Primary alone" in text and "Combined" in text
    assert "control cases" in text
    assert "not** an ISO 26262 latent fault metric" in text
