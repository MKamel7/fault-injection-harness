"""Load and validate the fault catalog.

The catalog is data, not code, so that adding a fault is a YAML entry and never
a new test. That only works if the loader is strict: a typo in a requirement id
or a missing FTTI has to fail loudly at load time, because the alternative is a
fault that silently never runs and a coverage report that quietly overstates
itself.

Validation is deliberately paranoid about the things that would corrupt the
evidence rather than merely crash:

  - unknown keys are rejected, so a misspelled field is not silently ignored
  - a detected fault must carry an FTTI, or its result cannot be judged
  - a residual fault must NOT carry one, and must explain itself
  - ids must be unique, or traceability silently loses an entry
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

FAULT_CLASSES = {"sensor", "actuator", "communication", "timing"}
#: Three outcomes, not two. A design can detect a fault and still not protect
#: against it, and collapsing "detected in time" and "detected too late" into one
#: word is how a coverage report ends up describing a drive that burns out.
EXPECTATIONS = {"detected", "late", "residual"}
SAFE_STATES = {"STO", "SS1", "none"}

#: A condition that must already hold for the fault to mean anything. Named in
#: the catalog rather than hard coded in the runner, because "this fault was
#: only injected once the rotor was already jammed" is part of what the evidence
#: says, and a reviewer must be able to see it without reading Python.
PRECONDITIONS = {"stalled_rotor", "overloaded_rotor"}

_REQUIRED = {"id", "title", "fault_class", "description", "injection",
             "challenges", "safe_state", "ftti_steps", "expectation"}
#: `history` records a fault that USED to behave differently, with the measured
#: before and after. Optional, and deliberately not deleted once a gap closes: a
#: catalog that erases the gap it fixed loses the evidence that fixing it
#: mattered, and a reviewer can no longer tell a design that was always safe from
#: one that was made safe.
_OPTIONAL = {"residual_rationale", "late_rationale", "history", "precondition"}

DEFAULT_CATALOG = Path(__file__).resolve().parents[2] / "catalog" / "faults.yaml"


class CatalogError(ValueError):
    """Raised when the catalog is malformed. Never recovered from."""


@dataclass(frozen=True)
class Fault:
    """One catalogued fault."""

    id: str
    title: str
    fault_class: str
    description: str
    hook: str
    params: dict[str, Any]
    challenges: tuple[str, ...]
    safe_state: str
    ftti_steps: int | None
    expectation: str
    residual_rationale: str | None = None
    late_rationale: str | None = None
    history: str | None = None
    precondition: str | None = None

    @property
    def is_residual(self) -> bool:
        return self.expectation == "residual"

    @property
    def is_late(self) -> bool:
        """Detected, but outside the budget. Documented, and still a failure."""
        return self.expectation == "late"

    @property
    def protects(self) -> bool:
        """Does this fault demonstrate the design actually protecting?

        Only a fault detected INSIDE its budget does. Used by the traceability
        matrix, so a requirement met only by late or residual faults is reported
        as unsatisfied rather than as covered.
        """
        return self.expectation == "detected"


def _fail(fault_id: str, message: str) -> None:
    raise CatalogError(f"{fault_id}: {message}")


def _parse_fault(raw: dict[str, Any], seen: set[str]) -> Fault:
    fault_id = str(raw.get("id", "<no id>"))

    unknown = set(raw) - _REQUIRED - _OPTIONAL
    if unknown:
        _fail(fault_id, f"unknown field(s) {sorted(unknown)}. A misspelled key "
                        f"would otherwise be silently ignored")
    missing = _REQUIRED - set(raw)
    if missing:
        _fail(fault_id, f"missing required field(s) {sorted(missing)}")
    if fault_id in seen:
        _fail(fault_id, "duplicate id; traceability would lose one of them")

    if raw["fault_class"] not in FAULT_CLASSES:
        _fail(fault_id, f"fault_class {raw['fault_class']!r} not in {sorted(FAULT_CLASSES)}")
    if raw["expectation"] not in EXPECTATIONS:
        _fail(fault_id, f"expectation {raw['expectation']!r} not in {sorted(EXPECTATIONS)}")
    if raw["safe_state"] not in SAFE_STATES:
        _fail(fault_id, f"safe_state {raw['safe_state']!r} not in {sorted(SAFE_STATES)}")

    precondition = raw.get("precondition")
    if precondition is not None and precondition not in PRECONDITIONS:
        _fail(fault_id, f"precondition {precondition!r} not in {sorted(PRECONDITIONS)}")

    injection = raw["injection"]
    if not isinstance(injection, dict) or "hook" not in injection:
        _fail(fault_id, "injection must be a mapping with a 'hook'")
    challenges = raw["challenges"]
    if not isinstance(challenges, list) or not challenges:
        _fail(fault_id, "challenges must be a non-empty list of requirement ids")

    ftti = raw["ftti_steps"]
    residual = raw["expectation"] == "residual"
    if residual:
        if ftti is not None:
            _fail(fault_id, "residual faults must not carry an FTTI: nothing "
                            "detects them, so there is no budget to meet")
        if not raw.get("residual_rationale"):
            _fail(fault_id, "residual faults must state what design change "
                            "would close the gap")
    else:
        if not isinstance(ftti, int) or ftti < 1:
            _fail(fault_id, "a detected fault needs a positive integer FTTI in "
                            "steps, or its result cannot be judged")
        if raw.get("residual_rationale"):
            _fail(fault_id, "residual_rationale is meaningless on a detected fault")

    late = raw["expectation"] == "late"
    if late and not raw.get("late_rationale"):
        _fail(fault_id, "late faults must state why detection cannot be brought "
                        "inside the budget, and what would bring it inside")
    if not late and raw.get("late_rationale"):
        _fail(fault_id, "late_rationale is meaningless unless the fault is "
                        "expected to be detected outside its budget")

    return Fault(
        id=fault_id,
        title=str(raw["title"]),
        fault_class=str(raw["fault_class"]),
        description=" ".join(str(raw["description"]).split()),
        hook=str(injection["hook"]),
        params=dict(injection.get("params") or {}),
        challenges=tuple(str(c) for c in challenges),
        safe_state=str(raw["safe_state"]),
        ftti_steps=ftti,
        expectation=str(raw["expectation"]),
        residual_rationale=(" ".join(str(raw["residual_rationale"]).split())
                            if raw.get("residual_rationale") else None),
        late_rationale=(" ".join(str(raw["late_rationale"]).split())
                        if raw.get("late_rationale") else None),
        history=(" ".join(str(raw["history"]).split())
                 if raw.get("history") else None),
        precondition=raw.get("precondition"),
    )


def load_catalog(path: Path | str = DEFAULT_CATALOG) -> tuple[Fault, ...]:
    """Parse and validate the catalog, or raise CatalogError."""
    text = Path(path).read_text()
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict) or "faults" not in doc:
        raise CatalogError(f"{path}: expected a mapping with a 'faults' list")

    faults: list[Fault] = []
    seen: set[str] = set()
    for raw in doc["faults"]:
        fault = _parse_fault(raw, seen)
        seen.add(fault.id)
        faults.append(fault)
    if not faults:
        raise CatalogError(f"{path}: catalog is empty")
    return tuple(faults)
