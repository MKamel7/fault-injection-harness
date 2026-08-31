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
import subprocess
import sys
from pathlib import Path

from fih.catalog import load_catalog
from fih.chain import build_chain, render_svg
from fih.dual_point import load_pairs
from fih.traceability import (
    load_goals,
    load_hazards,
    load_requirements,
)


def render_chain() -> str:
    """The chain diagram as it should be, for comparison with the committed one."""
    return render_svg(build_chain(load_hazards(), load_goals(),
                                  load_requirements(), load_catalog()))

ROOT = Path(__file__).resolve().parents[1]


def _summary_figure(coverage: str, label: str) -> int:
    """Read one number out of the generated coverage report's summary.

    The report is the right source rather than a recount here, because CI
    regenerates it and fails on any diff, so a figure taken from it is a figure
    the code produced on this commit.
    """
    found = re.search(rf"^- {re.escape(label)}: \*\*(\d+)\*\*", coverage, re.M)
    assert found is not None, f"coverage report has no {label!r} line"
    return int(found.group(1))


def _collected_tests() -> int:
    """How many tests the suite actually has.

    Collection rather than a run: it is fast, it needs no coverage threshold to
    be met, and the count is what the documents claim. `--no-cov` because the
    configured fail-under would otherwise make collection exit non-zero.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-cov"],
        cwd=ROOT, capture_output=True, text=True, check=False)
    found = re.search(r"^(\d+) tests collected", result.stdout, re.M)
    assert found is not None, f"could not count tests:\n{result.stdout[-2000:]}"
    return int(found.group(1))


def main() -> int:
    faults = load_catalog()
    by_id = {f.id: f for f in faults}
    requirements = load_requirements()
    pairs = load_pairs(known=by_id)
    hazards = ROOT / "docs" / "HAZARD_ANALYSIS.md"
    haz_text = hazards.read_text()
    coverage = (ROOT / "report" / "coverage.md").read_text()

    facts = {
        "faults": len(faults),
        "hazards": len(re.findall(r"^\| HAZ-", haz_text, re.M)),
        "goals": len(re.findall(r"^\| SG-", haz_text, re.M)),
        "requirements": len(requirements),
        "pairs": len(pairs),
        "residual": sum(1 for f in faults if f.is_residual),
    }

    # Outcome counts, which the fault count alone does not pin down. The README
    # said "20 detected in time" and "176 tests" for two commits after both had
    # moved, because the existing gate checked the size of the catalog and
    # nothing about what the campaign did with it. A headline nobody can check
    # is a headline that goes stale, and on this project of all projects.
    counted = {
        "detected in time": _summary_figure(coverage, "Detected within budget"),
        "detected late": _summary_figure(coverage, "Detected but OUTSIDE budget"),
        "residual": _summary_figure(coverage, "Known residual"),
        "catalogued pairs": facts["pairs"],
        "tests": _collected_tests(),
    }
    pin = re.search(r"embedded-test-automation@(\S+?)\"",
                    (ROOT / "pyproject.toml").read_text())
    assert pin is not None
    dut = pin.group(1)

    # Values and mechanism names that were retired. A document still quoting one
    # is describing a model that no longer exists, which is how the hazard
    # analysis kept a 53.1 C free running equilibrium and a four step stall
    # through two rebuilds.
    retired = {
        "53.1": "free running equilibrium from the speed dependent model",
        "66.2": "free running equilibrium from the speed dependent model",
        "OVERTEMP_ESTIMATED": "trip reason from the withdrawn estimator channel",
        "409.6": "excursion figure from a superseded injection model",
        "1617": "excursion figure from the two sensor design",
    }

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

        for value, why in retired.items():
            if value in text and "HISTORICAL" not in text[
                    max(0, text.index(value) - 400):text.index(value)]:
                problems.append(f"{name}: quotes retired value {value!r} ({why}) "
                                f"without marking the passage historical")

        # a stated fault count must be the real one
        for count in {int(m) for m in re.findall(r"(\d+)\s+faults\b", text)}:
            if count != facts["faults"]:
                problems.append(f"{name}: says {count} faults, there are "
                                f"{facts['faults']}")

        for phrase, expected in counted.items():
            pattern = rf"(\d+)\s+{re.escape(phrase)}\b"
            for count in {int(m) for m in re.findall(pattern, text)}:
                if count != expected:
                    problems.append(f"{name}: says {count} {phrase}, there are "
                                    f"{expected}")

    # The chain diagram is generated, committed, and therefore capable of going
    # stale. A number in a README at least gets read; a picture is never diffed,
    # so a diagram that quietly stopped matching the catalog would keep looking
    # authoritative indefinitely. Regenerating and comparing is the only version
    # of this check worth having.
    chain_svg = ROOT / "docs" / "traceability-chain.svg"
    if not chain_svg.exists():
        problems.append(f"{chain_svg.name} is missing; run "
                        f"scripts/render_chain.py")
    elif chain_svg.read_text(encoding="utf-8") != render_chain():
        problems.append(f"{chain_svg.name} is out of date with the catalog or "
                        f"the hazard analysis; run scripts/render_chain.py")

    if problems:
        print("Documentation contradicts the code:")
        for problem in sorted(set(problems)):
            print(f"  {problem}")
        return 1

    print(f"docs consistent: {facts | counted}, DUT {dut}, chain diagram current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
