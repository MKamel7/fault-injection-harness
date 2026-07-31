"""Bidirectional traceability between requirements and the faults that test them.

Structured the way Automotive SPICE SWE.4 and SWE.6 expect verification to be
traceable: every requirement has evidence, and every piece of evidence exists
because of a requirement. Both directions are enforced, and the build fails on a
gap in either, because each direction catches a different mistake:

  requirement with no fault   a hole in the argument. Something was specified
                              and never verified, and nothing would have said so.
  fault with no requirement   scope creep, or a typo in a requirement id. The
                              fault runs, looks like coverage, and answers
                              nothing that was asked for.

The second is the one that quietly inflates a coverage report, and a typo is
enough to cause it, which is why it is a build failure rather than a warning.

Requirements are parsed from docs/HAZARD_ANALYSIS.md rather than duplicated
here. A second list would drift from the analysis, and then the matrix would be
traceable to the wrong thing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from fih.catalog import Fault

DEFAULT_ANALYSIS = Path(__file__).resolve().parents[2] / "docs" / "HAZARD_ANALYSIS.md"

#: A requirement row in the analysis: | SR-01 | text | goal | ftti |
_REQ_ROW = re.compile(r"^\|\s*(SR-\d+)\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)


class TraceabilityError(AssertionError):
    """Raised on a gap in either direction. Never downgraded to a warning."""


@dataclass(frozen=True)
class Requirement:
    id: str
    text: str


def load_requirements(path: Path | str = DEFAULT_ANALYSIS) -> tuple[Requirement, ...]:
    """Parse SR-xx rows out of the hazard analysis."""
    text = Path(path).read_text()
    reqs = [Requirement(id=m.group(1), text=m.group(2).strip())
            for m in _REQ_ROW.finditer(text)]
    if not reqs:
        raise TraceabilityError(
            f"{path}: no SR-xx requirements found. Either the analysis lost its "
            f"requirements table or its format changed, and every downstream "
            f"claim of coverage would be vacuous."
        )
    seen: set[str] = set()
    for req in reqs:
        if req.id in seen:
            raise TraceabilityError(f"{req.id} is defined twice in {path}")
        seen.add(req.id)
    return tuple(reqs)


def check(faults: tuple[Fault, ...],
          requirements: tuple[Requirement, ...]) -> dict[str, tuple[str, ...]]:
    """Return requirement id -> fault ids, or raise on a gap in either direction."""
    known = {req.id for req in requirements}
    challenged: dict[str, list[str]] = {req.id: [] for req in requirements}

    unknown: list[str] = []
    for fault in faults:
        for req in fault.challenges:
            if req not in known:
                unknown.append(f"{fault.id} -> {req}")
            else:
                challenged[req].append(fault.id)

    if unknown:
        raise TraceabilityError(
            "fault(s) reference requirements that do not exist in the hazard "
            f"analysis: {unknown}. Usually a typo, which would otherwise count "
            f"as coverage while verifying nothing."
        )

    orphans = sorted(req for req, ids in challenged.items() if not ids)
    if orphans:
        raise TraceabilityError(
            f"requirement(s) with no fault challenging them: {orphans}. "
            f"Specified and never verified."
        )

    return {req: tuple(ids) for req, ids in challenged.items()}


def matrix_markdown(faults: tuple[Fault, ...],
                    requirements: tuple[Requirement, ...],
                    results: dict[str, object] | None = None) -> str:
    """Render the traceability matrix."""
    mapping = check(faults, requirements)
    by_id = {f.id: f for f in faults}

    lines = [
        "# Requirement to test traceability",
        "",
        "Generated from `catalog/faults.yaml` and `docs/HAZARD_ANALYSIS.md`. Do "
        "not edit by hand.",
        "",
        "Both directions are enforced and the build fails on a gap in either: a "
        "requirement with no fault is a hole in the argument, and a fault with "
        "no requirement is scope creep or a typo that would inflate coverage.",
        "",
        "| Requirement | Challenged by | Verdict |",
        "|---|---|---|",
    ]
    for req in requirements:
        ids = mapping[req.id]
        # A requirement is a UNIVERSAL claim, so one unhandled challenge
        # falsifies it. Satisfied means every fault challenging it is detected
        # inside its budget, not that at least one is.
        #
        # The weaker rule, at least one detecting fault, was in place first and
        # reported SR-10 as satisfied while a sensor stuck at ambient let the
        # winding reach 207 C. One passing example does not establish a claim
        # that quantifies over all of them, and a matrix that scores it that way
        # is measuring test presence rather than requirement satisfaction.
        late = [i for i in ids if by_id[i].is_late]
        residual = [i for i in ids if by_id[i].is_residual]
        if not late and not residual:
            verdict = "satisfied"
        else:
            why = []
            if late:
                why.append(f"detected outside budget: {', '.join(late)}")
            if residual:
                why.append(f"undetected: {', '.join(residual)}")
            verdict = "**NOT satisfied**, " + "; ".join(why)
        lines.append(f"| {req.id} | {', '.join(ids)} | {verdict} |")

    lines += ["", "| Fault | Class | Challenges | Expectation |", "|---|---|---|---|"]
    for fault in faults:
        lines.append(
            f"| {fault.id} | {fault.fault_class} | {', '.join(fault.challenges)} "
            f"| {fault.expectation} |"
        )
    return "\n".join(lines) + "\n"
