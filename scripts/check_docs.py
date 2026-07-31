"""Fail the build when a document states a figure the code contradicts.

The documents drifted badly: 23 faults against 24, "6 hazards, 6 safety goals, 10
safety requirements" against 8, 7 and 11, and a DUT pinned at v3.0 while three
files still said v1.3, v1.4 and v1.5. CI diffed `report/` only, so `docs/` and
`README.md` were free to say anything.

This checks the countable claims. It cannot check prose, and it is not trying to:
the point is that the numbers a reader would quote are the numbers the code
produces.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from fih.catalog import load_catalog
from fih.dual_point import load_pairs
from fih.traceability import load_requirements

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    faults = load_catalog()
    by_id = {f.id: f for f in faults}
    requirements = load_requirements()
    pairs = load_pairs(known=by_id)
    hazards = ROOT / "docs" / "HAZARD_ANALYSIS.md"
    haz_text = hazards.read_text()

    facts = {
        "faults": len(faults),
        "hazards": len(re.findall(r"^\| HAZ-", haz_text, re.M)),
        "goals": len(re.findall(r"^\| SG-", haz_text, re.M)),
        "requirements": len(requirements),
        "pairs": len(pairs),
        "residual": sum(1 for f in faults if f.is_residual),
    }
    pin = re.search(r"embedded-test-automation@(\S+?)\"",
                    (ROOT / "pyproject.toml").read_text())
    assert pin is not None
    dut = pin.group(1)

    problems: list[str] = []
    for name in ("README.md", "docs/SAFETY_ARGUMENT.md", "docs/HAZARD_ANALYSIS.md",
                 "docs/STANDARDS_MAPPING.md"):
        text = (ROOT / name).read_text()

        # Only claims about the CURRENT pin are checked. A change impact table
        # naming every past release is correct and must not be flagged, which is
        # why this looks for the phrasing that asserts what is pinned NOW rather
        # than for version strings anywhere.
        for phrase in (r"pinned to tag `(v[\d.]+)`",
                       r"pinned to tag (v[\d.]+)",
                       r"device under test is `embedded-test-automation` (v[\d.]+)"):
            for found in re.findall(phrase, text):
                if found != dut:
                    problems.append(
                        f"{name}: claims the DUT is pinned at {found}, it is {dut}")

        # a stated fault count must be the real one
        for count in {int(m) for m in re.findall(r"(\d+)\s+faults\b", text)}:
            if count != facts["faults"]:
                problems.append(f"{name}: says {count} faults, there are "
                                f"{facts['faults']}")

    if problems:
        print("Documentation contradicts the code:")
        for problem in sorted(set(problems)):
            print(f"  {problem}")
        return 1

    print(f"docs consistent: {facts}, DUT {dut}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
