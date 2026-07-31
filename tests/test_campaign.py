"""Catalog driven verification.

Every test here is parametrised over `catalog/faults.yaml`, so adding fault 20
is a YAML entry and never a new test function. That is the property a safety
review looks for: the evidence set is data, so it can be reviewed, diffed and
extended by someone who does not write Python, and a reviewer can see that no
fault got special treatment.
"""

from __future__ import annotations

import pytest
from dut_sim.motor_controller import OVERHEAT_LIMIT_C

from fih.campaign import run
from fih.catalog import Fault, load_catalog
from fih.report import verdict
from fih.traceability import load_requirements

CATALOG = load_catalog()
REQUIREMENTS = load_requirements()


def _ids(faults: tuple[Fault, ...]) -> list[str]:
    return [f.id for f in faults]


@pytest.fixture(scope="session")
def results() -> dict[str, object]:
    """One campaign for the whole session; runs are deterministic."""
    return {fault.id: run(fault) for fault in CATALOG}


# --- every catalogued fault must meet its recorded verdict -------------------
@pytest.mark.parametrize("fault", CATALOG, ids=_ids(CATALOG))
def test_fault_meets_its_verdict(fault: Fault, results: dict) -> None:
    ok, why = verdict(fault, results[fault.id])
    assert ok, f"{fault.id} ({fault.title}): {why}"


@pytest.mark.parametrize("fault", CATALOG, ids=_ids(CATALOG))
def test_detected_faults_reach_their_declared_safe_state(
    fault: Fault, results: dict
) -> None:
    """A fault declaring a safe state must actually get there.

    Detection is not the requirement. Reaching the safe state is. A design that
    notices a fault and keeps driving has satisfied nothing.
    """
    if fault.is_residual or fault.safe_state == "none":
        pytest.skip("no safe state declared for this fault")
    result = results[fault.id]
    assert result.reached_safe_state, (
        f"{fault.id} declares safe state {fault.safe_state} but the drive "
        f"finished in {result.final_state}"
    )


@pytest.mark.parametrize("fault", CATALOG, ids=_ids(CATALOG))
def test_campaign_is_deterministic(fault: Fault) -> None:
    """Same fault, same outcome, every time.

    An assessor asking to reproduce a result must get the identical one, so any
    accidental dependence on ordering, clock or hash seed is a defect in the
    evidence rather than a flaky test.
    """
    assert run(fault) == run(fault), f"{fault.id} produced different results across runs"


# --- properties of the catalog itself ----------------------------------------
def test_every_requirement_is_challenged() -> None:
    """Bidirectional traceability. Raises on a gap in either direction."""
    from fih.traceability import check
    check(CATALOG, REQUIREMENTS)


def test_residual_faults_are_genuinely_undetected(results: dict) -> None:
    """A residual entry must be an observation, not an excuse.

    If the design actually catches something recorded as residual, the rationale
    is stale and the report would be understating the design. That is still a
    failure: the report has to be wrong in neither direction.
    """
    for fault in CATALOG:
        if fault.is_residual:
            assert not results[fault.id].detected, (
                f"{fault.id} is recorded as residual but was detected. Update the "
                f"catalog rather than leaving the report understating the design."
            )


def test_at_least_one_fault_is_residual() -> None:
    """A campaign detecting everything is not credible, it is under-specified."""
    assert any(f.is_residual for f in CATALOG), (
        "no residual faults catalogued. Either the fault set is too easy or the "
        "hard cases were quietly dropped."
    )


def test_a_single_lying_sensor_is_now_caught_in_time(results: dict) -> None:
    """Third revision of this test, and each revision was the design improving.

    v1: asserted the winding cooked undetected. Failed when a second temperature
    source was added, which is what forced that source to exist.
    v2: asserted the trip landed inside the insulation limit. Failed when the
    thermal model was validated against its data sheet and the real physics
    turned out to be much faster.
    v3: asserted the trip was LATE, at step 12 and 207 C, because the frame is a
    larger thermal mass and cannot follow. Failed when a diverse model based
    channel was added, which has no thermal mass and no lag.

    Each failure was the test doing its job. A safety case that silently absorbs
    good news would also silently absorb bad news.
    """
    result = results["FLT-S01"]
    fault = next(f for f in CATALOG if f.id == "FLT-S01")
    assert fault.ftti_steps is not None
    assert result.detected and result.reached_safe_state
    assert result.detected_at_step is not None
    assert result.detected_at_step <= fault.ftti_steps, (
        f"caught at step {result.detected_at_step}, outside the "
        f"{fault.ftti_steps} step budget"
    )
    assert result.true_temperature_c <= OVERHEAT_LIMIT_C, (
        f"caught in time but at {result.true_temperature_c:.0f} C, past the limit"
    )


def test_diversity_survives_the_common_cause_that_redundancy_could_not(
    results: dict,
) -> None:
    """FLT-S05 was residual for as long as both channels were the same kind.

    Two sensors are two channels only while they fail independently. A model
    based channel reads no sensor, so whatever took both of them leaves it
    untouched. This is the clearest demonstration in the catalog of diverse
    versus merely duplicated, and it is pinned so a regression that removes the
    estimator fails here rather than quietly restoring an undetected runaway.
    """
    result = results["FLT-S05"]
    assert result.detected, "common cause is undetected again"
    assert result.true_temperature_c <= OVERHEAT_LIMIT_C


def test_the_estimator_cannot_see_the_plant(results: dict) -> None:
    """The other half of the diversity argument, and the half usually omitted.

    FLT-A03 degrades real cooling. The command is unchanged, so the estimator
    predicts the nominal and misses it entirely; only a measurement notices.
    Neither kind of channel is sufficient, which is what makes this diversity
    rather than redundancy.
    """
    result = results["FLT-A03"]
    assert result.detected and result.reached_safe_state
    assert result.notes == "" or "sensor" not in result.notes
