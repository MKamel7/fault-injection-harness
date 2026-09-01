"""A fault tree over the thermal top event, with the campaign mapped onto it.

WHAT THIS ANSWERS THAT THE CHAIN DOES NOT. `chain.py` proves every injected
fault descends from a hazard: nothing is injected because it seemed interesting.
It cannot prove the converse, that every WAY the hazard happens has been
attacked, because it only ever walks from faults that exist. A fault tree starts
at the top event and decomposes downwards, so its minimal cut sets are a list
the campaign can be held against. One artefact justifies what is there; this one
finds what is missing.

MINIMAL CUT SETS, and why the minimality step is not optional. A cut set is a
combination of basic events sufficient to reach the top event. Expanding the
tree produces many that are merely supersets of smaller ones: if {A} alone
reaches the top, then {A, B} does too and says nothing new. Keeping both would
inflate the count and, worse, would let a single point of failure hide inside a
list of plausible-looking pairs. `minimise()` removes every set that contains
another, which is what makes "order 1" mean single point of failure.

THE ORDER OF A CUT SET IS THE RESULT WORTH READING.

    order 1   a single basic event reaches the top event. A single point of
              failure. Every one must be challenged by an injected fault.
    order 2   two independent faults are required. This is the dual-point
              campaign's territory, and each pair should map to an entry in
              catalog/dual_point.yaml.

COMMON CAUSE IS WHY THIS TREE EXISTS. Redundancy shows up here as order-2 cut
sets: two channels must fail together. A common-cause event defeats all of them
at once and is therefore ORDER 1, which is the whole reason a redundant design
can still have a single point of failure. `BE-CCF-SUPPLY` is exactly that, it is
declared unattackable by this harness, and the gate below makes that declaration
explicit rather than letting it be an absence nobody noticed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any

import yaml

DEFAULT_TREE = Path(__file__).resolve().parents[2] / "catalog" / "fault_tree.yaml"


class FaultTreeError(ValueError):
    """A malformed fault tree."""


@dataclass(frozen=True)
class Event:
    """One node. A gate if it has children, a basic event if it does not."""

    identifier: str
    title: str
    gate: str = ""
    children: tuple[Event, ...] = ()
    challenged_by: tuple[str, ...] = ()
    unattacked_reason: str = ""
    note: str = ""

    @property
    def is_basic(self) -> bool:
        return not self.children


def _parse(raw: dict[str, Any], seen: dict[str, str]) -> Event:
    if "id" not in raw:
        raise FaultTreeError("an event is missing 'id'")
    identifier = str(raw["id"])
    title = str(raw.get("title", ""))
    if not title:
        raise FaultTreeError(f"{identifier} has no title")

    # A basic event may legitimately appear in several branches: channel A being
    # stuck contributes to two different pairs. Reusing the id is how the cut
    # set algebra knows they are THE SAME event, which is what makes
    # {A, B} and {A, E} two cut sets rather than four unrelated ones. What is
    # not allowed is the same id carrying two different titles.
    if identifier in seen and seen[identifier] != title:
        raise FaultTreeError(
            f"{identifier} is used twice with different titles: "
            f"{seen[identifier]!r} and {title!r}")
    seen[identifier] = title

    children = tuple(_parse(child, seen) for child in raw.get("children", ()))
    gate = str(raw.get("gate", "")).upper()
    if children and gate not in ("AND", "OR"):
        raise FaultTreeError(
            f"{identifier} has children and gate {gate!r}; expected AND or OR")
    if not children and gate:
        raise FaultTreeError(
            f"{identifier} is a basic event and cannot have gate {gate!r}")

    challenged = tuple(raw.get("challenged_by", ()) or ())
    reason = str(raw.get("unattacked_reason", ""))
    if children and (challenged or reason):
        raise FaultTreeError(
            f"{identifier} is a gate, so it cannot be challenged by a fault. "
            f"Faults attack basic events.")

    return Event(identifier=identifier, title=title, gate=gate,
                 children=children, challenged_by=challenged,
                 unattacked_reason=reason, note=str(raw.get("note", "")))


@dataclass(frozen=True)
class FaultTree:
    root: Event
    hazard: str = ""
    goal: str = ""

    def basic_events(self) -> dict[str, Event]:
        """Every basic event by id, deduplicated across branches."""
        found: dict[str, Event] = {}

        def walk(event: Event) -> None:
            if event.is_basic:
                found.setdefault(event.identifier, event)
            for child in event.children:
                walk(child)

        walk(self.root)
        return found

    def cut_sets(self) -> tuple[frozenset[str], ...]:
        """The minimal cut sets, smallest first."""
        return minimise(_expand(self.root))

    def by_order(self, order: int) -> tuple[frozenset[str], ...]:
        return tuple(c for c in self.cut_sets() if len(c) == order)


def _expand(event: Event) -> tuple[frozenset[str], ...]:
    """Cut sets of one node, before minimisation.

    OR takes the union of its children's cut sets: any one of them suffices.
    AND takes the cartesian product and unions each combination: all are
    required together.
    """
    if event.is_basic:
        return (frozenset({event.identifier}),)

    children = [_expand(child) for child in event.children]
    if event.gate == "OR":
        return tuple(cut for group in children for cut in group)

    combined: list[frozenset[str]] = []
    for combination in product(*children):
        union: set[str] = set()
        for cut in combination:
            union |= cut
        combined.append(frozenset(union))
    return tuple(combined)


def minimise(cuts: tuple[frozenset[str], ...]) -> tuple[frozenset[str], ...]:
    """Drop every cut set that contains another, then order for reading.

    Without this a single point of failure hides inside a list of
    plausible-looking pairs: if {A} reaches the top event then so does {A, B},
    and reporting both makes the design look better than it is.
    """
    unique = set(cuts)
    minimal = [c for c in unique
               if not any(other < c for other in unique)]
    return tuple(sorted(minimal, key=lambda c: (len(c), sorted(c))))


def load_tree(path: Path | str = DEFAULT_TREE) -> FaultTree:
    doc = yaml.safe_load(Path(path).read_text())
    if not isinstance(doc, dict) or "top_event" not in doc:
        raise FaultTreeError("the fault tree file has no top_event")
    top = doc["top_event"]
    return FaultTree(root=_parse(top, {}),
                     hazard=str(top.get("hazard", "")),
                     goal=str(top.get("goal", "")))


# --- mapping the campaign onto the tree --------------------------------------

@dataclass(frozen=True)
class Coverage:
    """How the campaign stands against the tree.

    `unattacked_single_points` is the one that must stay empty. The others are
    reported so a reader can see the shape of what is and is not covered rather
    than only whether a gate passed.
    """

    single_points: tuple[frozenset[str], ...] = ()
    unattacked_single_points: tuple[str, ...] = ()
    declared_unattackable: tuple[str, ...] = ()
    higher_order: tuple[frozenset[str], ...] = ()
    unmapped_pairs: tuple[frozenset[str], ...] = field(default=())


def coverage(tree: FaultTree, known_faults: set[str],
             attacked_pairs: set[frozenset[str]] | None = None) -> Coverage:
    """Measure the campaign against the cut sets.

    `known_faults` is the fault catalog. A basic event naming a fault that does
    not exist is as bad as naming none, because the reference reads as coverage
    and is not, so both land in `unattacked_single_points`.

    A basic event carrying `unattacked_reason` is DECLARED, not missing. That
    distinction is the whole point: an acknowledged gap with a stated reason is
    a finding, while a silent absence is a defect.
    """
    basics = tree.basic_events()
    singles = tree.by_order(1)

    unattacked: list[str] = []
    declared: list[str] = []
    for cut in singles:
        (identifier,) = tuple(cut)
        event = basics[identifier]
        real = set(event.challenged_by) & known_faults
        if real:
            continue
        if event.unattacked_reason:
            declared.append(identifier)
        else:
            unattacked.append(identifier)

    pairs = tree.by_order(2)
    attacked = attacked_pairs or set()
    unmapped = tuple(p for p in pairs if not any(
        _pair_matches(p, basics, a) for a in attacked))

    return Coverage(single_points=singles,
                    unattacked_single_points=tuple(sorted(unattacked)),
                    declared_unattackable=tuple(sorted(declared)),
                    higher_order=pairs,
                    unmapped_pairs=unmapped)


def _pair_matches(cut: frozenset[str], basics: dict[str, Event],
                  attacked: frozenset[str]) -> bool:
    """Does an injected pair of FAULTS cover a cut set of BASIC EVENTS?

    The two catalogs speak different languages: `dual_point.yaml` names faults,
    the tree names events. A pair covers a cut set when each event in the cut
    set is challenged by at least one fault in the pair, and every fault in the
    pair is used. Requiring both directions stops a pair that happens to touch
    one event of a cut set being counted as having attacked the whole thing.
    """
    if len(cut) != len(attacked):
        return False
    for identifier in cut:
        if not set(basics[identifier].challenged_by) & attacked:
            return False
    return all(any(fault in basics[i].challenged_by for i in cut)
               for fault in attacked)


# --- the picture -------------------------------------------------------------
# Same reasoning as `chain.py`: the SVG is generated from this catalog and
# regenerated by `scripts/check_docs.py`, which fails the build on a diff. A
# number in a README at least gets read; a diagram is never diffed, so a stale
# one keeps looking authoritative indefinitely.

from html import escape  # noqa: E402

BOX_WIDTH = 232
BOX_HEIGHT = 40
H_GAP = 26
V_GAP = 34
MARGIN = 26
TOP_OFFSET = 74

#: Basic events are coloured by how the campaign stands against them, so the
#: picture carries the finding rather than only the structure.
STYLE = {
    "attacked": ("#16241b", "#2f6b41", "challenged by an injected fault"),
    "declared": ("#2a1f14", "#8a5a2b", "known gap, declared unattackable here"),
    "missing": ("#2a1519", "#8a2f3b", "single point of failure, not attacked"),
    "gate": ("#1b1f27", "#39404d", "gate"),
}


def _layout(event: Event, depth: int, cursor: list[int],
            out: list[tuple[Event, int, int, int]]) -> tuple[int, int]:
    """Place children first, then centre the parent over them.

    A tidy-tree layout in miniature. Leaves are packed left to right in visit
    order; a gate is centred on the span of its children, which is what makes
    an AND pair read as a pair rather than as two unrelated boxes.
    """
    if event.is_basic:
        x = cursor[0]
        cursor[0] += BOX_WIDTH + H_GAP
        out.append((event, x, depth, x))
        return x, x
    spans = [_layout(child, depth + 1, cursor, out) for child in event.children]
    left, right = spans[0][0], spans[-1][1]
    centre = (left + right) // 2
    out.append((event, centre, depth, centre))
    return left, right


def render_svg(tree: FaultTree, cover: Coverage | None = None) -> str:
    """The tree as a standalone SVG, readable on a dark background."""
    placed: list[tuple[Event, int, int, int]] = []
    _layout(tree.root, 0, [MARGIN], placed)

    singles = {next(iter(c)) for c in tree.by_order(1)}
    declared = set(cover.declared_unattackable) if cover else set()
    missing = set(cover.unattacked_single_points) if cover else set()

    depth = max(d for _, _, d, _ in placed)
    width = max(x + BOX_WIDTH for _, x, _, _ in placed) + MARGIN
    height = TOP_OFFSET + (depth + 1) * (BOX_HEIGHT + V_GAP) + 46

    def geometry(d: int) -> int:
        return TOP_OFFSET + d * (BOX_HEIGHT + V_GAP)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" '
        f'font-family="Segoe UI, Helvetica, Arial, sans-serif">',
        '<rect width="100%" height="100%" fill="#11141a"/>',
        f'<text x="{MARGIN}" y="30" fill="#e8eaee" font-size="17" '
        f'font-weight="600">{escape(tree.root.title)}</text>',
        f'<text x="{MARGIN}" y="50" fill="#9aa3af" font-size="12">'
        f'Generated from catalog/fault_tree.yaml. Scoped to the protection '
        f'function ON DEMAND: the thermal demand is a condition, not a cut set '
        f'member.</text>',
    ]

    position = {event.identifier: (x, d) for event, x, d, _ in placed}
    for event, x, d, _ in placed:
        for child in event.children:
            cx, cd = position[child.identifier]
            x1, y1 = x + BOX_WIDTH // 2, geometry(d) + BOX_HEIGHT
            x2, y2 = cx + BOX_WIDTH // 2, geometry(cd)
            mid = (y1 + y2) / 2
            out.append(f'<path d="M{x1} {y1} C{x1} {mid} {x2} {mid} {x2} {y2}" '
                       f'fill="none" stroke="#39404d" stroke-width="1"/>')

    for event, x, d, _ in placed:
        y = geometry(d)
        if event.is_basic:
            key = ("missing" if event.identifier in missing
                   else "declared" if event.identifier in declared
                   else "attacked")
        else:
            key = "gate"
        fill, stroke, _meaning = STYLE[key]
        out.append(f'<rect x="{x}" y="{y}" width="{BOX_WIDTH}" '
                   f'height="{BOX_HEIGHT}" rx="5" fill="{fill}" '
                   f'stroke="{stroke}" stroke-width="1"/>')
        badge = f"  [{event.gate}]" if event.gate else ""
        order = "  order 1" if event.identifier in singles else ""
        out.append(f'<text x="{x + 9}" y="{y + 16}" fill="#e8eaee" '
                   f'font-size="11" font-weight="600">'
                   f'{escape(event.identifier + badge + order)}</text>')
        out.append(f'<text x="{x + 9}" y="{y + 31}" fill="#9aa3af" '
                   f'font-size="10">{escape(_fit(event.title))}</text>')

    legend_y = height - 12
    offset = MARGIN
    for _key, (fill, stroke, meaning) in STYLE.items():
        out.append(f'<rect x="{offset}" y="{legend_y - 9}" width="11" '
                   f'height="11" rx="2" fill="{fill}" stroke="{stroke}"/>')
        out.append(f'<text x="{offset + 17}" y="{legend_y}" fill="#9aa3af" '
                   f'font-size="10">{escape(meaning)}</text>')
        offset += 34 + len(meaning) * 5
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _fit(text: str, width: int = BOX_WIDTH) -> str:
    """Trim to what fits, marking the trim. Silent truncation would let the
    picture assert a shortened title as though it were the whole one."""
    limit = max(8, int((width - 18) / 5.6))
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "\u2026"
