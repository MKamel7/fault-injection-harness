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

from fih.campaign import RUN_STEPS, run
from fih.catalog import Fault, load_catalog
from fih.injection.device import ActuatorFaultedController
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


def test_the_run_window_outlasts_the_hazard_it_is_budgeting() -> None:
    """Otherwise "not detected" means "not detected inside a window somebody picked".

    The slowest thermal hazard in this catalog takes over a thousand steps to
    materialise, so a fixed window derived from the winding time constant cut
    every degraded cooling run short before the hazard existed. The window is now
    taken from the fault's own budget when that is longer.
    """
    slowest = max(CATALOG, key=lambda f: f.ftti_steps or 0)
    assert slowest.ftti_steps is not None
    assert slowest.ftti_steps > RUN_STEPS, (
        "no catalogued budget exceeds the default window, so this property is "
        "not being exercised"
    )
    assert run(slowest).detected, "the slowest hazard is cut short again"

    # and an explicit window is still honoured, which is what makes the default
    # overridable for a targeted investigation
    assert not run(slowest, steps=5).detected


# --- observations that must GATE, not merely be recorded ---------------------
# Both of these were computed and then consumed by nothing, so two requirements
# read green on evidence that would not have changed had the device violated
# them. An independent review found it. These tests run the campaign against
# deliberately non-conforming devices, which is the only way to prove a gate is
# live rather than merely present.
class _NoTelemetryInFault(ActuatorFaultedController):
    def handle_command(self, line: str) -> str:
        if line.strip().upper() == "GET_TEMP" and self.state == "FAULT":
            return "ERR NO-TELEMETRY"
        return super().handle_command(line)


class _AcceptsCommandsInSafeState(ActuatorFaultedController):
    def handle_command(self, line: str) -> str:
        if line.strip().upper().startswith("SET_SPEED") and self.state == "FAULT":
            return "OK ACCEPTED-WHILE-IN-STO"
        return super().handle_command(line)


def _run_against(device: type, fault_id: str):  # type: ignore[no-untyped-def]
    import fih.campaign as campaign_module

    original = campaign_module.ActuatorFaultedController
    campaign_module.ActuatorFaultedController = device  # type: ignore[misc]
    try:
        return campaign_module.run(next(f for f in CATALOG if f.id == fault_id))
    finally:
        campaign_module.ActuatorFaultedController = original  # type: ignore[misc]


def test_unreadable_telemetry_in_the_safe_state_fails_sr09() -> None:
    """FLT-T05 used to manufacture its own detection.

    The harness tripped the device itself, then wrote a latency of 1 out of thin
    air, and the report rendered "detected at 1 of 1 steps" for a run in which
    nothing detected anything. The one property SR-09 is actually about,
    telemetry surviving in the safe state, was computed and read by nobody.
    """
    fault = next(f for f in CATALOG if f.id == "FLT-T05")
    result = _run_against(_NoTelemetryInFault, "FLT-T05")
    assert not result.telemetry_readable
    ok, why = verdict(fault, result)
    assert not ok and "not readable" in why


def test_a_safe_state_that_accepts_commands_fails_sr07() -> None:
    """FLT-T04's check wrote to a string that is rendered only for residual faults."""
    fault = next(f for f in CATALOG if f.id == "FLT-T04")
    result = _run_against(_AcceptsCommandsInSafeState, "FLT-T04")
    assert result.safe_state_accepted_command
    ok, why = verdict(fault, result)
    assert not ok and "accepted a speed command" in why
