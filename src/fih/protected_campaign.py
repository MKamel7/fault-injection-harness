"""Run the communication faults again, this time through the protection layer.

The bare campaign in `campaign.py` answers "what does the device detect". This
one answers a different and more useful question: **what does adding a standard
end to end protection layer actually buy**, fault by fault, and where does it buy
nothing.

Both answers matter. A layer that catches everything would be suspicious, and a
layer whose benefit is asserted rather than measured is a diagram, not evidence.

Only the communication faults are re-run. Sensor, actuator and timing faults are
inside the device, and a protection layer on the link between supervisor and
device cannot see them by construction. Running them here to produce a row of
"not detected" would pad the table and imply the layer had been given a fair
chance at something it was never meant to address.
"""

from __future__ import annotations

from dataclasses import dataclass

from dut_sim.motor_controller import MotorControllerSim
from testbench.driver import SimTransport

from fih.catalog import Fault
from fih.injection.transport import TRANSPORT_HOOKS, FaultyTransport
from fih.protection import (
    PROFILES,
    PeerEndpoint,
    Profile,
    ProtectedTransport,
    ProtectionError,
)

#: Exchanges per run. Well past the timeout budget, so a fault that is only
#: caught by the timeout still gets caught.
EXCHANGES = 15

#: The command driven during a protected run. Same as the bare campaign, so the
#: two tables compare like with like.
COMMAND = "SET_SPEED 5000"


@dataclass(frozen=True)
class ProtectedResult:
    """What the protection layer did with one fault, under one profile."""

    fault_id: str
    profile: str
    detected: bool
    #: Which exchange first raised, 1 based. None if the fault was never caught.
    detected_at: int | None
    #: The profile's own verdict term: ERROR, REPEATED, WRONG_SEQUENCE, WRONG_ID.
    status: str | None
    detail: str
    timed_out: bool


def _build(fault: Fault, profile: Profile) -> ProtectedTransport:
    """Assemble initiator -> wire -> responder -> device for one fault."""
    device = SimTransport(MotorControllerSim())

    # Masquerade is armed at the RESPONDER, not on the wire. A wire can corrupt
    # a frame but it cannot manufacture a correctly checksummed one, so a fault
    # that produces a valid frame about the wrong quantity has to originate at a
    # node. Arming it on the wire would only ever produce a checksum failure and
    # would test the CRC a second time instead of testing the identifier.
    answer_instead = "GET_TEMP" if fault.hook == "masquerade_response" else None
    peer = PeerEndpoint(device, profile, answer_instead=answer_instead)

    wire = FaultyTransport(peer)
    if fault.hook in TRANSPORT_HOOKS and answer_instead is None:
        TRANSPORT_HOOKS[fault.hook](wire, **fault.params)

    return ProtectedTransport(wire, profile)


def run_protected(fault: Fault, profile: Profile) -> ProtectedResult:
    """Drive one fault through the protected stack and record the first refusal."""
    tx = _build(fault, profile)

    for exchange in range(1, EXCHANGES + 1):
        try:
            tx.request(COMMAND)
        except ProtectionError as err:
            return ProtectedResult(
                fault_id=fault.id, profile=profile.name, detected=True,
                detected_at=exchange, status=err.status, detail=err.detail,
                timed_out=tx.timed_out,
            )
    return ProtectedResult(
        fault_id=fault.id, profile=profile.name, detected=False, detected_at=None,
        status=None, detail="accepted every frame", timed_out=tx.timed_out,
    )


def run_all_protected(faults: tuple[Fault, ...]) -> dict[str, ProtectedResult]:
    """Every communication fault, under every profile. Key is 'FLT-Cxx/e2e'."""
    out: dict[str, ProtectedResult] = {}
    for fault in faults:
        if fault.fault_class != "communication":
            continue
        for key, profile in PROFILES.items():
            out[f"{fault.id}/{key}"] = run_protected(fault, profile)
    return out
