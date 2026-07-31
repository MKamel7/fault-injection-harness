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
    """Undetected AND harmless on its own, or the pair proves nothing.

    Applies only to latent_plus_primary pairs. A DUAL POINT pair is two faults
    the design detects perfectly well on its own which together defeat it, and
    demanding latency of those would be demanding the wrong property.
    """
    if not pair.is_latent_kind:
        pytest.skip("dual point pair: neither member is expected to be latent")
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


def test_the_latent_pairs_are_handled_and_the_dual_point_one_is_not(
    results: dict,
) -> None:
    """The two kinds now come out differently, and that is the finding.

    DP-01 and DP-02 violated a safety goal until a diverse third channel was
    added, and are kept rather than deleted because a pair that stopped
    violating is the regression test for whatever stopped it.

    DP-05 is the counterweight, and it was unreachable until the overload
    channel was given a current sensor. While it read plant truth directly it
    could not be faulted, so the campaign could only demonstrate the flattering
    direction of the diversity argument.
    """
    for pair_id in ("DP-01", "DP-02"):
        assert not results[pair_id].safety_goal_violated, (
            f"{pair_id} violates a safety goal again; the third channel has "
            f"regressed and the catalog says it should not"
        )
    assert results["DP-05"].safety_goal_violated, (
        "DP-05 no longer violates; if the design genuinely closed it the entry "
        "and the safety argument both need rewriting"
    )
    assert any(p.kind == "dual_point" for p in PAIRS), (
        "no dual point pair remains, so the campaign only exercises latency"
    )


def test_at_least_one_control_pair_is_unchanged(results: dict) -> None:
    """The property that stops this reading as 'more faults are worse'.

    A latent fault is consequential only in combination with something that
    needed the mechanism it removed. If every pair changed its outcome, the
    campaign would be measuring fault count rather than latency.
    """
    unchanged = [p.id for p in PAIRS if not results[p.id].caused_by_the_combination]
    assert unchanged, (
        "every pair changed its outcome, which means the 'latent' fault is "
        "affecting cases that never depended on it"
    )


def test_the_machinery_can_still_recognise_a_violation() -> None:
    """Asserted by construction, because no real pair violates any more.

    A campaign in which nothing fails is worth exactly as much as its ability to
    notice failure, and that ability is now exercised nowhere else.
    """
    import dataclasses

    from fih.campaign import run

    violating = dataclasses.replace(
        run(BY_ID["FLT-S05"]), reached_safe_state=False,
        true_temperature_c=OVERHEAT_LIMIT_C * 3, detected_at_step=None,
        rejected_command=False,
    )
    result = dataclasses.replace(run_pair(PAIRS[0], BY_ID), combined=violating)
    assert result.safety_goal_violated

    # A pair recorded as handled that violates must fail...
    ok, why = verdict(PAIRS[0], result)
    assert not ok and "recorded as handled" in why

    # ...and one recorded as violating that violates must pass, with the
    # temperature in the message, so a reader can see how bad it got.
    ok, why = verdict(dataclasses.replace(PAIRS[0], expectation="violated"), result)
    assert ok and "safety goal violated" in why and "C undetected" in why


# --- the pair loader, tested by breaking it ---------------------------------
GOOD = """
version: 1
pairs:
  - id: DP-X1
    title: A pair
    latent: FLT-S07
    primary: FLT-S01
    kind: latent_plus_primary
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

    Not hypothetical. DP-01 and DP-02 were recorded as violating, a diverse
    third channel was added, and this rule is exactly what failed the build and
    forced both entries plus the safety argument to be rewritten instead of
    quietly going green.
    """
    from fih.campaign import run

    ok, why = verdict(_pair(expectation="violated"),
                      _result("DP-01", combined=run(BY_ID["FLT-A01"])))
    assert not ok and "stale" in why


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


def test_a_pair_of_the_wrong_kind_is_rejected() -> None:
    """The two kinds are not interchangeable and the verdict says so.

    Recording a dual point fault as latent_plus_primary would claim the members
    are individually silent when the design detects them both, and recording a
    latent pair as dual_point would claim the opposite. Either misdescribes what
    the campaign measured.
    """
    import dataclasses

    latent_pair = next(p for p in PAIRS if p.is_latent_kind)
    dual_pair = next(p for p in PAIRS if not p.is_latent_kind)

    ok, why = verdict(dataclasses.replace(latent_pair, kind="dual_point"),
                      run_pair(latent_pair, BY_ID))
    assert not ok and "latent fault rather than the dual point" in why

    ok, why = verdict(dataclasses.replace(dual_pair, kind="latent_plus_primary"),
                      run_pair(dual_pair, BY_ID))
    assert not ok and "is not latent" in why


def test_an_unknown_pair_kind_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="kind"):
        _load(tmp_path, GOOD.replace("kind: latent_plus_primary", "kind: sort of both"))
