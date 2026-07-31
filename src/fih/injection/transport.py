"""Communication faults, injected by decorating the transport.

P1 defines `Transport` as a protocol with a single `request(line) -> str`, which
is the seam a real bus fault would sit on: between the thing issuing commands
and the thing executing them. Decorating it means the controller is untouched
and unaware, exactly as it would be on real hardware.

Layer order matters and is the reason this is a decorator rather than a flag on
the driver:

    driver -> [protection] -> [faults] -> transport -> controller

Faults inject BENEATH any protection layer, so the protection sees a corrupted
wire and has to catch it, rather than being handed a clean frame and asked to
pretend. Getting this backwards would make the protection layer look perfect and
prove nothing.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Protocol

#: Frame field separator, shared with fih.protection. Defined here rather than
#: imported to keep the wire layer free of any dependency on the layer above it.
SEP = "|"


class Transport(Protocol):
    def request(self, line: str) -> str: ...


class FaultyTransport:
    """Wraps a transport and applies one armed communication fault.

    Deliberately holds at most one fault: a campaign that injects several at
    once cannot attribute a detection to any of them, and attribution is the
    entire output of this project.
    """

    def __init__(self, inner: Transport) -> None:
        self.inner = inner
        self.corrupt_to: str | None = None
        self.silent = False
        self.stale_ok = False
        self.truncate = False
        self.drop = False
        self.delay_steps = 0
        self.masquerade = False
        self._delayed: deque[str] = deque()
        self.calls = 0

    def request(self, line: str) -> str:
        self.calls += 1

        if self.corrupt_to is not None and line.strip().upper().startswith("SET_SPEED"):
            # Corrupt the PAYLOAD and leave any protection trailer untouched.
            # Rewriting the whole frame would be caught by its shape rather than
            # by its checksum, which would flatter the protection layer: it
            # would appear to detect corruption while actually only detecting
            # that something was no longer a frame.
            _, sep, trailer = line.partition(SEP)
            line = f"SET_SPEED {self.corrupt_to}{sep}{trailer}"

        if self.silent:
            # The far end is gone. A real link would time out; the driver sees
            # a response it cannot frame.
            return ""

        if self.stale_ok:
            # Well formed, successful, and never delivered. Every protocol level
            # check passes. This is the fault that separates "the reply was
            # valid" from "the device is alive".
            return "OK"

        if self.drop:
            return "OK"

        if self.masquerade:
            # A reply meant for another request. The real command IS delivered,
            # so liveness is untouched: this isolates "the reply is not bound to
            # the request" from "the command never arrived". Conflating the two
            # would let the watchdog catch it and hide the fact that nothing in
            # the protocol binds a reply to its cause.
            self.inner.request(line)
            other = "GET_TEMP" if "GET_TEMP" not in line.upper() else "GET_SPEED"
            return self.inner.request(other)

        response = self.inner.request(line)

        if self.truncate:
            return response[: max(len(response) - 2, 0)]

        if self.delay_steps > 0:
            # Replies still arrive, and are still correct, just too late to be
            # useful. Correctness and timeliness are separate properties.
            self._delayed.append(response)
            if len(self._delayed) <= self.delay_steps:
                return ""
            return self._delayed.popleft()

        return response


# --- hooks ------------------------------------------------------------------

def corrupt_speed_argument(tx: FaultyTransport, to_rpm: float | None = None,
                           to_literal: str | None = None) -> None:
    tx.corrupt_to = to_literal if to_literal is not None else str(to_rpm)


def silence_channel(tx: FaultyTransport) -> None:
    tx.silent = True


def stale_ok_echo(tx: FaultyTransport) -> None:
    tx.stale_ok = True


def truncate_response(tx: FaultyTransport) -> None:
    tx.truncate = True


def drop_command(tx: FaultyTransport) -> None:
    tx.drop = True


def delay_response(tx: FaultyTransport, steps: int) -> None:
    tx.delay_steps = int(steps)


def masquerade_response(tx: FaultyTransport) -> None:
    tx.masquerade = True


#: Same contract as DEVICE_HOOKS, for faults that live on the wire.
TRANSPORT_HOOKS: dict[str, Callable[..., None]] = {
    "corrupt_speed_argument": corrupt_speed_argument,
    "silence_channel": silence_channel,
    "stale_ok_echo": stale_ok_echo,
    "truncate_response": truncate_response,
    "drop_command": drop_command,
    "delay_response": delay_response,
    "masquerade_response": masquerade_response,
}
