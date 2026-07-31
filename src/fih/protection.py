"""One CRC plus counter plus timeout layer, configured two ways.

AUTOSAR E2E and PROFIsafe are, mechanically, the same idea. Both protect a
payload with a checksum, a sequence counter and a timeout, and both bind the
frame to its intended endpoint with an identifier so that a well formed message
arriving from the wrong place is still rejected. They come from different worlds,
automotive and industrial, and they use entirely different words for it. That is
the whole point of this module: **one implementation, two profiles**, so the
vocabulary can be laid side by side and seen to describe the same three
mechanisms.

    concept                 AUTOSAR E2E              PROFIsafe (IEC 61784-3)
    ------------------------------------------------------------------------
    checksum                CRC                      CRC2
    sequence counter        Alive Counter            Consecutive Number
    endpoint binding        Data ID                  F_Destination_Address
    timeout                 max delta counter        F_WD_Time
    verdict                 E2E state (OK, REPEATED, safety telegram valid or
                            WRONG_SEQUENCE, ERROR)   the F-Host goes to passivation

HONESTY, because this is the part that gets overclaimed. This is a **model of
the mechanism**, not an implementation of either standard. Real E2E Profile 1
specifies CRC8 over SAE J1850 with a 4 bit alive counter; real PROFIsafe V2 uses
a wider CRC and a 24 bit consecutive number, computed over the F-Parameters as
well as the data. Both standards are paid documents and neither is implemented
here. What is implemented is the shared skeleton, parameterised, so that the same
fault set can be run through both framings and the results compared.

The layer sits ABOVE the wire and BELOW the application, exactly as it does on a
real bus:

    ProtectedTransport   (initiator: wraps outgoing, checks incoming)
      -> FaultyTransport (the wire, where faults live)
        -> PeerEndpoint  (responder: checks incoming, wraps outgoing)
          -> SimTransport

Faults are therefore injected on the frame, not on the payload, which is the
only arrangement that tests anything: a fault injected above the protection
layer would simply be protected data that was already wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

from fih.injection.transport import Transport

#: Frame layout: payload | counter | endpoint id | checksum
SEP = "|"


@dataclass(frozen=True)
class Profile:
    """One naming and sizing of the shared mechanism."""

    name: str
    #: What the standard calls each field. Used in diagnostics so a failure
    #: reads in the vocabulary of the domain it came from.
    checksum_term: str
    counter_term: str
    endpoint_term: str
    timeout_term: str
    #: THE ASYMMETRY between the two profiles, and the most interesting thing
    #: this module demonstrates. An E2E Data ID identifies a DATA ELEMENT, so
    #: every protected signal has its own, and a reply about the wrong signal
    #: fails the check. A PROFIsafe F_Destination_Address identifies a DEVICE,
    #: so every message on a link carries the same one, and a reply about the
    #: wrong signal from the right device passes. The mechanisms are usually
    #: presented as equivalent. They are not, and FLT-C08 shows it.
    id_per_message: bool
    #: Sequence counter width. E2E Profile 1 uses 4 bits; PROFIsafe V2 uses 24.
    counter_bits: int
    #: Binds a frame to its intended endpoint. This is the field that makes a
    #: masquerading reply detectable, and the bare protocol has no equivalent.
    endpoint_id: int
    #: Steps without a valid frame before the receiver declares loss.
    timeout_steps: int


E2E = Profile(
    name="AUTOSAR E2E",
    checksum_term="CRC",
    counter_term="Alive Counter",
    endpoint_term="Data ID",
    timeout_term="max delta counter",
    counter_bits=4,
    endpoint_id=0x2A,
    timeout_steps=10,
    id_per_message=True,
)

PROFISAFE = Profile(
    name="PROFIsafe",
    checksum_term="CRC2",
    counter_term="Consecutive Number",
    endpoint_term="F_Destination_Address",
    timeout_term="F_WD_Time",
    counter_bits=24,
    endpoint_id=0x2A,
    timeout_steps=10,
    id_per_message=False,
)

PROFILES = {"e2e": E2E, "profisafe": PROFISAFE}


class ProtectionError(Exception):
    """A frame the protection layer refused, carrying the reason.

    The reason is not decoration. E2E defines distinct states because they call
    for different reactions: a REPEATED frame may be tolerated briefly, an ERROR
    frame never is. Collapsing them into "bad frame" would throw away the part
    the standard exists to provide.
    """

    def __init__(self, status: str, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


def crc8(data: bytes) -> int:
    """CRC8 with the SAE J1850 polynomial 0x1D, as E2E Profile 1 specifies.

    Chosen over a simpler checksum because the property under test is that
    corruption is caught, and a sum is defeated by transposition. Both profiles
    use this implementation; the real standards differ in width, which is noted
    in the module docstring rather than pretended away.
    """
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1D) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc ^ 0xFF


def message_id(profile: Profile, payload: str) -> int:
    """The identifier carried in the frame, per the profile's rules.

    Per data element for E2E, per device for PROFIsafe. The command word is what
    identifies the data element here, since each command carries a different
    quantity.
    """
    if not profile.id_per_message:
        return profile.endpoint_id
    command = payload.strip().split(" ", 1)[0].upper()
    return profile.endpoint_id ^ crc8(command.encode())


def _wrap(profile: Profile, payload: str, counter: int, ident: int) -> str:
    body = f"{payload}{SEP}{counter}{SEP}{ident}"
    return f"{body}{SEP}{crc8(body.encode()):02X}"


def _unwrap(profile: Profile, frame: str, expect_id: int) -> tuple[str, int]:
    """Return (payload, counter) or raise ProtectionError.

    Checks run in the order a receiver can perform them: structure, then
    checksum, then endpoint, then sequence. Anything after a failed checksum is
    reading fields that may not mean what they appear to.
    """
    parts = frame.rsplit(SEP, 3)
    if len(parts) != 4:
        raise ProtectionError("ERROR", f"frame is not {profile.name} shaped: {frame!r}")
    payload, counter_s, endpoint_s, checksum_s = parts

    body = f"{payload}{SEP}{counter_s}{SEP}{endpoint_s}"
    try:
        given = int(checksum_s, 16)
    except ValueError:
        raise ProtectionError("ERROR", f"unreadable {profile.checksum_term}") from None
    if given != crc8(body.encode()):
        raise ProtectionError("ERROR", f"{profile.checksum_term} mismatch")

    try:
        counter, endpoint = int(counter_s), int(endpoint_s)
    except ValueError:
        raise ProtectionError("ERROR", "unreadable counter or endpoint") from None

    if endpoint != expect_id:
        # The masquerade case. A checksum cannot catch this: the frame is
        # perfectly well formed and perfectly intact, it is simply about
        # something other than what was asked.
        raise ProtectionError(
            "WRONG_ID",
            f"{profile.endpoint_term} {endpoint} is not the expected {expect_id}",
        )
    return payload, counter


class PeerEndpoint:
    """The responder's half. Unwraps a request, answers, wraps the reply.

    Modelled explicitly rather than folded into the initiator because both ends
    of a real link run the protection library, and the fault is injected
    BETWEEN them. Collapsing the two would leave nothing for a fault to corrupt.
    """

    def __init__(self, inner: Transport, profile: Profile,
                 answer_instead: str | None = None) -> None:
        self._inner = inner
        self._profile = profile
        #: Masquerade is modelled HERE rather than on the wire, because that is
        #: where it happens: a reply about the wrong quantity comes from a
        #: responder, or from another node answering in its place. A wire cannot
        #: manufacture a correctly checksummed frame.
        self._answer_instead = answer_instead

    def request(self, line: str) -> str:
        payload, counter = _unwrap(self._profile, line,
                                   message_id(self._profile, line.split(SEP)[0]))
        answered = self._answer_instead or payload
        reply = self._inner.request(answered)
        # The counter is echoed rather than run independently. In a request and
        # response protocol that is what binds a reply to its request, and it is
        # what makes a stale echo detectable on arrival instead of only once the
        # watchdog expires. The identifier is derived from the question actually
        # ANSWERED, not the one asked, which is what exposes a masquerade.
        return _wrap(self._profile, reply, counter,
                     message_id(self._profile, answered))


class ProtectedTransport:
    """The initiator's half. The layer the application talks to."""

    def __init__(self, inner: Transport, profile: Profile) -> None:
        self._inner = inner
        self._profile = profile
        self._modulus = 1 << profile.counter_bits
        self._counter = 0
        self.since_valid = 0
        #: Every rejection, in order, for the report.
        self.rejections: list[ProtectionError] = []

    def request(self, line: str) -> str:
        sent = self._counter
        self._counter = (self._counter + 1) % self._modulus
        ident = message_id(self._profile, line)
        try:
            frame = self._inner.request(_wrap(self._profile, line, sent, ident))
            payload, got = _unwrap(self._profile, frame, ident)
            if got != sent:
                # REPEATED and WRONG_SEQUENCE are separate states in E2E, and
                # separate reactions: an exact repeat is a stuck sender, a
                # mismatch is a reply to some other request entirely.
                status = "REPEATED" if got == (sent - 1) % self._modulus else "WRONG_SEQUENCE"
                raise ProtectionError(
                    status,
                    f"{self._profile.counter_term} {got} for request {sent}",
                )
        except ProtectionError as err:
            self.rejections.append(err)
            self.since_valid += 1
            raise
        self.since_valid = 0
        return payload

    @property
    def timed_out(self) -> bool:
        """True once nothing valid has arrived within the timeout budget."""
        return self.since_valid >= self._profile.timeout_steps
