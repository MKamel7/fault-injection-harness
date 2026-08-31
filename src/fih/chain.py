"""The whole safety argument as one picture, generated from the data.

WHY THIS EXISTS. The chain this project is actually about runs

    hazard -> safety goal -> safety requirement -> fault -> detection ->
    FTTI -> evidence

and until now it was spread across three documents plus a generated matrix. A
reader had to hold `docs/HAZARD_ANALYSIS.md`, `docs/SAFETY_ARGUMENT.md` and
`report/traceability.md` open side by side to see that any single hazard is
answered by anything at all. The chain is the intellectual contribution of the
repository, and it was the one thing not on a page.

WHY IT IS GENERATED RATHER THAN DRAWN. A hand-drawn diagram is a fourth place
for the same facts to live, and this repository has already been bitten by
exactly that: the README claimed 204 tests against a suite of 225 for four
weeks, and the docs gate was correctly failing on it the whole time. A picture
that is not generated from the catalog would go stale the first time a fault is
added, and unlike a number in a README nobody would notice, because a diagram
looks authoritative and is never diffed. So the SVG is built from the same
loaders the campaign uses, and `scripts/check_docs.py` regenerates it and
compares, which means a stale diagram fails the build.

WHAT THE COLOURS MEAN. A fault is drawn by its catalogued expectation, not by
its last run: `detected` in time, `late`, or `residual`. The campaign gates
whether reality matches that expectation; this picture shows what the argument
CLAIMS, and the coverage report shows whether the claim held. Colouring by live
result would make the same diagram mean different things on different days.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

from fih.catalog import Fault
from fih.traceability import Goal, Hazard, Requirement

#: Column x positions and widths. Five columns rather than seven: detection,
#: FTTI and evidence are properties OF a fault, so they ride on the fault node
#: instead of becoming three more columns of one-to-one arrows.
COLUMNS = (
    ("Hazard", 20, 200),
    ("Safety goal", 260, 220),
    ("Safety requirement", 520, 260),
    ("Fault", 820, 300),
)

ROW_HEIGHT = 46
TOP = 70
PADDING = 24

#: Catalogued expectation -> (fill, stroke, what it means).
EXPECTATION_STYLE = {
    "detected": ("#0f3d2e", "#2f9e6e", "detected inside its FTTI"),
    "late": ("#463206", "#c99a1e", "detected, but outside its FTTI"),
    "residual": ("#4a1d1d", "#d95c5c", "the design cannot catch it"),
}


@dataclass(frozen=True)
class Node:
    key: str
    column: int
    label: str
    detail: str
    row: int
    style: str = "plain"


@dataclass(frozen=True)
class Chain:
    """Nodes and edges of the whole argument, before anything is drawn."""

    nodes: tuple[Node, ...]
    edges: tuple[tuple[str, str], ...]

    def node(self, key: str) -> Node | None:
        return next((n for n in self.nodes if n.key == key), None)


def build_chain(hazards: tuple[Hazard, ...], goals: tuple[Goal, ...],
                requirements: tuple[Requirement, ...],
                faults: tuple[Fault, ...]) -> Chain:
    """Assemble the graph. Every edge is a link something else already asserts.

    Nothing is invented here: a hazard connects to a goal because the goal's own
    row names it, and a requirement connects to a fault because the fault's
    `challenges` list names the requirement. That is what makes the picture
    evidence rather than illustration.
    """
    nodes: list[Node] = []
    edges: list[tuple[str, str]] = []

    for row, hazard in enumerate(hazards):
        nodes.append(Node(hazard.id, 0, hazard.id, hazard.text, row))

    for row, goal in enumerate(goals):
        nodes.append(Node(goal.id, 1, goal.id, goal.text, row))
        edges.extend((hazard, goal.id) for hazard in goal.hazards)

    for row, requirement in enumerate(requirements):
        budget = requirement.ftti_text or "no budget"
        nodes.append(Node(requirement.id, 2, requirement.id,
                          f"{requirement.text}  [FTTI {budget}]", row))
        edges.extend((goal, requirement.id) for goal in requirement.goals)

    for row, fault in enumerate(faults):
        budget = "invariant" if fault.ftti_steps is None else f"{fault.ftti_steps} steps"
        nodes.append(Node(fault.id, 3, fault.id,
                          f"{fault.title}  [{budget}]", row,
                          style=fault.expectation))
        edges.extend((claim, fault.id) for claim in fault.challenges)

    return Chain(tuple(nodes), tuple(edges))


def dangling(chain: Chain) -> tuple[tuple[str, str], ...]:
    """Edges naming something that is not a node.

    A picture with an arrow pointing at nothing is worse than no picture: it
    asserts a link that does not exist and looks authoritative doing it.
    """
    keys = {node.key for node in chain.nodes}
    return tuple((a, b) for a, b in chain.edges
                 if a not in keys or b not in keys)


#: Approximate advance width of one character at font-size 10 in the sans stack
#: above. Used to keep detail text inside its box: the first version placed the
#: detail after the label on the same line and it ran past the right edge of
#: every narrow column, which is the kind of defect a generated diagram hides
#: because nobody diffs a picture.
CHAR_WIDTH = 5.0


def fit(text: str, box_width: int, inset: int = 18) -> str:
    """Trim `text` to what actually fits, marking the trim with an ellipsis.

    Truncating silently would let the picture assert a shortened requirement as
    though it were the whole one.
    """
    limit = max(8, int((box_width - inset) / CHAR_WIDTH))
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "…"


def render_svg(chain: Chain) -> str:
    """The chain as a standalone SVG, readable on a light or dark background."""
    rows = max((n.row for n in chain.nodes), default=0) + 1
    height = TOP + rows * ROW_HEIGHT + PADDING
    width = COLUMNS[-1][1] + COLUMNS[-1][2] + PADDING

    def geometry(node: Node) -> tuple[int, int, int]:
        _, x, w = COLUMNS[node.column]
        return x, TOP + node.row * ROW_HEIGHT, w

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" '
        f'font-family="Segoe UI, Helvetica, Arial, sans-serif">',
        '<rect width="100%" height="100%" fill="#11141a"/>',
        f'<text x="{PADDING}" y="30" fill="#e8eaee" font-size="17" '
        f'font-weight="600">Hazard to evidence, one chain</text>',
        f'<text x="{PADDING}" y="50" fill="#9aa3af" font-size="12">'
        f'Generated from docs/HAZARD_ANALYSIS.md and catalog/faults.yaml. '
        f'Every arrow is a link one of those files asserts.</text>',
    ]

    for name, x, w in COLUMNS:
        out.append(f'<text x="{x}" y="{TOP - 12}" fill="#6f7784" font-size="11" '
                   f'letter-spacing="0.08em">{escape(name.upper())}</text>')
        out.append(f'<line x1="{x}" y1="{TOP - 6}" x2="{x + w}" y2="{TOP - 6}" '
                   f'stroke="#2a2f3a" stroke-width="1"/>')

    for source, target in chain.edges:
        a, b = chain.node(source), chain.node(target)
        if a is None or b is None:
            continue
        ax, ay, aw = geometry(a)
        bx, by, _ = geometry(b)
        y1, y2 = ay + ROW_HEIGHT // 2 - 8, by + ROW_HEIGHT // 2 - 8
        mid = (ax + aw + bx) / 2
        out.append(f'<path d="M{ax + aw} {y1} C{mid} {y1} {mid} {y2} {bx} {y2}" '
                   f'fill="none" stroke="#39404d" stroke-width="1"/>')

    for node in chain.nodes:
        x, y, w = geometry(node)
        fill, stroke, _ = EXPECTATION_STYLE.get(node.style,
                                                ("#1b1f27", "#39404d", ""))
        out.append(f'<rect x="{x}" y="{y - 14}" width="{w}" height="34" rx="5" '
                   f'fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
        out.append(f'<text x="{x + 9}" y="{y}" fill="#e8eaee" font-size="11" '
                   f'font-weight="600">{escape(node.label)}</text>')
        # Detail on its own line, not trailing the label: sharing the line
        # overflowed every narrow column.
        out.append(f'<text x="{x + 9}" y="{y + 13}" fill="#9aa3af" '
                   f'font-size="10">{escape(fit(node.detail, w))}</text>')

    legend_y = height - 10
    offset = PADDING
    for expectation, (fill, stroke, meaning) in EXPECTATION_STYLE.items():
        out.append(f'<rect x="{offset}" y="{legend_y - 9}" width="11" '
                   f'height="11" rx="2" fill="{fill}" stroke="{stroke}"/>')
        out.append(f'<text x="{offset + 17}" y="{legend_y}" fill="#9aa3af" '
                   f'font-size="10">{escape(expectation)}: {escape(meaning)}</text>')
        offset += 30 + len(f"{expectation}: {meaning}") * 5

    out.append("</svg>")
    return "\n".join(out) + "\n"
