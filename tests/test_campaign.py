"""Catalog driven verification.

Every test here is parametrised over `catalog/faults.yaml`, so adding fault 20
is a YAML entry and never a new test function. That is the property a safety
review looks for: the evidence set is data, so it can be reviewed, diffed and
extended by someone who does not write Python, and a reviewer can see that no
fault got special treatment.
"""

from __future__ import annotations

import pytest

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


def test_the_lying_sensor_actually_overheats_the_winding(results: dict) -> None:
    """The defence in depth finding, asserted so it cannot silently disappear.

    FLT-S01 is the project's central result: a single temperature source means a
    sensor that lies defeats the overheat protection completely. If a future
    change to the DUT closes this, this test fails and the safety argument has
    to be rewritten, which is the correct outcome.
    """
    result = results["FLT-S01"]
    assert result.overheated_undetected, (
        "FLT-S01 no longer drives the winding past its limit undetected"
    )
    assert result.true_temperature_c > result.sensed_temperature_c + 100, (
        "the gap between true and sensed temperature has closed; check whether "
        "the sensor model or the DUT changed"
    )
