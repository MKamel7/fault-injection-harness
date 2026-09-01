"""An educational FMEDA over a synthetic bill of materials.

WHAT THIS IS AND IS NOT. `catalog/fmeda.yaml` holds invented failure rates for a
hypothetical BOM. Everything computed here is arithmetic over invented numbers,
which makes it a demonstration of the METHOD and not a statement about any real
device. `docs/HAZARD_ANALYSIS.md` still says, correctly, that the hazard analysis
carries no component failure rates and that no quantitative metric follows from
it. This is a separate exercise, labelled as one everywhere it surfaces.

THE DISTINCTION THIS MODULE EXISTS TO PRESERVE, and the easiest thing here to
get wrong once quantitative vocabulary is available:

    detection coverage    24 of 29 injected faults were caught. A measured
                          statement about the contents of `catalog/faults.yaml`.
    diagnostic coverage   the fraction of a failure mode's RATE that a mechanism
                          detects, integrated over that mode's occurrences. An
                          ASSUMED INPUT here, never an output.

A campaign cannot produce a DC number. It samples a fault list somebody wrote;
DC integrates over a rate distribution. Conflating them would let "we caught 24
of 29" masquerade as "diagnostic coverage is 83%", which is the kind of sentence
that gets into a safety case and is not true.

WHAT THE CAMPAIGN LEGITIMATELY CONTRIBUTES is falsification, not measurement. A
mode claiming `diagnostic_coverage > 0` names the faults that challenge its
mechanism, and `test_fmeda.py` fails the build if it names none: a coverage
figure nobody has ever tested is an assumption wearing a number. That is the
honest bridge between the two artefacts, and it runs in one direction only.

THE ARITHMETIC, per ISO 26262-5. For a safety-related failure mode with rate L
and diagnostic coverage DC:

    single-point capable, no mechanism    all of L is SPF
    single-point capable, with mechanism  L*(1-DC) is RF, the rest is covered
    not single-point capable              L*(1-DC) is a LATENT multiple-point
                                          fault, L*DC a detected one

    SPFM = 1 - (SPF + RF) / L_total_safety_related
    LFM  = 1 - MPF_latent / (L_total_safety_related - SPF - RF)

Non-safety-related modes are safe faults: they are excluded from both
denominators, which is why a design cannot improve its metrics by adding
harmless parts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

DEFAULT_FMEDA = Path(__file__).resolve().parents[2] / "catalog" / "fmeda.yaml"

#: ISO 26262-5 architectural metric targets, per ASIL. Quoted as the comparison
#: this report is made against, not as a claim to have met any of them.
ASIL_TARGETS: dict[str, tuple[float, float]] = {
    "B": (0.90, 0.60),
    "C": (0.97, 0.80),
    "D": (0.99, 0.90),
}


class FmedaError(ValueError):
    """A malformed FMEDA catalog.

    Raised rather than defaulted, for the same reason `CatalogError` is: a
    metric computed from a file that quietly lost half its modes is a number
    that looks fine and is wrong.
    """


class Classification(str, Enum):
    """Where a mode's UNDETECTED rate lands in the ISO 26262-5 accounting.

    A label per mode, while the ARITHMETIC splits each mode's rate: a covered
    multiple-point mode contributes `detected_fit` to the detected term and
    `undetected_fit` to the latent one, and only the latter decides the metric.
    So `MULTIPLE_POINT_DETECTED` appears only where coverage is exactly 1.0,
    and a mode at DC 0.9 is labelled latent while still contributing nine
    tenths of its rate to the detected total. Reading the labels as a partition
    of the rate is the mistake this docstring exists to prevent; `Metrics` is
    where the rates are actually apportioned.
    """

    SAFE = "safe"
    SINGLE_POINT = "single_point"
    RESIDUAL = "residual"
    MULTIPLE_POINT_LATENT = "multiple_point_latent"
    MULTIPLE_POINT_DETECTED = "multiple_point_detected"


@dataclass(frozen=True)
class FailureMode:
    """One row of the FMEDA."""

    identifier: str
    element: str
    title: str
    lambda_fit: float
    safety_related: bool
    can_violate_alone: bool
    mechanism: str
    diagnostic_coverage: float
    challenged_by: tuple[str, ...]
    note: str = ""

    @property
    def has_mechanism(self) -> bool:
        """A mechanism named "none" is not a mechanism.

        Written this way so the catalog can say `mechanism: none` in the same
        column as a real one, which keeps the file readable as a table.
        """
        return self.mechanism.strip().lower() not in ("", "none")

    @property
    def undetected_fit(self) -> float:
        """The part of this mode's rate no mechanism catches."""
        if not self.has_mechanism:
            return self.lambda_fit
        return self.lambda_fit * (1.0 - self.diagnostic_coverage)

    @property
    def detected_fit(self) -> float:
        return self.lambda_fit - self.undetected_fit

    @property
    def classification(self) -> Classification:
        if not self.safety_related:
            return Classification.SAFE
        if self.can_violate_alone:
            return (Classification.RESIDUAL if self.has_mechanism
                    else Classification.SINGLE_POINT)
        return (Classification.MULTIPLE_POINT_DETECTED
                if self.undetected_fit == 0.0
                else Classification.MULTIPLE_POINT_LATENT)


@dataclass(frozen=True)
class Metrics:
    """The ISO 26262-5 architectural metrics over a set of failure modes.

    Every property is derived rather than stored, so the numbers cannot drift
    apart from the modes they came from.
    """

    modes: tuple[FailureMode, ...]
    target_asil: str

    def _sum(self, predicate: Callable[[FailureMode], bool],
             attribute: str = "lambda_fit") -> float:
        """Rate-weighted sum over the modes a predicate selects.

        `float()` around the `getattr` because the attribute name is dynamic,
        so the property's own annotation is not visible here and the result
        would otherwise be `Any`, which mypy strict rejects at the call site.
        """
        return sum(float(getattr(m, attribute))
                   for m in self.modes if predicate(m))

    @property
    def total_fit(self) -> float:
        return sum(m.lambda_fit for m in self.modes)

    @property
    def safety_related_fit(self) -> float:
        return self._sum(lambda m: m.safety_related)

    @property
    def safe_fit(self) -> float:
        return self._sum(lambda m: not m.safety_related)

    @property
    def spf_fit(self) -> float:
        """Single-point faults: no mechanism, and able to violate alone."""
        return self._sum(
            lambda m: m.classification is Classification.SINGLE_POINT)

    @property
    def rf_fit(self) -> float:
        """Residual faults: the uncovered part of a covered single-point mode."""
        return self._sum(
            lambda m: m.classification is Classification.RESIDUAL,
            "undetected_fit")

    @property
    def mpf_latent_fit(self) -> float:
        return self._sum(
            lambda m: m.classification is Classification.MULTIPLE_POINT_LATENT,
            "undetected_fit")

    @property
    def mpf_detected_fit(self) -> float:
        return self._sum(
            lambda m: m.safety_related and not m.can_violate_alone,
            "detected_fit")

    @property
    def spfm(self) -> float:
        """Single-point fault metric.

        Returns 1.0 for a design with no safety-related failure rate at all,
        which is vacuous rather than excellent. `is_vacuous` is how a caller
        tells the two apart, because a bare 100% here would read as the best
        possible result and means nothing was analysed.
        """
        if not self.safety_related_fit:
            return 1.0
        return 1.0 - (self.spf_fit + self.rf_fit) / self.safety_related_fit

    @property
    def lfm(self) -> float:
        """Latent fault metric.

        The denominator excludes single-point and residual faults: those have
        already failed the first metric, and counting them twice would let a
        design with a large SPF term post a flattering LFM.
        """
        remainder = self.safety_related_fit - self.spf_fit - self.rf_fit
        if remainder <= 0.0:
            return 1.0
        return 1.0 - self.mpf_latent_fit / remainder

    @property
    def is_vacuous(self) -> bool:
        """True when there is nothing safety related to measure."""
        return self.safety_related_fit == 0.0

    def meets_target(self) -> tuple[bool, bool]:
        """(SPFM meets target, LFM meets target) for the stated ASIL.

        A comparison against the published ISO 26262-5 figures, and nothing
        more. Meeting a metric is not conformance: it is one input among an
        assessor's judgement, on rates that are invented here anyway.
        """
        spfm_target, lfm_target = ASIL_TARGETS[self.target_asil]
        return self.spfm >= spfm_target, self.lfm >= lfm_target


def _require(raw: dict[str, Any], key: str, where: str) -> Any:
    if key not in raw:
        raise FmedaError(f"{where} is missing {key!r}")
    return raw[key]


def _parse_mode(raw: dict[str, Any], element: str,
                seen: set[str]) -> FailureMode:
    identifier = str(_require(raw, "id", f"a mode of {element}"))
    if identifier in seen:
        raise FmedaError(f"duplicate failure mode id {identifier!r}")
    seen.add(identifier)

    rate = float(_require(raw, "lambda_fit", identifier))
    if rate < 0:
        raise FmedaError(f"{identifier} has a negative failure rate")

    coverage = float(raw.get("diagnostic_coverage", 0.0))
    if not 0.0 <= coverage <= 1.0:
        raise FmedaError(
            f"{identifier} has a diagnostic coverage of {coverage}, which is "
            f"not a fraction. DC is a proportion of a rate, not a percentage.")

    mode = FailureMode(
        identifier=identifier,
        element=element,
        title=str(_require(raw, "title", identifier)),
        lambda_fit=rate,
        safety_related=bool(_require(raw, "safety_related", identifier)),
        can_violate_alone=bool(_require(raw, "can_violate_alone", identifier)),
        mechanism=str(raw.get("mechanism", "none")),
        diagnostic_coverage=coverage,
        challenged_by=tuple(raw.get("challenged_by", ()) or ()),
        note=str(raw.get("note", "")),
    )

    if mode.has_mechanism and coverage == 0.0:
        raise FmedaError(
            f"{identifier} names the mechanism {mode.mechanism!r} and claims "
            f"no coverage from it. Either it covers something or it is not a "
            f"mechanism; say `mechanism: none` instead.")
    if not mode.has_mechanism and coverage > 0.0:
        raise FmedaError(
            f"{identifier} claims coverage {coverage} with no mechanism to "
            f"provide it")
    return mode


def load_fmeda(path: Path | str = DEFAULT_FMEDA
               ) -> tuple[tuple[FailureMode, ...], str]:
    """Read the catalog. Returns the modes and the ASIL they are reported against."""
    doc = yaml.safe_load(Path(path).read_text())
    if not isinstance(doc, dict):
        raise FmedaError("the FMEDA catalog is not a mapping")

    target = str(doc.get("target_asil", "D"))
    if target not in ASIL_TARGETS:
        raise FmedaError(
            f"target_asil {target!r} is not one of {sorted(ASIL_TARGETS)}")

    elements = doc.get("elements")
    if not elements:
        raise FmedaError("the FMEDA catalog lists no elements")

    modes: list[FailureMode] = []
    seen: set[str] = set()
    for element in elements:
        name = str(_require(element, "id", "an element"))
        for raw in _require(element, "modes", name):
            modes.append(_parse_mode(raw, name, seen))
    return tuple(modes), target


def metrics(path: Path | str = DEFAULT_FMEDA) -> Metrics:
    modes, target = load_fmeda(path)
    return Metrics(modes=modes, target_asil=target)


def untested_coverage_claims(modes: tuple[FailureMode, ...]
                             ) -> tuple[FailureMode, ...]:
    """Modes claiming coverage that no injected fault challenges.

    This is the only permitted direction of travel between the campaign and the
    FMEDA. The campaign cannot MEASURE diagnostic coverage, but it can falsify a
    claim that a mechanism works, and a DC figure nobody has ever tested is an
    assumption wearing a number.
    """
    return tuple(m for m in modes
                 if m.diagnostic_coverage > 0.0 and not m.challenged_by)
