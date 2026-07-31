"""Run a catalogued fault against the device and record what happened.

One fault per run, on a fresh controller, with a fixed step budget. Determinism
matters more than realism here: an assessor asking "reproduce that result" must
get the identical outcome, so nothing in this module consumes randomness and the
step budget is explicit rather than wall clock.

What a run records is deliberately narrow. Not "did the test pass", which
presupposes the answer, but **what the device did**: whether it reached its safe
state, after how many steps, and what the winding was actually doing versus what
the device believed. Judgement against the FTTI happens afterwards in the
report, so the same run data can be re-judged if a budget changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from dut_sim.motor_controller import OVERHEAT_LIMIT_C, RATED_TORQUE_NM, THERMAL_TIME_STEPS
from testbench.driver import MotorControllerDriver, ProtocolError, SimTransport

from fih.catalog import Fault
from fih.injection.device import (
    DEVICE_HOOKS,
    ActuatorFaultedController,
)
from fih.injection.transport import TRANSPORT_HOOKS, FaultyTransport

#: Steps a campaign runs for, DERIVED rather than chosen. It was 120 against a
#: thermal time constant of 125, so no run ever reached thermal equilibrium and
#: "not detected" quietly meant "not detected within 0.96 time constants". The
#: constant predated the thermal model it was timing.
#:
#: Two full thermal time constants puts the slowest process in the item at 86%
#: of its final value, so a thermal fault that is going to be missed has visibly
#: been missed rather than merely being still in progress.
RUN_STEPS = int(THERMAL_TIME_STEPS * 2)

#: Watchdog budget armed for the liveness faults. Ten steps, so the 11 step FTTI
#: in the catalog is budget plus one.
WATCHDOG_BUDGET = 10

#: Faults whose requirement is about behaviour AFTER the safe state is reached.
#: The run continues past detection for these, or the property they exist to
#: check never gets exercised.
_POST_SAFE_STATE_HOOKS = frozenset({
    "reset_without_clearing", "hammer_commands_in_fault", "late_watchdog_kick",
})

#: Speed commanded during a campaign. Below the rated maximum so that normal
#: running is never itself a fault.
COMMAND_RPM = 5000


@dataclass(frozen=True)
class RunResult:
    """What the device did when one fault was injected."""

    fault_id: str
    reached_safe_state: bool
    detected_at_step: int | None
    final_state: str
    true_temperature_c: float
    sensed_temperature_c: float
    overheated_undetected: bool
    rejected_command: bool
    telemetry_readable: bool
    notes: str = ""

    @property
    def detected(self) -> bool:
        return self.reached_safe_state or self.rejected_command


def _arm(fault: Fault, dut: ActuatorFaultedController, tx: FaultyTransport) -> None:
    """Apply the fault named by the catalog entry, or fail loudly.

    An unknown hook is a hard error rather than a skip: a catalog entry that
    silently does nothing would inflate the coverage report, which is the one
    failure mode this project cannot tolerate.
    """
    if fault.hook in DEVICE_HOOKS:
        DEVICE_HOOKS[fault.hook](dut, **fault.params)
        return
    if fault.hook in TRANSPORT_HOOKS:
        TRANSPORT_HOOKS[fault.hook](tx, **fault.params)
        return
    if fault.hook in _BEHAVIOURAL_HOOKS:
        return          # applied by run(), not by arming state
    raise KeyError(
        f"{fault.id}: unknown injection hook {fault.hook!r}. A catalogued fault "
        f"that does not inject would count as covered while testing nothing."
    )


#: Hooks that are a campaign SHAPE rather than a state to arm: they change what
#: the supervisor does, not what the hardware is.
_BEHAVIOURAL_HOOKS = {
    "starve_watchdog",
    "late_watchdog_kick",
    "reset_without_clearing",
    "hammer_commands_in_fault",
    "read_telemetry_in_fault",
}


def run(fault: Fault, steps: int = RUN_STEPS) -> RunResult:
    """Inject one fault and observe the device for `steps` steps."""
    dut = ActuatorFaultedController()
    tx = FaultyTransport(SimTransport(dut, steps_per_request=0))
    driver = MotorControllerDriver(tx)

    _arm(fault, dut, tx)

    rejected = False
    reset_attempted = False
    telemetry_readable = True
    notes = ""

    # Commanding speed is itself part of the exposure: a fault that only shows
    # up on an idle drive is not interesting.
    try:
        driver.set_speed(COMMAND_RPM)
    except (ProtocolError, ValueError):
        # The command was refused, which for a corruption fault IS the
        # protection working.
        rejected = True
        notes = "command rejected on arrival"

    # Faults that need something already wrong before the behaviour under test
    # is meaningful, declared per fault in the catalog. Resetting a healthy
    # drive proves nothing, a safe state cannot be hammered until the drive is
    # in one, and a lying temperature sensor is only hazardous when the winding
    # is ACTUALLY cooking. Free running at 5000 rpm the winding equilibrates
    # around 62 C, well under the 140 C limit, so injecting a thermal sensor
    # fault there would measure a sensor lying about a motor that was never in
    # danger and would overstate nothing but also prove nothing.
    if fault.precondition == "stalled_rotor":
        dut.inject_stall(True)
    elif fault.precondition == "overloaded_rotor":
        # Twice rated torque: the machine still turns, so this is not a stall,
        # and it heats at four times rated because loss goes as current squared.
        # More likely in service than a locked rotor and much slower, which is
        # what makes it a different test rather than a weaker one.
        dut.load_torque_nm = RATED_TORQUE_NM * 2.0

    kicking = fault.hook not in {"starve_watchdog", "late_watchdog_kick"}
    # One step past the budget by default: the boundary case, where the kick is
    # as early as it can be and still be too late.
    late_kick_step = WATCHDOG_BUDGET + int(fault.params.get("late_by", 1))
    dut.handle_command(f"WDG_EN {WATCHDOG_BUDGET}")

    detected_at: int | None = None
    # The CAMPAIGN owns the clock, which is why the transport is built with
    # steps_per_request=0. By default SimTransport advances the device once per
    # request, so a loop iteration that sent a watchdog kick AND called step()
    # advanced it twice, and every latency this campaign reported was in units
    # of two device steps while every FTTI budget was written in one. The two
    # were compared directly. Found by validating the device against its data
    # sheet, which changed the thermal numbers enough to make the discrepancy
    # visible; it had been silently wrong since the first run.
    for step in range(1, steps + 1):
        # Kicks go through the FAULTY TRANSPORT, not straight to the controller.
        # Sending them directly would keep the watchdog fed across a dead link,
        # which silently defeats every liveness fault in the catalog: a silent
        # channel, a stale OK echo and a dropped command would all look healthy.
        if kicking or (fault.hook == "late_watchdog_kick" and step == late_kick_step):
            tx.request("WDG_KICK")

        dut.step(1)

        if fault.hook == "hammer_commands_in_fault" and dut.state == "FAULT":
            reply = dut.handle_command(f"SET_SPEED {COMMAND_RPM}")
            if not reply.startswith("ERR"):    # pragma: no cover
                # Only reachable if the DUT regresses and starts accepting
                # commands in its safe state. Kept as a live check rather than
                # deleted, and excluded from coverage rather than forced by a
                # test, because a test that forced it would be asserting
                # something about a mock instead of about the design.
                notes = "safe state accepted a speed command under sustained pressure"

        if (fault.hook == "reset_without_clearing" and dut.state == "FAULT"
                and not reset_attempted):
            # Reset ONCE, with the cause still present, then keep watching. The
            # requirement is that the drive trips AGAIN rather than running on,
            # so resetting every step would just oscillate and prove nothing.
            dut.handle_command("RESET")
            # The DUT's reset() also clears the injected stall, because the
            # stall is a test backdoor rather than physical state it models. A
            # mechanically jammed shaft plainly survives an electrical reset, so
            # re-apply it: otherwise this fault would test a controller that
            # magically unjams itself and would always pass.
            dut.inject_stall(True)
            # And resume the command. Reset alone leaves the drive idle with no
            # torque demand, so it would sit safely still and the fault would
            # look handled. The hazard is the supervisor RESUMING into a jam
            # that was never cleared, which is what has to trip again.
            dut.handle_command(f"SET_SPEED {COMMAND_RPM}")
            reset_attempted = True
            detected_at = None
            continue

        if dut.state == "FAULT" and detected_at is None:
            detected_at = step
            # Most faults are answered once the drive is safe, so the run stops.
            # These three are about what happens AFTER the safe state is entered,
            # so they must keep running: does it survive a reset with the cause
            # still present, sustained commanding, and a kick that arrives too
            # late. Breaking here would leave those claims unverified while the
            # report showed them green.
            if fault.hook not in _POST_SAFE_STATE_HOOKS:
                break

    if fault.hook == "late_watchdog_kick" and detected_at is not None:
        notes = ("the late kick did not revive the drive"
                 if dut.state == "FAULT"
                 else "A LATE KICK LEFT THE SAFE STATE, the fault did not latch")

    if fault.hook == "read_telemetry_in_fault":
        dut.trip_fault()
        telemetry_readable = dut.handle_command("GET_TEMP").startswith("OK")
        detected_at = detected_at or 1

    overheated_undetected = (
        dut.true_temperature_c >= OVERHEAT_LIMIT_C and dut.state != "FAULT"
    )
    if overheated_undetected:
        notes = (f"winding reached {dut.true_temperature_c:.0f} C while the sensor "
                 f"reported {dut.read_winding_c():.0f} C and the drive kept running")

    return RunResult(
        fault_id=fault.id,
        reached_safe_state=dut.state == "FAULT",
        detected_at_step=detected_at,
        final_state=dut.state,
        true_temperature_c=round(dut.true_temperature_c, 1),
        sensed_temperature_c=round(dut.read_winding_c(), 1),
        overheated_undetected=overheated_undetected,
        rejected_command=rejected,
        telemetry_readable=telemetry_readable,
        notes=notes,
    )


def run_all(faults: tuple[Fault, ...]) -> dict[str, RunResult]:
    return {fault.id: run(fault) for fault in faults}
