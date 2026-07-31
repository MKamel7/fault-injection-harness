"""The protection layer, verified in both profiles.

Two things are being checked here and they are easy to confuse. One is that the
layer works: it passes clean frames and refuses damaged ones. The other, which is
the point of the module, is that the two profiles are the same mechanism except
where they genuinely differ, and that the difference is where the standards
actually differ rather than where the implementation happened to.
"""

from __future__ import annotations

import pytest
from dut_sim.motor_controller import MotorControllerSim
from hypothesis import given
from hypothesis import strategies as st
from testbench.driver import SimTransport

from fih.catalog import load_catalog
from fih.protected_campaign import run_all_protected, run_protected
from fih.protection import (
    E2E,
    PROFILES,
    PROFISAFE,
    SEP,
    PeerEndpoint,
    ProtectedTransport,
    ProtectionError,
    crc8,
    message_id,
)

CATALOG = load_catalog()
COMMS = tuple(f for f in CATALOG if f.fault_class == "communication")
PROFILE_LIST = list(PROFILES.values())
PROFILE_IDS = list(PROFILES)


def _stack(profile, answer_instead=None):  # type: ignore[no-untyped-def]
    peer = PeerEndpoint(SimTransport(MotorControllerSim()), profile,
                        answer_instead=answer_instead)
    return ProtectedTransport(peer, profile)


# --- the layer must not break the working case -------------------------------
@pytest.mark.parametrize("profile", PROFILE_LIST, ids=PROFILE_IDS)
def test_a_clean_link_passes_every_frame(profile) -> None:  # type: ignore[no-untyped-def]
    """A protection layer that rejects good traffic is worse than none."""
    tx = _stack(profile)
    for _ in range(40):
        assert tx.request("SET_SPEED 3000").startswith("OK")
    assert not tx.timed_out
    assert tx.rejections == []


@pytest.mark.parametrize("profile", PROFILE_LIST, ids=PROFILE_IDS)
def test_the_counter_wraps_without_a_false_rejection(profile) -> None:  # type: ignore[no-untyped-def]
    """E2E's counter is 4 bits, so it wraps every 16 frames.

    Wrap is where sequence checks classically produce a false positive, and a
    safety layer that trips on healthy traffic gets switched off by whoever is
    on call.
    """
    tx = _stack(profile)
    for _ in range((1 << E2E.counter_bits) * 3):
        tx.request("GET_TEMP")
    assert tx.rejections == []


# --- corruption --------------------------------------------------------------
@pytest.mark.parametrize("profile", PROFILE_LIST, ids=PROFILE_IDS)
@given(position=st.integers(min_value=0, max_value=30),
       replacement=st.characters(min_codepoint=33, max_codepoint=126))
def test_any_single_character_change_is_caught(profile, position: int,  # type: ignore[no-untyped-def]
                                               replacement: str) -> None:
    """Property, not example: change one character anywhere, it must be refused.

    A checksum tested against three hand picked corruptions proves very little.
    Searched corruption is what distinguishes a real check from a checksum that
    happens to differ on the cases someone thought of.
    """
    body = f"SET_SPEED 3000{SEP}5{SEP}{message_id(profile, 'SET_SPEED')}"
    frame = f"{body}{SEP}{crc8(body.encode()):02X}"
    if position >= len(frame) or frame[position] == replacement:
        return
    mutated = frame[:position] + replacement + frame[position + 1:]

    class _Wire:
        def request(self, line: str) -> str:
            return mutated

    tx = ProtectedTransport(_Wire(), profile)
    with pytest.raises(ProtectionError):
        tx.request("SET_SPEED 3000")


@pytest.mark.parametrize("profile", PROFILE_LIST, ids=PROFILE_IDS)
def test_an_unframed_reply_is_refused(profile) -> None:  # type: ignore[no-untyped-def]
    class _Wire:
        def request(self, line: str) -> str:
            return "OK"

    tx = ProtectedTransport(_Wire(), profile)
    with pytest.raises(ProtectionError, match="ERROR"):
        tx.request("SET_SPEED 3000")


# --- sequence ----------------------------------------------------------------
@pytest.mark.parametrize("profile", PROFILE_LIST, ids=PROFILE_IDS)
def test_a_repeated_frame_is_distinguished_from_a_wrong_one(profile) -> None:  # type: ignore[no-untyped-def]
    """REPEATED and WRONG_SEQUENCE are separate E2E states for a reason.

    They call for different reactions, so collapsing them into "bad frame" would
    discard the part the standard exists to provide.
    """
    frames: list[str] = []

    class _Wire:
        def __init__(self) -> None:
            self.peer = PeerEndpoint(SimTransport(MotorControllerSim()), profile)
            self.replay = False

        def request(self, line: str) -> str:
            reply = self.peer.request(line)
            frames.append(reply)
            return frames[0] if self.replay else reply

    wire = _Wire()
    tx = ProtectedTransport(wire, profile)
    tx.request("GET_TEMP")
    wire.replay = True
    with pytest.raises(ProtectionError) as repeated:
        tx.request("GET_TEMP")
    assert repeated.value.status == "REPEATED"

    with pytest.raises(ProtectionError) as wrong:
        tx.request("GET_TEMP")
    assert wrong.value.status == "WRONG_SEQUENCE"


@pytest.mark.parametrize("profile", PROFILE_LIST, ids=PROFILE_IDS)
def test_silence_is_declared_lost_after_the_timeout_budget(profile) -> None:  # type: ignore[no-untyped-def]
    class _Wire:
        def request(self, line: str) -> str:
            return ""

    tx = ProtectedTransport(_Wire(), profile)
    for _ in range(profile.timeout_steps):
        with pytest.raises(ProtectionError):
            tx.request("GET_TEMP")
    assert tx.timed_out, f"{profile.name}: silence never reached {profile.timeout_term}"


# --- the campaign, and the asymmetry -----------------------------------------
@pytest.mark.parametrize("fault", COMMS, ids=[f.id for f in COMMS])
@pytest.mark.parametrize("profile", PROFILE_LIST, ids=PROFILE_IDS)
def test_the_protected_campaign_is_deterministic(fault, profile) -> None:  # type: ignore[no-untyped-def]
    assert run_protected(fault, profile) == run_protected(fault, profile)


def test_every_communication_fault_except_the_masquerade_is_caught() -> None:
    results = run_all_protected(CATALOG)
    for fault in COMMS:
        for key in PROFILES:
            got = results[f"{fault.id}/{key}"]
            if fault.id == "FLT-C08" and key == "profisafe":
                continue
            assert got.detected, f"{fault.id} under {key}: {got.detail}"


def test_e2e_catches_the_masquerade_and_profisafe_does_not() -> None:
    """The headline of the cross domain comparison, pinned by test.

    This is not an implementation quirk. An E2E Data ID identifies a data
    element, so a reply about the wrong quantity carries the wrong one. A
    PROFIsafe F_Destination_Address identifies a device, so every message on the
    link carries the same one and the reply passes. If a refactor makes these two
    agree, the mapping document has become wrong and this test should say so.
    """
    results = run_all_protected(CATALOG)
    assert results["FLT-C08/e2e"].detected
    assert results["FLT-C08/e2e"].status == "WRONG_ID"
    assert not results["FLT-C08/profisafe"].detected


def test_the_profiles_are_configuration_not_forks() -> None:
    """Same mechanism, different names. Only the documented fields differ."""
    differing = {k for k, v in vars(E2E).items() if vars(PROFISAFE)[k] != v}
    assert differing == {
        "name", "checksum_term", "counter_term", "endpoint_term", "timeout_term",
        "counter_bits", "id_per_message",
    }, f"the profiles diverge in an undocumented way: {differing}"


@pytest.mark.parametrize("profile", PROFILE_LIST, ids=PROFILE_IDS)
def test_a_valid_checksum_over_a_nonsense_counter_is_still_refused(profile) -> None:  # type: ignore[no-untyped-def]
    """The checksum passing does not mean the fields are readable.

    A sender that computes its CRC correctly over garbage produces a frame that
    survives the checksum and then has to be refused on parsing. Skipping this
    check would mean an exception escaping the protection layer as a ValueError
    instead of a refusal the application can react to.
    """
    body = f"SET_SPEED 3000{SEP}not-a-number{SEP}{profile.endpoint_id}"
    frame = f"{body}{SEP}{crc8(body.encode()):02X}"

    class _Wire:
        def request(self, line: str) -> str:
            return frame

    tx = ProtectedTransport(_Wire(), profile)
    with pytest.raises(ProtectionError, match="unreadable counter or endpoint"):
        tx.request("SET_SPEED 3000")
