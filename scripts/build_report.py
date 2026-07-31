"""Run the campaign and write the traceability matrix and coverage report.

    uv run --group dev python scripts/build_report.py

Exits non-zero if any fault fails its verdict or if traceability has a gap, so
CI publishes the report as an artifact AND fails the build when the evidence
stops supporting the claims. A report that is generated but not gated is
decoration.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fih.campaign import run_all
from fih.catalog import load_catalog
from fih.protected_campaign import run_all_protected
from fih.report import build, protection_markdown
from fih.traceability import load_requirements, matrix_markdown

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "report"


def main() -> int:
    faults = load_catalog()
    requirements = load_requirements()
    results = run_all(faults)

    REPORT_DIR.mkdir(exist_ok=True)
    matrix = REPORT_DIR / "traceability.md"
    coverage = REPORT_DIR / "coverage.md"
    protection = REPORT_DIR / "protection.md"

    matrix.write_text(matrix_markdown(faults, requirements))
    text, all_ok = build(faults, results, requirements)
    coverage.write_text(text)
    protection.write_text(
        protection_markdown(faults, results, run_all_protected(faults)))

    print(f"wrote {matrix.relative_to(ROOT)}")
    print(f"wrote {coverage.relative_to(ROOT)}")
    print(f"wrote {protection.relative_to(ROOT)}")
    print(f"{len(faults)} faults, "
          f"{sum(1 for f in faults if f.is_residual)} residual, "
          f"verdicts {'all met' if all_ok else 'NOT all met'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
