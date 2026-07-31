"""Sensor and actuator faults, injected by subclassing the device under test.

The DUT is a pinned dependency and is never edited, so faults arrive the same
way P1's own seeded defects do: a subclass. That keeps the vendored original
independently verifiable, which matters because evidence about a modified DUT is
evidence about something other than the shipped device.

The important modelling decision is here. A real controller does not know the
winding temperature, it knows what a sensor reports, and a sensor fault is only
expressible once those two are separate things. Since DUT v1.5 the controller
provides that separation itself: `temperature_c` is the physical state and
`read_winding_c()` is the measurement the protection trips on. Injecting a lying
sensor is therefore a one line override of the READ, and the physics is never
touched.

That matters more than it looks. Editing `temperature_c` would simulate a cool
motor rather than a broken sensor, and the protection would be right to stay
quiet; the fault would appear undetectable for the wrong reason. Overriding the
read keeps the motor genuinely hot and the controller genuinely blind, which is
the condition SR-10 is about.

Before v1.5 this had to be done by transplanting temperature increments between a
true and a sensed field, because the DUT had no seam. That worked for a single
sensor and broke the moment a SECOND one existed: the second node followed the
lie instead of the motor, so a cross check between them could never fire.
"""

from __future__ import annotations

from collections.abc import Callable

from dut_sim.motor_controller import MotorControllerSim


class SensorFaultedController(MotorControllerSim):
    """A controller whose winding and speed sensors can misreport.

    The fault lives in the measurement. `temperature_c` remains the physical
    winding temperature and the DUT's own physics and trip logic stay
    authoritative throughout, because this has to verify the shipped controller
    rather than a reimplementation of it.

    The FRAME sensor is deliberately left honest. A campaign that broke both
    channels at once would be injecting a common cause failure and calling it a
    sensor fault, and the redundancy it exists to test would never get a turn.
    Common cause belongs in the catalog as its own entry, not smuggled into
    every sensor fault.
    """

    def __init__(self) -> None:
        super().__init__()
        self.temp_stuck_at: float | None = None
        self.temp_bias_c: float = 0.0
        self.housing_stuck_at: float | None = None
        self.speed_stuck_at: float | None = None

    def read_winding_c(self) -> float:
        true = super().read_winding_c()
        if self.temp_stuck_at is not None:
            return self.temp_stuck_at
        return true + self.temp_bias_c

    def read_housing_c(self) -> float:
        # Only faulted by the COMMON CAUSE entry. Every other sensor fault
        # leaves this channel honest, so the redundancy gets a fair test.
        if self.housing_stuck_at is not None:
            return self.housing_stuck_at
        return super().read_housing_c()

    @property
    def true_temperature_c(self) -> float:
        """The physical winding temperature, named for the campaign's report.

        Kept as an alias rather than a second field so there is exactly one
        place the truth lives. Two fields is how the true and sensed values
        drifted apart in the first place.
        """
        return self.temperature_c

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            super().step(1)
            if self.speed_stuck_at is not None:
                # No sensor seam for speed in the DUT, so this is still applied
                # after the fact. It is why FLT-S04 remains residual: there is
                # one speed source and nothing to disagree with it.
                self.speed_rpm = self.speed_stuck_at


class ActuatorFaultedController(SensorFaultedController):
    """Adds actuator faults: a blocked rotor, or torque that never arrives."""

    def __init__(self) -> None:
        super().__init__()
        self.torque_lost: bool = False

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            if self.torque_lost:
                # The controller believes it is driving; the shaft disagrees.
                # Nothing in the item can tell, which is the point of FLT-A02.
                target, self.target_rpm = self.target_rpm, 0.0
                super().step(1)
                self.target_rpm = target
            else:
                super().step(1)


# --- hooks ------------------------------------------------------------------
# Each takes the controller and the catalog params, and arms the fault. Keeping
# them tiny and named after catalog hooks is what lets the catalog stay data.

def temperature_stuck(dut: SensorFaultedController, at_c: float) -> None:
    dut.temp_stuck_at = float(at_c)


def temperature_bias(dut: SensorFaultedController, offset_c: float) -> None:
    dut.temp_bias_c = float(offset_c)


def housing_stuck(dut: SensorFaultedController, at_c: float) -> None:
    """The FRAME sensor alone misreports.

    The failure mode adding a second channel introduced. It went uncatalogued
    until a review pointed out that the only entry touching this sensor failed
    both channels at once, so the entire failure space of the newly added
    component was untested.
    """
    dut.housing_stuck_at = float(at_c)


def both_temperatures_stuck(dut: SensorFaultedController, at_c: float) -> None:
    """Both thermal channels report the same safe value.

    The failure redundancy cannot answer. Two sensors are two channels only
    while they fail independently; a shared supply, a shared ADC reference, a
    shared harness or a shared connector makes them one channel wearing two
    names, and the cross check between them agrees perfectly all the way to
    destruction.
    """
    dut.temp_stuck_at = float(at_c)
    dut.housing_stuck_at = float(at_c)


def speed_feedback_stuck(dut: SensorFaultedController, at_rpm: float) -> None:
    dut.speed_stuck_at = float(at_rpm)


def stall_rotor(dut: ActuatorFaultedController) -> None:
    dut.inject_stall(True)


def torque_loss(dut: ActuatorFaultedController) -> None:
    dut.torque_lost = True


#: Hook name from the catalog -> the function that arms it. Typed loosely on
#: purpose: the params come from YAML, so the arity varies per hook and the
#: catalog loader is what validates them.
DEVICE_HOOKS: dict[str, Callable[..., None]] = {
    "temperature_stuck": temperature_stuck,
    "temperature_bias": temperature_bias,
    "housing_stuck": housing_stuck,
    "both_temperatures_stuck": both_temperatures_stuck,
    "speed_feedback_stuck": speed_feedback_stuck,
    "stall_rotor": stall_rotor,
    "torque_loss": torque_loss,
}
