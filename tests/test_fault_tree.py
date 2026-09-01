"""The fault tree, its cut sets, and the campaign measured against them.

The load-bearing tests here are:

  * `test_no_single_point_of_failure_is_unattacked` is the gate. An order-1 cut
    set is one basic event that reaches the top event alone, and one nobody has
    injected is a hole in the campaign.
  * `test_the_common_cause_event_is_a_single_point_of_failure` is the result the
    tree exists to produce. Redundancy shows up as order-2 cut sets; a common
    cause defeats every channel at once and is therefore order 1. That is why a
    redundant design can still have a single point of failure, and it is
    invisible in the traceability chain.
  * `test_the_demand_is_not_part_of_the_cut_sets` guards a modelling error this
    file made and had to fix. The first version made the top event
    AND(heat is generated, protection fails), which put a demand event in every
    cut set, raised every order by one, and left ZERO order-1 cut sets. The gate
    above passed while guarding nothing.
  * `test_the_number_of_unattacked_double_failures_is_the_documented_one` stops
    the known gap growing quietly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fih.catalog import load_catalog
from fih.dual_point import load_pairs
from fih.fault_tree import (
    Event,
    FaultTree,
    FaultTreeError,
    coverage,
    load_tree,
    minimise,
)

#: Order-2 cut sets the dual-point campaign has never attacked. Three, all in
#: the sensor branch. Written down so the gap cannot grow without this number
#: changing, and named rather than counted so a reader knows which.
DOCUMENTED_UNATTACKED_PAIRS = 3


def _known_faults() -> set[str]:
    return {f.id for f in load_catalog()}


def _attacked_pairs() -> set[frozenset[str]]:
    return {frozenset((p.latent, p.primary)) for p in load_pairs()}


# --- the algebra -------------------------------------------------------------
def _basic(identifier: str) -> Event:
    return Event(identifier=identifier, title=identifier)


def test_an_or_gate_gives_one_cut_set_per_child() -> None:
    tree = FaultTree(Event("TOP", "t", "OR", (_basic("A"), _basic("B"))))
    assert tree.cut_sets() == (frozenset({"A"}), frozenset({"B"}))


def test_an_and_gate_gives_one_cut_set_of_both() -> None:
    tree = FaultTree(Event("TOP", "t", "AND", (_basic("A"), _basic("B"))))
    assert tree.cut_sets() == (frozenset({"A", "B"}),)


def test_a_superset_is_not_a_minimal_cut_set() -> None:
    """If A alone reaches the top, {A, B} says nothing new.

    Keeping it would inflate the count and, far worse, let a single point of
    failure hide inside a list of plausible-looking pairs.
    """
    assert minimise((frozenset({"A"}), frozenset({"A", "B"}))) == (
        frozenset({"A"}),)


def test_cut_sets_come_back_smallest_first() -> None:
    tree = FaultTree(Event("TOP", "t", "OR", (
        Event("G", "g", "AND", (_basic("A"), _basic("B"))), _basic("C"))))
    assert [len(c) for c in tree.cut_sets()] == [1, 2]


def test_a_shared_basic_event_is_the_same_event_in_both_branches() -> None:
    """Two branches naming A must not produce two unrelated cut sets."""
    tree = FaultTree(Event("TOP", "t", "OR", (
        Event("G1", "g", "AND", (_basic("A"), _basic("B"))),
        Event("G2", "g", "AND", (_basic("A"), _basic("C"))))))
    assert tree.cut_sets() == (frozenset({"A", "B"}), frozenset({"A", "C"}))


def test_duplicate_cut_sets_are_collapsed() -> None:
    tree = FaultTree(Event("TOP", "t", "OR", (_basic("A"), _basic("A"))))
    assert tree.cut_sets() == (frozenset({"A"}),)


# --- the file parses, and refuses nonsense -----------------------------------
def _write(tmp_path: Path, doc: object) -> Path:
    path = tmp_path / "tree.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


def test_the_shipped_tree_loads() -> None:
    tree = load_tree()
    assert tree.root.identifier == "TOP"
    assert tree.hazard and tree.goal


def test_a_file_without_a_top_event_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FaultTreeError, match="no top_event"):
        load_tree(_write(tmp_path, {"version": 1}))


def test_an_unknown_gate_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FaultTreeError, match="expected AND or OR"):
        load_tree(_write(tmp_path, {"top_event": {
            "id": "T", "title": "t", "gate": "XOR",
            "children": [{"id": "A", "title": "a"}]}}))


def test_a_basic_event_with_a_gate_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FaultTreeError, match="cannot have gate"):
        load_tree(_write(tmp_path, {"top_event": {
            "id": "T", "title": "t", "gate": "OR", "children": [
                {"id": "A", "title": "a", "gate": "AND"}]}}))


def test_a_gate_cannot_be_challenged_by_a_fault(tmp_path: Path) -> None:
    """Faults attack basic events. A fault on a gate is a category error."""
    with pytest.raises(FaultTreeError, match="Faults attack basic events"):
        load_tree(_write(tmp_path, {"top_event": {
            "id": "T", "title": "t", "gate": "OR",
            "challenged_by": ["FLT-C01"],
            "children": [{"id": "A", "title": "a"}]}}))


def test_an_event_without_a_title_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FaultTreeError, match="no title"):
        load_tree(_write(tmp_path, {"top_event": {"id": "T"}}))


def test_an_event_without_an_id_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FaultTreeError, match="missing 'id'"):
        load_tree(_write(tmp_path, {"top_event": {"title": "t"}}))


def test_one_id_with_two_titles_is_refused(tmp_path: Path) -> None:
    """Reusing an id is how the algebra knows two branches mean one event.

    Reusing it for two DIFFERENT events would silently merge them and make
    every cut set through them wrong.
    """
    with pytest.raises(FaultTreeError, match="different titles"):
        load_tree(_write(tmp_path, {"top_event": {
            "id": "T", "title": "t", "gate": "OR", "children": [
                {"id": "A", "title": "one"}, {"id": "A", "title": "two"}]}}))


# --- the modelling error this file had to fix --------------------------------
def test_the_demand_is_not_part_of_the_cut_sets() -> None:
    """The first version of the tree put it there and broke the whole gate.

    With AND(demand, protection fails) every cut set contains a demand event,
    every order rises by one, and there are no order-1 cut sets at all. The
    single-point-of-failure gate then passes while guarding nothing.
    """
    events = set(load_tree().basic_events())
    assert "BE-STALL" not in events
    assert "BE-OVERLOAD" not in events


def test_there_are_single_point_cut_sets_at_all() -> None:
    """A gate over an empty list passes for the wrong reason."""
    assert load_tree().by_order(1), (
        "no order-1 cut sets, so the single-point gate guards nothing")


# --- the gate ----------------------------------------------------------------
def test_no_single_point_of_failure_is_unattacked() -> None:
    """One basic event reaching the top event alone, that nobody injects."""
    result = coverage(load_tree(), _known_faults(), _attacked_pairs())
    assert not result.unattacked_single_points, (
        "these single points of failure have no injected fault challenging "
        f"them: {list(result.unattacked_single_points)}")


def test_a_fault_that_does_not_exist_does_not_count_as_coverage() -> None:
    """A dangling reference reads as coverage and is not.

    This is why `coverage()` intersects with the real catalog instead of just
    checking the list is non-empty.
    """
    tree = FaultTree(Event("TOP", "t", "OR", (
        Event("BE-X", "x", challenged_by=("FLT-DOES-NOT-EXIST",)),)))
    result = coverage(tree, _known_faults())
    assert result.unattacked_single_points == ("BE-X",)


def test_a_declared_gap_is_reported_separately_from_a_missing_one() -> None:
    """An acknowledged gap with a reason is a finding; silence is a defect."""
    tree = FaultTree(Event("TOP", "t", "OR", (
        Event("BE-Y", "y", unattacked_reason="cannot be injected here"),)))
    result = coverage(tree, _known_faults())
    assert result.unattacked_single_points == ()
    assert result.declared_unattackable == ("BE-Y",)


# --- the result the tree exists to produce -----------------------------------
def test_the_common_cause_event_is_a_single_point_of_failure() -> None:
    """Why a redundant design can still have one, and the chain cannot show it.

    Two channels failing together is an order-2 cut set, which is the value
    redundancy buys. A common cause defeats all of them at once, so it sits at
    order 1 and the majority vote buys nothing against it.
    """
    tree = load_tree()
    assert frozenset({"BE-CCF-SUPPLY"}) in tree.by_order(1)
    assert tree.basic_events()["BE-CCF-SUPPLY"].unattacked_reason, (
        "the common-cause event must say why it cannot be injected")


def test_the_redundant_sensor_channels_need_two_failures() -> None:
    """The other half of the same point: redundancy is visible as order 2."""
    pairs = load_tree().by_order(2)
    assert frozenset({"BE-TA-STUCK", "BE-TB-STUCK"}) in pairs


def test_the_documented_residual_reaches_the_top_event_alone() -> None:
    """FLT-T07's gap is not academic: clock drift is a single point of failure."""
    tree = load_tree()
    assert frozenset({"BE-DRIFT"}) in tree.by_order(1)
    assert "FLT-T07" in tree.basic_events()["BE-DRIFT"].challenged_by


# --- the open finding, held at its documented size ---------------------------
def test_the_number_of_unattacked_double_failures_is_the_documented_one() -> None:
    """The tree found three double failures the pair campaign never attacked.

    That is a real finding and it is recorded rather than closed by inventing
    pairs. This test exists so the gap cannot GROW silently: add a branch that
    creates a fourth and this number has to be changed deliberately.
    """
    result = coverage(load_tree(), _known_faults(), _attacked_pairs())
    assert len(result.unmapped_pairs) == DOCUMENTED_UNATTACKED_PAIRS, (
        f"the tree now has {len(result.unmapped_pairs)} unattacked double "
        f"failures against {DOCUMENTED_UNATTACKED_PAIRS} documented: "
        f"{[sorted(p) for p in result.unmapped_pairs]}")


def test_a_pair_covering_a_cut_set_is_recognised() -> None:
    """Otherwise the unmapped count is three because nothing ever matches."""
    tree = FaultTree(Event("TOP", "t", "OR", (
        Event("G", "g", "AND", (
            Event("BE-P", "p", challenged_by=("FLT-S07",)),
            Event("BE-Q", "q", challenged_by=("FLT-S01",)))),)))
    result = coverage(tree, _known_faults(),
                      {frozenset({"FLT-S07", "FLT-S01"})})
    assert result.unmapped_pairs == ()


def test_a_pair_touching_only_half_a_cut_set_does_not_cover_it() -> None:
    tree = FaultTree(Event("TOP", "t", "OR", (
        Event("G", "g", "AND", (
            Event("BE-P", "p", challenged_by=("FLT-S07",)),
            Event("BE-Q", "q", challenged_by=("FLT-S01",)))),)))
    result = coverage(tree, _known_faults(),
                      {frozenset({"FLT-S07", "FLT-A02"})})
    assert len(result.unmapped_pairs) == 1


def test_a_single_fault_does_not_cover_a_two_event_cut_set() -> None:
    """One fault cannot attack a double failure, however well it is aimed."""
    tree = FaultTree(Event("TOP", "t", "OR", (
        Event("G", "g", "AND", (
            Event("BE-P", "p", challenged_by=("FLT-S07",)),
            Event("BE-Q", "q", challenged_by=("FLT-S07",)))),)))
    result = coverage(tree, _known_faults(), {frozenset({"FLT-S07"})})
    assert len(result.unmapped_pairs) == 1


def test_a_pair_carrying_an_irrelevant_fault_does_not_cover_a_cut_set() -> None:
    """Both directions are checked, and this is the reverse one.

    Here one fault of the pair happens to challenge both events, so the forward
    check passes. The other fault attacks nothing in the cut set, which means
    this pair was never an experiment on this double failure and must not be
    counted as one.
    """
    tree = FaultTree(Event("TOP", "t", "OR", (
        Event("G", "g", "AND", (
            Event("BE-P", "p", challenged_by=("FLT-S07", "FLT-S01")),
            Event("BE-Q", "q", challenged_by=("FLT-S07",)))),)))
    result = coverage(tree, _known_faults(),
                      {frozenset({"FLT-S07", "FLT-A02"})})
    assert len(result.unmapped_pairs) == 1


def test_every_fault_named_in_the_tree_exists_in_the_catalog() -> None:
    """The mapping must not rot when a fault is renamed."""
    known = _known_faults()
    dangling = {e.identifier: sorted(set(e.challenged_by) - known)
                for e in load_tree().basic_events().values()
                if set(e.challenged_by) - known}
    assert not dangling, f"these point at faults that do not exist: {dangling}"


# --- the picture -------------------------------------------------------------
# A diagram is never diffed, so it can go stale while looking authoritative.
# `scripts/check_docs.py` regenerates and compares it; these check the drawing
# itself is well formed and actually carries the finding.

def test_the_svg_is_well_formed_and_holds_every_event() -> None:
    import xml.etree.ElementTree as ET

    from fih.fault_tree import render_svg

    tree = load_tree()
    root = ET.fromstring(render_svg(tree))
    text = "".join(node.text or "" for node in root.iter())
    for identifier in tree.basic_events():
        assert identifier in text, f"{identifier} is missing from the diagram"


def test_the_diagram_marks_the_single_points_of_failure() -> None:
    """A picture that does not carry the finding is decoration."""
    from fih.fault_tree import render_svg

    svg = render_svg(load_tree())
    assert "order 1" in svg


def test_the_diagram_colours_a_declared_gap_differently_from_an_attacked_one() -> None:
    """The colour IS the finding, so the two must not render the same."""
    from fih.fault_tree import STYLE, render_svg

    tree = load_tree()
    cover = coverage(tree, _known_faults(), _attacked_pairs())
    svg = render_svg(tree, cover)
    assert STYLE["declared"][0] in svg, "the declared gap is not marked"
    assert STYLE["attacked"][0] in svg, "attacked events are not marked"
    assert STYLE["declared"][0] != STYLE["attacked"][0]


def test_an_unattacked_single_point_is_drawn_in_the_alarming_colour() -> None:
    from fih.fault_tree import STYLE, Coverage, render_svg

    tree = FaultTree(Event("TOP", "t", "OR", (Event("BE-X", "x"),)))
    svg = render_svg(tree, Coverage(unattacked_single_points=("BE-X",)))
    assert STYLE["missing"][0] in svg


def test_rendering_is_deterministic() -> None:
    """Otherwise the staleness gate would fail on every run."""
    from fih.fault_tree import render_svg

    tree = load_tree()
    assert render_svg(tree) == render_svg(tree)


def test_a_long_title_is_trimmed_visibly_rather_than_silently() -> None:
    """Silent truncation lets the picture assert a shortened title as whole."""
    from fih.fault_tree import render_svg

    tree = FaultTree(Event("TOP", "t", "OR", (
        Event("BE-LONG", "x" * 400),)))
    assert "\u2026" in render_svg(tree)


def test_an_and_gate_is_labelled_as_one_in_the_drawing() -> None:
    """Reading an AND pair as two OR children inverts the whole conclusion."""
    from fih.fault_tree import render_svg

    assert "[AND]" in render_svg(load_tree())
