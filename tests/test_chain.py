"""The chain diagram: the links are real, and the picture stays inside itself.

A generated diagram is only worth more than a drawn one if something checks it.
Two properties matter, and neither is about aesthetics:

  every arrow is a link the source documents assert, and every node it names
  exists, so the picture cannot claim a hazard is answered when it is not

  every label fits the box it is drawn in, because text that overflows is
  silently unreadable and nobody diffs a picture
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from fih.catalog import load_catalog
from fih.chain import (
    CHAR_WIDTH,
    COLUMNS,
    Chain,
    Node,
    build_chain,
    dangling,
    fit,
    render_svg,
)
from fih.traceability import (
    TraceabilityError,
    load_goals,
    load_hazards,
    load_requirements,
)

SVG = "{http://www.w3.org/2000/svg}"


@pytest.fixture(scope="module")
def chain():
    return build_chain(load_hazards(), load_goals(),
                       load_requirements(), load_catalog())


# ---- the links are real ----------------------------------------------------

def test_no_edge_points_at_something_that_does_not_exist(chain):
    """An arrow to a missing node asserts a link nobody wrote down."""
    assert dangling(chain) == ()


def test_every_hazard_reaches_at_least_one_fault(chain):
    """The whole claim of the repository, checked rather than asserted.

    A hazard with no path down to an injected fault is a hazard nothing in the
    campaign challenges, and the diagram would show it sitting alone. That is
    exactly the gap the picture exists to make visible, so if one ever appears
    this test names it rather than leaving it to be spotted by eye.
    """
    forward: dict[str, set[str]] = {}
    for source, target in chain.edges:
        forward.setdefault(source, set()).add(target)

    faults = {n.key for n in chain.nodes if n.column == 3}
    orphans = []
    for hazard in (n.key for n in chain.nodes if n.column == 0):
        seen, stack = set(), [hazard]
        while stack:
            node = stack.pop()
            for nxt in forward.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        if not seen & faults:
            orphans.append(hazard)

    assert orphans == [], f"hazards no fault challenges: {orphans}"


def test_every_fault_traces_back_to_a_hazard(chain):
    """The other direction, which catches a typo in a requirement id."""
    back: dict[str, set[str]] = {}
    for source, target in chain.edges:
        back.setdefault(target, set()).add(source)

    hazards = {n.key for n in chain.nodes if n.column == 0}
    stranded = []
    for fault in (n.key for n in chain.nodes if n.column == 3):
        seen, stack = set(), [fault]
        while stack:
            node = stack.pop()
            for prev in back.get(node, ()):
                if prev not in seen:
                    seen.add(prev)
                    stack.append(prev)
        if not seen & hazards:
            stranded.append(fault)

    assert stranded == [], f"faults descending from no hazard: {stranded}"


def test_the_chain_covers_the_whole_catalog(chain):
    faults = load_catalog()
    drawn = {n.key for n in chain.nodes if n.column == 3}
    assert drawn == {f.id for f in faults}


def test_faults_are_coloured_by_their_catalogued_expectation(chain):
    """Not by the last run. The picture states the claim; the campaign gates it.

    Colouring by live result would make the same committed diagram mean
    different things on different days.
    """
    by_id = {f.id: f for f in load_catalog()}
    for node in chain.nodes:
        if node.column == 3:
            assert node.style == by_id[node.key].expectation


# ---- the picture stays inside itself ---------------------------------------

def test_fit_marks_a_trim_rather_than_truncating_silently():
    trimmed = fit("x" * 400, 100)
    assert trimmed.endswith("…")
    assert len(trimmed) < 400


def test_fit_leaves_short_text_alone():
    assert fit("SR-01", 260) == "SR-01"


def test_no_label_overflows_its_column(chain):
    """The bug the first version shipped.

    Detail text was drawn after the label on the same line, so in the 200 px
    hazard column it started 59 px in and ran about 25 px past the right edge.
    Every column is checked, not just the one that broke.
    """
    widths = {index: width for index, (_, _, width) in enumerate(COLUMNS)}
    for node in chain.nodes:
        drawn = fit(node.detail, widths[node.column])
        assert len(drawn) * CHAR_WIDTH + 18 <= widths[node.column] + 1, (
            f"{node.key}: detail is {len(drawn)} chars in a "
            f"{widths[node.column]} px box")


def test_the_svg_is_well_formed_and_holds_every_node(chain):
    root = ET.fromstring(render_svg(chain))

    assert root.tag == f"{SVG}svg"
    labels = {e.text for e in root.iter(f"{SVG}text")}
    for node in chain.nodes:
        assert node.label in labels, f"{node.key} is not drawn"


def test_the_canvas_is_tall_enough_for_the_longest_column(chain):
    """A column that outgrows the canvas is drawn off the bottom edge."""
    root = ET.fromstring(render_svg(chain))
    height = int(root.get("height"))
    rows = max(n.row for n in chain.nodes) + 1

    assert height > rows * 40, f"{rows} rows will not fit in {height} px"


def test_rendering_is_deterministic(chain):
    """The SVG is committed and gated, so two runs must agree byte for byte."""
    assert render_svg(chain) == render_svg(chain)


def test_a_dangling_edge_is_skipped_rather_than_crashing_the_render():
    """render_svg is reachable without going through the dangling() check.

    The script refuses to write a diagram with a broken link, which is the
    right behaviour there. Anything calling render_svg directly should still
    get a picture rather than a traceback, so the edge is dropped and the
    missing node is simply absent, which is visible.
    """
    broken = Chain(nodes=(Node("HAZ-01", 0, "HAZ-01", "a hazard", 0),),
                   edges=(("HAZ-01", "SG-99"),))

    assert dangling(broken) == (("HAZ-01", "SG-99"),)
    svg = render_svg(broken)
    assert "HAZ-01" in svg
    assert "SG-99" not in svg


# ---- the loaders refuse to succeed on a document that lost its tables -------

def test_missing_safety_goals_is_an_error_not_an_empty_chain(tmp_path):
    """An empty parse must not become an unenforced argument.

    Same reasoning as the FTTI column: a table that quietly returns nothing
    makes every downstream claim vacuous while the build stays green.
    """
    document = tmp_path / "HAZARD_ANALYSIS.md"
    document.write_text("# nothing here\n", encoding="utf-8")

    with pytest.raises(TraceabilityError, match="no SG-xx"):
        load_goals(document)


def test_missing_hazards_is_an_error(tmp_path):
    document = tmp_path / "HAZARD_ANALYSIS.md"
    document.write_text("| SG-01 | a goal | HAZ-01 |\n", encoding="utf-8")

    with pytest.raises(TraceabilityError, match="no HAZ-xx"):
        load_hazards(document)
