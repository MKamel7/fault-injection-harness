"""The bidirectional traceability gate, with nothing fault-injection in it.

WHY THIS MODULE EXISTS SEPARATELY. The same gate has now been needed by three
different safety arguments: fault injection against ISO 26262 requirements here,
PackML safety requirements against IEC 61131-3 tests in the virtual production
cell, and perception triggering conditions against measured slice evidence under
ISO 21448. It was written twice before it was written once, and the second copy
already differed from the first in ways nobody had decided on.

What is genuinely common is not the hazards, the requirements or the evidence.
It is the two failure modes, which are the same in every domain:

  a requirement with no evidence   a hole. Something was specified and never
                                   verified, and nothing would have said so.

  evidence naming no requirement   the quieter one. It runs, it passes, and it
                                   makes the matrix look complete while
                                   answering nothing that was asked for. One
                                   mistyped character is enough.

The second is why this is a build failure rather than a report. A gate that only
checked downward would pass a suite where every marker was misspelled.

WHAT IS DELIBERATELY NOT HERE. Loading and rendering. The sources legitimately
differ, a markdown analysis table here, a YAML hazard analysis in the cell, and
pulling them into a common format would mean inventing a schema none of the
three projects wanted. Each project reads its own analysis and hands this module
plain records.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


class GateError(AssertionError):
    """A gap in the safety argument. Never downgraded to a warning.

    Deliberately an AssertionError: this is a claim about the work being wrong,
    not a runtime condition to be handled and continued past.
    """


@dataclass(frozen=True)
class Requirement:
    """Something the argument asserts, which evidence must answer for."""

    id: str
    text: str
    #: What this traces UP to: a safety goal, a hazard, an operational
    #: condition. None when the project's argument is flat.
    parent: str | None = None
    #: A numeric limit the requirement imposes, when it states one. The unit
    #: belongs to the project: fault tolerant time in steps here, a detection
    #: threshold elsewhere. None means the requirement sets no number, which is
    #: different from setting one of zero.
    budget: float | None = None
    #: The budget as written, so a non-numeric one can be reported as it reads.
    budget_text: str = ""


@runtime_checkable
class Evidence(Protocol):
    """Anything offered as verification of a requirement.

    A protocol rather than a base class, so a project's own record type
    qualifies without inheriting from this package. `Fault` in this repository
    satisfies it, and so does a pytest function harvested from a marker.
    """

    @property
    def id(self) -> str:
        """Identifies this piece of evidence in a failure message."""

    @property
    def claims(self) -> tuple[str, ...]:
        """The requirement ids this evidence is offered against."""

    @property
    def budget(self) -> float | None:
        """The limit this evidence was actually judged against, if any."""


@dataclass(frozen=True)
class Claim:
    """A piece of evidence harvested from source, rather than declared in data.

    `where` carries the location so a failure names the file and function that
    has to change, instead of only the id that was wrong.
    """

    id: str
    claims: tuple[str, ...]
    budget: float | None = None
    where: str = ""


def _looser(evidence_budget: float, requirement_budget: float) -> bool:
    """Default: a larger number is more permissive, as with a time budget."""
    return evidence_budget > requirement_budget


def check(requirements: Sequence[Requirement],
          evidence: Iterable[Evidence],
          *,
          is_looser: Callable[[float, float], bool] = _looser,
          ) -> dict[str, tuple[str, ...]]:
    """Return requirement id -> evidence ids, or raise on any gap.

    Three ways the argument can be wrong, all fatal:

    1. Evidence naming a requirement that does not exist.
    2. A requirement no evidence names.
    3. Evidence judged against a budget looser than the requirement it is cited
       for. Without this the numbers are decorative: every piece of evidence
       sets its own, and anything can be made to pass by raising it. That is not
       hypothetical, it is what happened in this repository before the check
       existed, where a requirement demanding 7 steps was reported satisfied by
       a fault judged on 154.

    `is_looser` exists because "looser" is not universally "larger". A time
    budget is looser when bigger; a detection threshold is looser when smaller.
    The comparison is the project's to state rather than this module's to assume.
    """
    counts: Counter[str] = Counter(req.id for req in requirements)
    duplicates = sorted(rid for rid, n in counts.items() if n > 1)
    if duplicates:
        raise GateError(
            f"requirement id(s) defined more than once: {duplicates}. Which one "
            f"the evidence answers would be decided by ordering.")
    known = set(counts)

    answered: dict[str, list[str]] = {req.id: [] for req in requirements}
    evidence = list(evidence)

    unknown: list[str] = []
    for item in evidence:
        for requirement_id in item.claims:
            if requirement_id in known:
                answered[requirement_id].append(item.id)
            else:
                where = getattr(item, "where", "") or item.id
                unknown.append(f"{where} -> {requirement_id}")
    if unknown:
        raise GateError(
            f"evidence names requirement(s) that do not exist: {sorted(unknown)}. "
            f"Usually a typo, which would otherwise count as coverage while "
            f"verifying nothing.")

    orphans = sorted(rid for rid, ids in answered.items() if not ids)
    if orphans:
        raise GateError(
            f"requirement(s) with no evidence: {orphans}. Specified and never "
            f"verified.")

    by_id = {item.id: item for item in evidence}
    overruns: list[str] = []
    for requirement in requirements:
        if requirement.budget is None:
            continue
        for evidence_id in answered[requirement.id]:
            budget = by_id[evidence_id].budget
            if budget is not None and is_looser(budget, requirement.budget):
                overruns.append(
                    f"{evidence_id} is judged on {budget:g} but "
                    f"{requirement.id} allows {requirement.budget:g}")
    if overruns:
        raise GateError(
            f"evidence judged against a budget looser than the requirement it "
            f"answers: {overruns}. Evidence cannot grant itself more room than "
            f"the requirement allows.")

    return {rid: tuple(ids) for rid, ids in answered.items()}


def check_chain(children: Sequence[Requirement],
                parents: Iterable[str],
                *,
                child_kind: str = "requirement",
                parent_kind: str = "goal") -> None:
    """Every child must trace up to a parent that exists.

    Separate from `check` because a flat argument has no parents and should not
    be forced to invent them. A requirement under a goal that was renamed reads
    as complete and traces to nothing, which is the same class of error as a
    misspelled marker one level down.
    """
    known = set(parents)
    dangling = [f"{c.id} names {parent_kind} {c.parent}"
                for c in children if c.parent is not None and c.parent not in known]
    if dangling:
        raise GateError(
            f"{child_kind}(s) tracing up to a {parent_kind} that does not "
            f"exist: {dangling}. The matrix would read as complete and trace "
            f"to nothing.")


#: Harvested claims, keyed by requirement id.
MarkerClaims = dict[str, list[tuple[str, str]]]


@dataclass
class _MarkerVisitor(ast.NodeVisitor):
    marker: str
    found: dict[str, list[str]] = field(default_factory=dict)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            attribute = decorator.func
            if not isinstance(attribute, ast.Attribute) or attribute.attr != self.marker:
                continue
            for argument in decorator.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    self.found.setdefault(node.name, []).append(argument.value)
        self.generic_visit(node)


def claims_in_file(path: Path, marker: str = "verifies") -> dict[str, list[str]]:
    """Requirement ids claimed by each test function in one file.

    Read by PARSING rather than by importing or running. Parsing cannot be
    fooled by a marker inside a string or a comment, and it still works on a
    suite too broken to collect, which is exactly when you most want to know
    what is no longer covered.
    """
    visitor = _MarkerVisitor(marker=marker)
    visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    return visitor.found


def collect_marker_claims(tests: Path, marker: str = "verifies",
                          pattern: str = "test_*.py") -> MarkerClaims:
    """requirement id -> [(file, test name)] across a test tree."""
    claimed: MarkerClaims = defaultdict(list)
    for path in sorted(tests.rglob(pattern)):
        for test, requirement_ids in claims_in_file(path, marker).items():
            for requirement_id in requirement_ids:
                claimed[requirement_id].append((path.name, test))
    return dict(claimed)


def as_evidence(claimed: MarkerClaims) -> tuple[Claim, ...]:
    """Turn harvested markers into evidence `check` can take.

    One Claim per test function, not per requirement, so that a single test
    verifying three requirements is reported as one piece of evidence answering
    three rather than as three unrelated ones.
    """
    by_test: dict[tuple[str, str], list[str]] = defaultdict(list)
    for requirement_id, locations in claimed.items():
        for location in locations:
            by_test[location].append(requirement_id)
    return tuple(
        Claim(id=f"{file}::{test}", claims=tuple(sorted(ids)),
              where=f"{file}::{test}")
        for (file, test), ids in sorted(by_test.items()))
