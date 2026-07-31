"""Sensor and actuator faults, injected by subclassing the device under test.

The DUT is a pinned dependency and is never edited, so faults arrive the same
way P1's own seeded defects do: a subclass. That keeps the vendored original
independently verifiable, which matters because evidence about a modified DUT is
evidence about something other than the shipped device.

The important modelling decision is here. A real controller does not know the
winding temperature, it knows what the sensor reports. P1's controller conflates
the two: `temperature_c` is both the physical state and the reading its
protection trips on. A sensor fault is only meaningful once those are separated,
so `SensorFaultedController` keeps a true temperature and publishes a possibly
lying sensed value into the field the inherited protection reads.

That separation is what makes "the sensor says everything is fine while the
winding cooks" expressible at all, and it is the whole point of SR-10.
"""

from __future__ import annotations

from collections.abc import Callable

from dut_sim.motor_controller import MotorControllerSim


class SensorFaultedController(MotorControllerSim):
    """A controller whose temperature and speed sensors can misreport.

    `temperature_c` (what the inherited protection trips on) becomes the SENSED
    value. The physical winding temperature is tracked separately in
    `true_temperature_c`, so the campaign can compare what the device believed
    with what was actually happening.
    """

    def __init__(self) -> None:
        super().__init__()
        self.true_temperature_c: float = self.temperature_c
        self.temp_stuck_at: float | None = None
        self.temp_bias_c: float = 0.0
        self.speed_stuck_at: float | None = None

    def _sensed(self, true_value: float) -> float:
        if self.temp_stuck_at is not None:
            return self.temp_stuck_at
        return true_value + self.temp_bias_c

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            # The DUT's own physics and its own trip logic stay authoritative:
            # this must verify the shipped controller, not a reimplementation of
            # it. So the sensed value is written into the field the inherited
            # protection reads, the DUT is stepped, and the physical increment it
            # produced is then applied to the true temperature.
            #
            # Doing it the other way round (stepping on the true value and
            # publishing sensed afterwards) makes the protection trip on physics
            # the device cannot actually observe, which would quietly make every
            # sensor fault look detected.
            true = self.true_temperature_c
            self.temperature_c = self._sensed(true)
            before = self.temperature_c
            super().step(1)
            # Approximation worth naming: the increment is computed at the sensed
            # temperature, so the cooling term uses the sensed value rather than
            # the true one. Immaterial next to the fault being modelled.
            self.true_temperature_c = true + (self.temperature_c - before)
            self.temperature_c = self._sensed(self.true_temperature_c)
            if self.speed_stuck_at is not None:
                self.speed_rpm = self.speed_stuck_at

    def reset(self) -> None:
        super().reset()
        # A reset clears the controller, not the broken hardware attached to it.
        self.true_temperature_c = self.temperature_c
        self.temperature_c = self._sensed(self.true_temperature_c)


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
    "speed_feedback_stuck": speed_feedback_stuck,
    "stall_rotor": stall_rotor,
    "torque_loss": torque_loss,
}
