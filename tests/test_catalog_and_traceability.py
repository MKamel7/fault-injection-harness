"""Tests for the catalog loader and the traceability gate.

These verify the machinery the evidence depends on. If the loader silently
accepts a malformed entry, or the traceability gate can be satisfied by a typo,
then every downstream number is unreliable no matter how green the campaign is.
So the gate is tested by deliberately breaking it.
"""

from __future__ import annotations

import dataclasses
import textwrap
from pathlib import Path

import pytest

from fih.catalog import CatalogError, load_catalog
from fih.traceability import (
    Requirement,
    TraceabilityError,
    check,
    load_requirements,
    matrix_markdown,
)

GOOD = """
version: 1
faults:
  - id: FLT-X01
    title: A fault
    fault_class: sensor
    description: text
    injection: {hook: temperature_stuck, params: {at_c: 40.0}}
    challenges: [SR-01]
    safe_state: STO
    ftti_steps: 5
    expectation: detected
"""


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "faults.yaml"
    path.write_text(textwrap.dedent(body))
    return path


def test_valid_catalog_loads(tmp_path: Path) -> None:
    faults = load_catalog(_write(tmp_path, GOOD))
    assert faults[0].id == "FLT-X01"
    assert faults[0].params == {"at_c": 40.0}


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("fault_class: sensor", "fault_class: gremlin"),
        ("expectation: detected", "expectation: maybe"),
        ("safe_state: STO", "safe_state: OFF"),
    ],
)
def test_invalid_enum_values_are_rejected(tmp_path: Path, mutation: str,
                                          expected: str) -> None:
    with pytest.raises(CatalogError):
        load_catalog(_write(tmp_path, GOOD.replace(mutation, expected)))


def test_misspelled_field_is_rejected_not_ignored(tmp_path: Path) -> None:
    """The important one. A silently ignored key is a fault that never runs."""
    with pytest.raises(CatalogError, match="unknown field"):
        load_catalog(_write(tmp_path, GOOD.replace("ftti_steps:", "ftti_step:")))


def test_detected_fault_without_ftti_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="FTTI"):
        load_catalog(_write(tmp_path, GOOD.replace("ftti_steps: 5", "ftti_steps: null")))


def test_residual_fault_must_explain_itself(tmp_path: Path) -> None:
    body = GOOD.replace("expectation: detected", "expectation: residual").replace(
        "ftti_steps: 5", "ftti_steps: null")
    with pytest.raises(CatalogError, match="design change"):
        load_catalog(_write(tmp_path, body))


def test_residual_fault_may_not_carry_an_ftti(tmp_path: Path) -> None:
    body = GOOD.replace("expectation: detected", "expectation: residual")
    body += "    residual_rationale: because\n"
    with pytest.raises(CatalogError, match="must not carry an FTTI"):
        load_catalog(_write(tmp_path, body))


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="duplicate"):
        load_catalog(_write(tmp_path, GOOD + GOOD.split("faults:")[1]))


# --- the traceability gate, tested by breaking it ---------------------------
def test_gate_rejects_a_requirement_with_no_fault() -> None:
    faults = load_catalog()
    reqs = (*load_requirements(), Requirement(id="SR-99", text="never verified"))
    with pytest.raises(TraceabilityError, match="no fault challenging"):
        check(faults, reqs)


def test_gate_rejects_a_fault_referencing_an_unknown_requirement(
    tmp_path: Path,
) -> None:
    """A typo in a requirement id must fail the build, not count as coverage."""
    faults = load_catalog(_write(tmp_path, GOOD.replace("SR-01", "SR-0l")))
    with pytest.raises(TraceabilityError, match="do not exist"):
        check(faults, load_requirements())


def test_real_catalog_and_analysis_are_fully_traceable() -> None:
    mapping = check(load_catalog(), load_requirements())
    assert all(ids for ids in mapping.values())


def test_matrix_reports_a_requirement_unmet_when_any_challenge_is_unhandled() -> None:
    """Satisfaction is universal, not existential.

    The matrix exists to surface that a requirement can be fully traceable and
    still unsatisfied. It reported SR-10 as satisfied under an earlier,
    existential rule while a sensor stuck at ambient let the winding reach
    207 C, so the rule itself is now asserted rather than assumed.
    """
    faults = load_catalog()
    text = matrix_markdown(faults, load_requirements())

    by_req = {line.split("|")[1].strip(): line
              for line in text.splitlines() if line.startswith("| SR-")}

    for req, row in by_req.items():
        ids = [i.strip() for i in row.split("|")[2].split(",")]
        unhandled = [f.id for f in faults if f.id in ids and not f.protects]
        if unhandled:
            assert "NOT satisfied" in row, (
                f"{req} is challenged by unhandled {unhandled} and still reads "
                f"as satisfied"
            )
            for fid in unhandled:
                assert fid in row, f"{req} does not name its counterexample {fid}"
        else:
            assert "NOT satisfied" not in row, f"{req} is unmet with no reason given"

    assert any("NOT satisfied" in r for r in by_req.values()), (
        "no requirement is unmet, so this test is not exercising the case it "
        "was written for"
    )


def test_a_requirement_broken_only_by_lateness_says_only_that() -> None:
    """The reason has to name which kind of failure it was.

    "Not satisfied" alone would leave a reader unable to tell a design that
    never notices a fault from one that notices it too late, and those call for
    completely different fixes: a new diagnostic versus a faster one.
    """
    faults = load_catalog()
    # No entry is currently late, the estimator closed the only one, so the case
    # is made synthetically. The distinction has to keep working for the next
    # one: "not satisfied" alone would leave a reader unable to tell a design
    # that never notices a fault from one that notices it too late, and those
    # call for completely different fixes.
    template = next(f for f in faults if not f.is_residual)
    only_late = dataclasses.replace(template, id="FLT-Z98", challenges=("SR-99",),
                                    expectation="late", ftti_steps=1,
                                    late_rationale="synthetic")
    reqs = (*load_requirements(), Requirement(id="SR-99", text="late only"))

    row = next(line for line in matrix_markdown((*faults, only_late), reqs).splitlines()
               if line.startswith("| SR-99 "))
    assert "detected outside budget: FLT-Z98" in row
    assert "undetected" not in row
