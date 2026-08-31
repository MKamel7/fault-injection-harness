"""Draw the whole safety argument as one SVG.

    uv run --group dev python scripts/render_chain.py

Reads the same files the campaign reads and writes docs/traceability-chain.svg.
`scripts/check_docs.py` regenerates it and compares, so a stale diagram fails
the build rather than sitting there looking authoritative.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fih.catalog import load_catalog
from fih.chain import build_chain, dangling, render_svg
from fih.traceability import load_goals, load_hazards, load_requirements

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "traceability-chain.svg"


def build() -> str:
    chain = build_chain(load_hazards(), load_goals(),
                        load_requirements(), load_catalog())
    broken = dangling(chain)
    if broken:
        # An arrow pointing at nothing asserts a link that does not exist, and
        # a diagram is never diffed, so this has to be loud.
        raise SystemExit(
            "chain has edges naming something that does not exist: "
            + ", ".join(f"{a} -> {b}" for a, b in broken))
    return render_svg(chain)


def main() -> int:
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
