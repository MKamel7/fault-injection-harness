"""The malformed inputs the loader must refuse.

Split from the catalog tests because these are not about any one fault: they are
about the loader being the place where a bad catalog stops. Every branch here
exists because the alternative is a fault that appears in the coverage report
and tests nothing, which is the one failure this project cannot tolerate.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from fih.campaign import _arm, run
from fih.catalog import CatalogError, Fault, load_catalog
from fih.injection.device import ActuatorFaultedController
from fih.injection.transport import FaultyTransport
from fih.traceability import TraceabilityError, load_requirements

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


def _load(tmp_path: Path, body: str) -> tuple[Fault, ...]:
    path = tmp_path / "faults.yaml"
    path.write_text(textwrap.dedent(body))
    return load_catalog(path)


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    body = "\n".join(ln for ln in GOOD.splitlines() if "fault_class" not in ln)
    with pytest.raises(CatalogError, match="missing required field"):
        _load(tmp_path, body)


def test_injection_must_be_a_mapping_with_a_hook(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="must be a mapping"):
        _load(tmp_path, GOOD.replace(
            "injection: {hook: temperature_stuck, params: {at_c: 40.0}}",
            "injection: temperature_stuck"))


def test_challenges_must_be_a_non_empty_list(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="non-empty list"):
        _load(tmp_path, GOOD.replace("challenges: [SR-01]", "challenges: []"))


def test_rationale_on_a_detected_fault_is_rejected(tmp_path: Path) -> None:
    """It reads as a documented gap while the fault is actually covered."""
    with pytest.raises(CatalogError, match="meaningless on a detected fault"):
        _load(tmp_path, GOOD + "    residual_rationale: not applicable\n")


def test_ftti_must_be_a_positive_integer(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="positive integer FTTI"):
        _load(tmp_path, GOOD.replace("ftti_steps: 5", "ftti_steps: 0"))


def test_a_file_that_is_not_a_fault_catalog_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="expected a mapping"):
        _load(tmp_path, "just a string\n")


def test_an_empty_catalog_is_rejected(tmp_path: Path) -> None:
    """Zero faults would report as a clean campaign rather than as no campaign."""
    with pytest.raises(CatalogError, match="empty"):
        _load(tmp_path, "version: 1\nfaults: []\n")


def test_an_unknown_injection_hook_is_a_hard_error(tmp_path: Path) -> None:
    """A catalog entry that injects nothing must not run green."""
    faults = _load(tmp_path, GOOD.replace("temperature_stuck", "does_not_exist"))
    with pytest.raises(KeyError, match="unknown injection hook"):
        _arm(faults[0], ActuatorFaultedController(), FaultyTransport(None))  # type: ignore[arg-type]


def test_run_also_refuses_an_unknown_hook(tmp_path: Path) -> None:
    faults = _load(tmp_path, GOOD.replace("temperature_stuck", "does_not_exist"))
    with pytest.raises(KeyError):
        run(faults[0])


# --- the requirements side ---------------------------------------------------
def test_an_analysis_with_no_requirements_is_rejected(tmp_path: Path) -> None:
    """Otherwise every claim of coverage is vacuously true."""
    path = tmp_path / "HAZARD_ANALYSIS.md"
    path.write_text("# Analysis\n\nProse, but no requirements table.\n")
    with pytest.raises(TraceabilityError, match="no SR-xx requirements found"):
        load_requirements(path)


def test_a_requirement_defined_twice_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "HAZARD_ANALYSIS.md"
    path.write_text("| SR-01 | first | SG-01 | 5 |\n| SR-01 | second | SG-01 | 5 |\n")
    with pytest.raises(TraceabilityError, match="defined twice"):
        load_requirements(path)
