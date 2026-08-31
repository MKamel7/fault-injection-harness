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

from fih import gate
from fih.catalog import Fault

DEFAULT_ANALYSIS = Path(__file__).resolve().parents[2] / "docs" / "HAZARD_ANALYSIS.md"

#: A requirement row in the analysis: | SR-01 | text | goal | ftti |
#: All four columns are captured. The FTTI column used to be discarded, which
#: made it decorative: every fault set its OWN budget and nothing compared the
#: two, so any fault could be made to pass by raising its own number. SR-03
#: demanded 7 steps and was reported satisfied by a fault judged on 154.
_REQ_ROW = re.compile(
    r"^\|\s*(SR-\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
    re.MULTILINE)

#: A safety goal row: | SG-01 | text | HAZ-01, HAZ-02 |
_GOAL_ROW = re.compile(
    r"^\|\s*(SG-\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)

#: A hazard row: | HAZ-01 | text | consequence |
_HAZARD_ROW = re.compile(
    r"^\|\s*(HAZ-\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)

#: Requirement budgets that are not a plain step count. `invariant` is a property
#: that must hold at all times rather than within a window, and `budget + 1` is
#: expressed relative to a configurable watchdog budget. Both are exempt from the
#: numeric comparison, and naming them here means the exemption is a decision
#: rather than a parse failure that silently skipped the check.
_NON_NUMERIC_BUDGETS = {"invariant", "budget + 1", "per condition"}


#: The gate's error, under this package's older name. An alias rather than a
#: subclass on purpose: a gap raised by `fih.gate` and a gap raised by the
#: loader here are the same kind of failure, and code catching one must catch
#: the other. A subclass would let a caller catch `TraceabilityError` and
#: silently miss everything the shared gate raises.
TraceabilityError = gate.GateError


@dataclass(frozen=True)
class Requirement:
    id: str
    text: str
    #: The requirement's OWN fault tolerant time interval, in steps. None when
    #: the analysis states it as an invariant or relative to another budget.
    ftti_steps: int | None = None
    #: The raw text, so a non-numeric budget can be reported as what it says.
    ftti_text: str = ""
    #: The safety goals this requirement decomposes. Parsed from the third
    #: column, which used to be captured and thrown away, so the chain from a
    #: hazard down to a fault could not be followed by anything but a human
    #: reading three documents side by side.
    goals: tuple[str, ...] = ()


@dataclass(frozen=True)
class Goal:
    """A safety goal, and the hazards it exists to control."""

    id: str
    text: str
    hazards: tuple[str, ...] = ()


@dataclass(frozen=True)
class Hazard:
    """A hazard, and what it does when it happens."""

    id: str
    text: str
    consequence: str = ""


def _ids(cell: str, prefix: str) -> tuple[str, ...]:
    return tuple(re.findall(rf"{prefix}-\d+", cell))


def load_goals(path: Path | str = DEFAULT_ANALYSIS) -> tuple[Goal, ...]:
    """Parse SG-xx rows out of the hazard analysis."""
    text = Path(path).read_text()
    goals = tuple(Goal(id=m.group(1), text=m.group(2).strip(),
                       hazards=_ids(m.group(3), "HAZ"))
                  for m in _GOAL_ROW.finditer(text))
    if not goals:
        raise TraceabilityError(
            f"{path}: no SG-xx safety goals found. Without them a requirement "
            f"cannot be shown to descend from a hazard, and the chain the whole "
            f"argument rests on would be unverifiable.")
    return goals


def load_hazards(path: Path | str = DEFAULT_ANALYSIS) -> tuple[Hazard, ...]:
    """Parse HAZ-xx rows out of the hazard analysis."""
    text = Path(path).read_text()
    hazards = tuple(Hazard(id=m.group(1), text=m.group(2).strip(),
                           consequence=m.group(3).strip())
                    for m in _HAZARD_ROW.finditer(text))
    if not hazards:
        raise TraceabilityError(
            f"{path}: no HAZ-xx hazards found. Every safety goal would then "
            f"descend from nothing.")
    return hazards


def load_requirements(path: Path | str = DEFAULT_ANALYSIS) -> tuple[Requirement, ...]:
    """Parse SR-xx rows out of the hazard analysis."""
    text = Path(path).read_text()
    reqs = []
    for m in _REQ_ROW.finditer(text):
        raw = m.group(4).strip()
        steps = None
        if raw not in _NON_NUMERIC_BUDGETS:
            digits = re.match(r"(\d+)", raw)
            if not digits:
                # Neither a recognised non-numeric form nor a number. Silently
                # treating it as "no budget" would ungate the requirement
                # without anybody deciding to, which is the same class of hole
                # as discarding the column altogether.
                raise TraceabilityError(
                    f"{m.group(1)}: budget {raw!r} is neither a step count nor "
                    f"one of {sorted(_NON_NUMERIC_BUDGETS)}. An unreadable "
                    f"budget must not quietly become an unenforced one."
                )
            steps = int(digits.group(1))
        reqs.append(Requirement(id=m.group(1), text=m.group(2).strip(),
                                ftti_steps=steps, ftti_text=raw,
                                goals=_ids(m.group(3), "SG")))
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
    """Return requirement id -> fault ids, or raise on a gap in either direction.

    The checking itself lives in `fih.gate` now. It had been written twice, here
    and in the virtual production cell, and the two copies had already drifted
    apart before a third safety argument needed the same thing. It now lives
    somewhere neither project owns and all three import.

    What remains here is the translation, which is the part that is genuinely
    about fault injection: requirements in this repository carry an FTTI in
    steps, and `Fault` satisfies the gate's `Evidence` protocol through the
    `claims` and `budget` aliases on it. More steps is a looser budget, which is
    the gate's default reading, so no comparator is passed.
    """
    return gate.check(
        tuple(gate.Requirement(id=r.id, text=r.text, budget=r.ftti_steps,
                               budget_text=r.ftti_text)
              for r in requirements),
        faults,
    )


def matrix_markdown(faults: tuple[Fault, ...],
                    requirements: tuple[Requirement, ...]) -> str:
    """Render the traceability matrix from the CATALOG, not from a run.

    Stated because it used to be misleading. This function once took a `results`
    argument and never read it, which implied the matrix reported measured
    outcomes. It does not: it reports what the catalog DECLARES, so a fault that
    claims to be detected in time appears here as coverage whether or not the run
    agreed.

    That is not unsound, because a mis-declared fault fails its verdict in
    `report.py` and fails the build. But the two documents answer different
    questions and should be read that way: this one is declared linkage, and
    `report/coverage.md` is what happened. The dead parameter suggested
    otherwise and is gone.
    """
    mapping = check(faults, requirements)
    by_id = {f.id: f for f in faults}

    lines = [
        "# Requirement to test traceability",
        "",
        "Generated from `catalog/faults.yaml` and `docs/HAZARD_ANALYSIS.md`. Do "
        "not edit by hand.",
        "",
        "**This is declared linkage, not measured outcome.** It shows which fault "
        "challenges which requirement and what the catalog expects. What actually "
        "happened is in `coverage.md`, and a fault whose declaration does not "
        "match its run fails the build rather than appearing here as coverage.",
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
