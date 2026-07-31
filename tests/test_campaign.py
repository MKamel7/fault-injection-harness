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


def test_a_single_lying_sensor_no_longer_defeats_the_thermal_trip(results: dict) -> None:
    """The finding that drove DUT v1.5, now inverted and still pinned.

    It used to assert the opposite: that FLT-S01 cooked the winding undetected.
    That assertion failing is what forced the second temperature source to be
    built, which is exactly what it was written to do. It now pins the fix, so a
    regression that removes the second channel fails here rather than quietly
    restoring a hazard.
    """
    result = results["FLT-S01"]
    assert result.detected, "a lying winding sensor is no longer caught"
    assert result.reached_safe_state
    assert result.true_temperature_c < OVERHEAT_LIMIT_C, (
        f"the drive tripped, but only after the winding reached "
        f"{result.true_temperature_c:.0f} C, past the {OVERHEAT_LIMIT_C:.0f} C limit"
    )
    assert result.true_temperature_c > result.sensed_temperature_c + 50, (
        "the winding and the sensor no longer disagree, so this test is not "
        "exercising the fault it was written for"
    )


def test_redundancy_does_not_survive_common_cause(results: dict) -> None:
    """The honest counterweight to the entry above.

    Adding a second sensor closes the INDEPENDENT failure and does nothing at all
    about common cause. If this ever starts passing as detected, either the DUT
    gained genuinely diverse channels or the injection stopped being common
    cause, and both need the safety argument rewritten.
    """
    result = results["FLT-S05"]
    assert not result.detected, "common cause is now detected; check what changed"
    assert result.overheated_undetected
    assert result.true_temperature_c > OVERHEAT_LIMIT_C * 2, (
        f"the winding only reached {result.true_temperature_c:.0f} C, so the "
        f"common cause case is no longer demonstrating an uncontrolled overheat"
    )
