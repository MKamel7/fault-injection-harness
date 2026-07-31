"""Tests for the verdict logic and the generated report.

The report is the deliverable, so its failure modes matter more than usual. It
must be wrong in neither direction: it must not claim detection that did not
happen, and it must not quietly absorb good news either, because a residual
entry that the design has since started catching is a stale rationale.
"""

from __future__ import annotations

import dataclasses

from fih.campaign import RunResult, run_all
from fih.catalog import load_catalog
from fih.report import build, verdict
from fih.traceability import load_requirements

CATALOG = load_catalog()
REQUIREMENTS = load_requirements()
BY_ID = {f.id: f for f in CATALOG}


def _result(**kw: object) -> RunResult:
    """A synthetic run. `detected` is derived, so it is set via its inputs."""
    base = RunResult(
        fault_id="FLT-X", reached_safe_state=True, detected_at_step=1,
        final_state="STO", true_temperature_c=40.0, sensed_temperature_c=40.0,
        overheated_undetected=False, rejected_command=False,
        telemetry_readable=True, notes="",
    )
    return dataclasses.replace(base, **kw)  # type: ignore[arg-type]


def test_detection_later_than_the_ftti_budget_fails() -> None:
    """Detection alone is not the requirement. Detection in time is."""
    fault = BY_ID["FLT-C01"]
    assert fault.ftti_steps is not None
    ok, why = verdict(fault, _result(detected_at_step=fault.ftti_steps + 1))
    assert not ok
    assert "over the" in why


def test_detection_inside_the_budget_passes() -> None:
    fault = BY_ID["FLT-C01"]
    ok, _ = verdict(fault, _result(detected_at_step=fault.ftti_steps))
    assert ok


def test_rejected_on_arrival_counts_as_zero_steps() -> None:
    fault = BY_ID["FLT-C01"]
    ok, why = verdict(fault, _result(detected_at_step=None))
    assert ok and "rejected on arrival" in why


def test_undetected_fault_fails_its_verdict() -> None:
    ok, why = verdict(BY_ID["FLT-C01"], _result(reached_safe_state=False, detected_at_step=None))
    assert not ok and why == "not detected"


def test_residual_fault_that_gets_detected_is_a_failure() -> None:
    """Good news is still a report defect until the rationale is updated."""
    ok, why = verdict(BY_ID["FLT-S05"], _result(reached_safe_state=True))
    assert not ok and "stale" in why


def test_residual_fault_passes_by_staying_undetected() -> None:
    ok, _ = verdict(BY_ID["FLT-S05"], _result(reached_safe_state=False, detected_at_step=None))
    assert ok


# --- the rendered document ---------------------------------------------------
def test_report_builds_and_every_verdict_is_met() -> None:
    text, all_ok = build(CATALOG, run_all(CATALOG), REQUIREMENTS)
    assert all_ok, "a catalogued fault no longer meets its verdict"
    for fault in CATALOG:
        assert fault.id in text, f"{fault.id} is missing from the report"
    assert "FAIL" not in text


def test_report_refuses_the_iso_diagnostic_coverage_claim() -> None:
    """The wording is load bearing, so it is asserted rather than trusted.

    Detection coverage over an injected fault set and ISO 26262 diagnostic
    coverage get conflated constantly, and an assessor checks. If someone
    reworded this section, the build should tell them what they just claimed.
    """
    text, _ = build(CATALOG, run_all(CATALOG), REQUIREMENTS)
    assert "not** diagnostic coverage" in text
    assert "FMEDA" in text
    assert "simulation steps" in text


def test_report_names_every_residual_fault_with_its_rationale() -> None:
    text, _ = build(CATALOG, run_all(CATALOG), REQUIREMENTS)
    for fault in CATALOG:
        if fault.is_residual:
            assert fault.residual_rationale is not None
            assert fault.residual_rationale[:40] in text, (
                f"{fault.id} is residual but its rationale is not in the report"
            )


def test_every_requirement_now_has_at_least_one_detecting_fault() -> None:
    """SR-10 used to be listed here as unmet. The second source closed it.

    The section is still generated and still tested, by
    test_report_flags_a_requirement_met_only_by_residual_faults below, because
    the machinery has to keep working for the next gap. What changed is the
    design, not the check.
    """
    text, _ = build(CATALOG, run_all(CATALOG), REQUIREMENTS)
    section = text.split("## Requirements not satisfied by this design")[1]
    assert "None: every requirement" in section, section


def test_report_flags_a_requirement_met_only_by_residual_faults() -> None:
    """Synthetic, because the real design no longer has such a requirement.

    Written against fabricated inputs on purpose: the day a new residual-only
    requirement appears is the day this path matters most, and that is the worst
    possible time to discover it was never exercised.
    """
    from fih.traceability import Requirement

    fault = dataclasses.replace(BY_ID["FLT-S05"], challenges=("SR-99",))
    req = Requirement(id="SR-99", text="a requirement nothing detects")
    text, ok = build((fault,), {fault.id: run_all((fault,))[fault.id]}, (req,))
    assert ok, "the residual fault should still meet its own verdict"
    section = text.split("## Requirements not satisfied by this design")[1]
    assert "SR-99" in section
    assert "does not currently meet them" in text


# --- the protection comparison -----------------------------------------------
def test_protection_section_reports_the_gain_not_just_the_pass() -> None:
    """"8 of 8 detected" would be true and useless: the bare protocol got 7.

    What the document has to show is how much earlier, and which fault changed
    from undetected to detected, so it is asserted rather than assumed.
    """
    from fih.protected_campaign import run_all_protected
    from fih.report import protection_markdown

    text = protection_markdown(CATALOG, run_all(CATALOG), run_all_protected(CATALOG))
    assert "steps earlier, before the payload reaches the device" in text
    assert "closes a fault the bare protocol never detects" in text
    assert "nothing: the bare protocol already rejected it" in text
    assert "the two profiles disagree" in text
    assert "F_Destination_Address" in text and "Data ID" in text


def test_protection_section_covers_every_communication_fault_and_only_those() -> None:
    from fih.protected_campaign import run_all_protected
    from fih.report import protection_markdown

    text = protection_markdown(CATALOG, run_all(CATALOG), run_all_protected(CATALOG))
    for fault in CATALOG:
        present = f"| {fault.id} |" in text
        assert present == (fault.fault_class == "communication"), (
            f"{fault.id} ({fault.fault_class}) should "
            f"{'appear' if fault.fault_class == 'communication' else 'not appear'} "
            f"in the protection comparison"
        )
