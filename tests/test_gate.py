"""The shared traceability gate, exercised on its own terms.

`test_catalog_and_traceability.py` covers what the gate does to THIS
repository's hazard analysis. This file covers the gate as a component that two
other safety arguments now import, using records that have nothing to do with
fault injection, because that is the whole reason it was extracted.

Every failure mode is watched failing. A gate nobody has seen fail is an
assumption rather than a control, and that applies to the shared copy at least
as much as it did to the two it replaced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fih.gate import (
    Claim,
    Evidence,
    GateError,
    Requirement,
    as_evidence,
    check,
    check_chain,
    claims_in_file,
    collect_marker_claims,
)


def req(rid: str, budget: float | None = None) -> Requirement:
    return Requirement(id=rid, text=f"requirement {rid}", budget=budget)


def ev(eid: str, *claims: str, budget: float | None = None) -> Claim:
    return Claim(id=eid, claims=claims, budget=budget, where=eid)


# --- the two directions ------------------------------------------------------
def test_a_complete_argument_maps_requirements_to_their_evidence() -> None:
    result = check((req("R-1"), req("R-2")),
                   [ev("E-1", "R-1"), ev("E-2", "R-1", "R-2")])

    assert result == {"R-1": ("E-1", "E-2"), "R-2": ("E-2",)}


def test_a_requirement_with_no_evidence_fails_the_build() -> None:
    """The hole. Something was specified and never verified."""
    with pytest.raises(GateError, match="R-2"):
        check((req("R-1"), req("R-2")), [ev("E-1", "R-1")])


def test_evidence_naming_a_requirement_that_does_not_exist_fails_the_build() -> None:
    """The quieter direction, and the reason this is a gate rather than a report.

    A single mistyped character produces evidence that runs, passes, and fills
    a row in the matrix while answering nothing that was asked for. A gate
    checking only downward would let an entire suite of misspelled markers
    through as complete coverage.
    """
    with pytest.raises(GateError, match="do not exist"):
        check((req("R-1"),), [ev("E-1", "R-l")])


def test_the_failure_names_where_the_bad_claim_came_from() -> None:
    """An id alone does not tell you which file to open."""
    with pytest.raises(GateError, match=r"test_thing.py::test_it"):
        check((req("R-1"),),
              [Claim(id="x", claims=("R-9",), where="test_thing.py::test_it")])


def test_a_requirement_defined_twice_fails_rather_than_resolving_by_order() -> None:
    with pytest.raises(GateError, match="more than once"):
        check((req("R-1"), req("R-1")), [ev("E-1", "R-1")])


# --- budgets -----------------------------------------------------------------
def test_evidence_cannot_grant_itself_more_room_than_the_requirement() -> None:
    """Without this the numbers are decorative.

    Every piece of evidence would set its own budget and anything could be made
    to pass by raising it. This is not hypothetical: in this repository a
    requirement demanding 7 steps was once reported satisfied by a fault judged
    on 154.
    """
    with pytest.raises(GateError, match="more room than the requirement allows"):
        check((req("R-1", budget=7),), [ev("E-1", "R-1", budget=154)])


def test_evidence_judged_inside_the_budget_passes() -> None:
    assert check((req("R-1", budget=10),), [ev("E-1", "R-1", budget=10)])


def test_a_requirement_with_no_budget_imposes_none() -> None:
    """None is not zero. A requirement that states no number must not silently
    become one that demands the strictest possible."""
    assert check((req("R-1"),), [ev("E-1", "R-1", budget=99999)])


def test_evidence_with_no_budget_is_not_compared() -> None:
    assert check((req("R-1", budget=5),), [ev("E-1", "R-1")])


def test_looser_can_mean_smaller_when_the_project_says_so() -> None:
    """A time budget is looser when bigger; a detection threshold is looser
    when smaller. The gate must not assume automotive timing semantics, since
    the perception project measures in the opposite direction."""
    smaller_is_looser = check(
        (req("R-1", budget=0.4),), [ev("E-1", "R-1", budget=0.9)],
        is_looser=lambda evidence, requirement: evidence < requirement)

    assert smaller_is_looser == {"R-1": ("E-1",)}

    with pytest.raises(GateError, match="more room"):
        check((req("R-1", budget=0.4),), [ev("E-1", "R-1", budget=0.1)],
              is_looser=lambda evidence, requirement: evidence < requirement)


# --- the chain ---------------------------------------------------------------
def test_a_requirement_under_a_goal_that_does_not_exist_fails() -> None:
    """A renamed goal leaves a matrix that reads as complete and traces to
    nothing, which is the same error as a misspelled marker one level down."""
    children = (Requirement(id="R-1", text="t", parent="G-9"),)

    with pytest.raises(GateError, match="G-9"):
        check_chain(children, {"G-1"})


def test_a_flat_argument_needs_no_parents() -> None:
    check_chain((req("R-1"), req("R-2")), set())


def test_the_chain_failure_names_the_level_it_is_talking_about() -> None:
    children = (Requirement(id="TC-1", text="t", parent="H-4"),)

    with pytest.raises(GateError, match="triggering condition"):
        check_chain(children, {"H-1"},
                    child_kind="triggering condition", parent_kind="hazard")


# --- harvesting claims from source ------------------------------------------
SUITE = '''
import functools
import pytest

@pytest.mark.verifies("R-1")
def test_one() -> None:
    pass

@pytest.mark.parametrize("case", [1, 2])
@pytest.mark.verifies("R-1", "R-2")
def test_two(case) -> None:
    pass

def test_unmarked() -> None:
    """Not every test claims a requirement, and that is not an error."""

@pytest.mark.slow
def test_other_marker() -> None:
    pass

@functools.lru_cache()
def test_unrelated_call_decorator() -> None:
    pass
'''


def test_claims_are_read_from_markers(tmp_path: Path) -> None:
    path = tmp_path / "test_sample.py"
    path.write_text(SUITE, encoding="utf-8")

    assert claims_in_file(path) == {"test_one": ["R-1"], "test_two": ["R-1", "R-2"]}


def test_a_marker_inside_a_string_is_not_a_claim(tmp_path: Path) -> None:
    """Parsed, not grepped, and this is the difference.

    A docstring explaining the marker would otherwise register as coverage for
    a requirement nothing actually tests.
    """
    path = tmp_path / "test_sample.py"
    path.write_text(
        'MARKER_DOCS = \'@pytest.mark.verifies("R-99")\'\n'
        '# @pytest.mark.verifies("R-98")\n'
        'def test_real() -> None:\n'
        '    """Use @pytest.mark.verifies("R-97") to claim a requirement."""\n',
        encoding="utf-8")

    assert claims_in_file(path) == {}


def test_claims_are_collected_across_a_test_tree(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "test_a.py").write_text(SUITE, encoding="utf-8")
    (tmp_path / "nested" / "test_b.py").write_text(
        'import pytest\n\n@pytest.mark.verifies("R-3")\ndef test_three() -> None:\n    pass\n',
        encoding="utf-8")
    (tmp_path / "helper.py").write_text(
        'import pytest\n\n@pytest.mark.verifies("R-4")\ndef test_ignored() -> None:\n    pass\n',
        encoding="utf-8")

    claimed = collect_marker_claims(tmp_path)

    assert claimed["R-1"] == [("test_a.py", "test_one"), ("test_a.py", "test_two")]
    assert claimed["R-3"] == [("test_b.py", "test_three")]
    assert "R-4" not in claimed, "a non-test module must not be harvested"


def test_a_computed_requirement_id_is_not_harvested(tmp_path: Path) -> None:
    """Only string literals count, and this fails in the safe direction.

    `@pytest.mark.verifies(SR_01)` reads as a claim but cannot be resolved
    without importing the module, which is exactly what parsing avoids. The
    result is that the requirement appears UNVERIFIED and the build fails, which
    is the right way round: the alternative would be a claim nobody can check
    quietly counting as coverage.
    """
    path = tmp_path / "test_sample.py"
    path.write_text(
        'import pytest\n\n'
        'SR_01 = "R-1"\n\n'
        '@pytest.mark.verifies(SR_01, 42, "R-2")\n'
        'def test_it() -> None:\n'
        '    pass\n',
        encoding="utf-8")

    assert claims_in_file(path) == {"test_it": ["R-2"]}


def test_a_custom_marker_name_is_honoured(tmp_path: Path) -> None:
    path = tmp_path / "test_sample.py"
    path.write_text(
        'import pytest\n\n@pytest.mark.demonstrates("TC-1")\ndef test_it() -> None:\n    pass\n',
        encoding="utf-8")

    assert claims_in_file(path, marker="demonstrates") == {"test_it": ["TC-1"]}


def test_harvested_claims_become_one_piece_of_evidence_per_test() -> None:
    """Per test, not per requirement.

    A single test verifying three requirements is one piece of evidence
    answering three, not three unrelated ones. Counting it the other way would
    inflate any evidence count taken from this.
    """
    claimed = collect_marker_claims_stub()

    evidence = as_evidence(claimed)

    assert [e.id for e in evidence] == ["test_a.py::test_one", "test_a.py::test_two"]
    assert evidence[1].claims == ("R-1", "R-2")


def collect_marker_claims_stub() -> dict[str, list[tuple[str, str]]]:
    return {
        "R-1": [("test_a.py", "test_one"), ("test_a.py", "test_two")],
        "R-2": [("test_a.py", "test_two")],
    }


def test_harvested_evidence_passes_straight_into_the_gate(tmp_path: Path) -> None:
    """The two halves have to actually compose, which is the only thing the
    consuming projects care about."""
    (tmp_path / "test_a.py").write_text(SUITE, encoding="utf-8")

    result = check((req("R-1"), req("R-2")),
                   as_evidence(collect_marker_claims(tmp_path)))

    assert sorted(result["R-1"]) == ["test_a.py::test_one", "test_a.py::test_two"]


# --- the protocol ------------------------------------------------------------
def test_this_repositorys_fault_satisfies_the_evidence_protocol() -> None:
    """The aliases on `Fault` are what let the gate stay domain-neutral without
    renaming fault-injection vocabulary inside this package."""
    from fih.catalog import load_catalog

    fault = load_catalog()[0]

    assert isinstance(fault, Evidence)
    assert fault.claims == fault.challenges
    assert fault.budget == fault.ftti_steps
