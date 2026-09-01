"""Draw the fault tree as one SVG.

    uv run --group dev python scripts/render_tree.py

Reads catalog/fault_tree.yaml and writes docs/fault-tree.svg.
`scripts/check_docs.py` regenerates it and compares, so a stale diagram fails
the build rather than sitting there looking authoritative.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fih.catalog import load_catalog
from fih.dual_point import load_pairs
from fih.fault_tree import coverage, load_tree, render_svg

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "fault-tree.svg"


def build() -> str:
    tree = load_tree()
    cover = coverage(tree, {f.id for f in load_catalog()},
                     {frozenset((p.latent, p.primary)) for p in load_pairs()})
    if cover.unattacked_single_points:
        # A single point of failure nobody injects is exactly what this tree
        # exists to find, and a picture is never diffed, so it has to be loud.
        raise SystemExit(
            "single points of failure with no injected fault: "
            + ", ".join(cover.unattacked_single_points))
    return render_svg(tree, cover)


def main() -> int:
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
