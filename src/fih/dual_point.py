"""Latent fault plus primary fault, which is where redundant designs actually fail.

The single fault campaign answers "what does this design detect". It cannot
answer the question that matters most to a design with two channels: **what
happens when one of them has been quietly dead for a month.**

ISO 26262 draws the distinction this module exists to exercise. A LATENT fault
violates no safety goal by itself and is not detected, so nothing announces it;
what it does is silently remove a safety mechanism that only matters later. The
latent fault metric exists because that combination, not the single fault, is
where a two channel item gets hurt. The safety argument named this as a scope
limit, and it is now partly closed.

Deliberately kept to PAIRS rather than arbitrary combinations. Two faults can be
attributed: run the pair, run each member alone, and the difference is caused by
the combination. Beyond two the attribution goes, and attribution is the entire
output of this project.

The control cases matter as much as the failures. DP-03 pairs the same latent
fault with a primary the design handles anyway, and it must come out unchanged,
because a latent fault that changed every outcome would not be latent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dut_sim.motor_controller import OVERHEAT_LIMIT_C

from fih.campaign import RunResult, run
from fih.catalog import CatalogError, Fault

DEFAULT_PAIRS = Path(__file__).resolve().parents[2] / "catalog" / "dual_point.yaml"

#: `violated` means the combination let the winding pass its limit with the
#: drive still running. `handled` means the design coped, and is used for the
#: control cases.
PAIR_EXPECTATIONS = {"violated", "handled"}

#: What KIND of two fault combination this is. The distinction is real and
#: ISO 26262 keeps it: a latent fault is undetected alone and silently removes a
#: mechanism, whereas a dual point fault is two faults each of which the design
#: detects perfectly well on its own, which together defeat it. The second is not
#: a weaker version of the first, and the campaign would misdescribe it if the
#: schema only knew about one.
PAIR_KINDS = {"latent_plus_primary", "dual_point"}

_REQUIRED = {"id", "title", "latent", "primary", "challenges", "expectation",
             "rationale", "kind"}


@dataclass(frozen=True)
class Pair:
    """One latent fault combined with one primary fault."""

    id: str
    title: str
    latent: str
    primary: str
    challenges: tuple[str, ...]
    expectation: str
    rationale: str
    kind: str = "latent_plus_primary"

    @property
    def is_latent_kind(self) -> bool:
        return self.kind == "latent_plus_primary"

    @property
    def expects_violation(self) -> bool:
        return self.expectation == "violated"


@dataclass(frozen=True)
class PairResult:
    """What the combination did, and what each member did alone.

    All three are recorded together because a latent fault is DEFINED by the
    difference. Reporting only the combined run would leave a reader unable to
    tell a latent fault from a primary one that happens to be bad.
    """

    pair_id: str
    combined: RunResult
    latent_alone: RunResult
    primary_alone: RunResult

    @property
    def safety_goal_violated(self) -> bool:
        """Winding past its limit with the drive still running."""
        return (self.combined.true_temperature_c >= OVERHEAT_LIMIT_C
                and not self.combined.reached_safe_state)

    @property
    def latent_is_silent_alone(self) -> bool:
        """The defining property: no effect on its own.

        If the latent member is detected or hazardous by itself then it is not
        latent, it is just a fault, and pairing it proves nothing about latency.
        """
        return (not self.latent_alone.detected
                and self.latent_alone.true_temperature_c < OVERHEAT_LIMIT_C)

    @property
    def caused_by_the_combination(self) -> bool:
        """Did pairing them change the outcome at all?"""
        return self.combined.detected != self.primary_alone.detected


def load_pairs(path: Path | str = DEFAULT_PAIRS,
               known: dict[str, Fault] | None = None) -> tuple[Pair, ...]:
    """Parse and validate the pair catalog, or raise CatalogError."""
    doc = yaml.safe_load(Path(path).read_text())
    if not isinstance(doc, dict) or "pairs" not in doc:
        raise CatalogError(f"{path}: expected a mapping with a 'pairs' list")

    pairs: list[Pair] = []
    seen: set[str] = set()
    for raw in doc["pairs"]:
        pair = _parse(raw, seen, known)
        seen.add(pair.id)
        pairs.append(pair)
    if not pairs:
        raise CatalogError(f"{path}: pair catalog is empty")
    return tuple(pairs)


def _parse(raw: dict[str, Any], seen: set[str],
           known: dict[str, Fault] | None) -> Pair:
    pair_id = str(raw.get("id", "<no id>"))
    unknown = set(raw) - _REQUIRED
    if unknown:
        raise CatalogError(f"{pair_id}: unknown field(s) {sorted(unknown)}")
    missing = _REQUIRED - set(raw)
    if missing:
        raise CatalogError(f"{pair_id}: missing required field(s) {sorted(missing)}")
    if pair_id in seen:
        raise CatalogError(f"{pair_id}: duplicate id")
    if raw["expectation"] not in PAIR_EXPECTATIONS:
        raise CatalogError(
            f"{pair_id}: expectation {raw['expectation']!r} not in "
            f"{sorted(PAIR_EXPECTATIONS)}")
    if raw["kind"] not in PAIR_KINDS:
        raise CatalogError(
            f"{pair_id}: kind {raw['kind']!r} not in {sorted(PAIR_KINDS)}")
    if raw["latent"] == raw["primary"]:
        raise CatalogError(f"{pair_id}: a fault cannot be paired with itself")

    if known is not None:
        for role in ("latent", "primary"):
            if raw[role] not in known:
                raise CatalogError(
                    f"{pair_id}: {role} {raw[role]!r} is not in the fault catalog. "
                    f"A pair referring to a fault that does not exist would run "
                    f"nothing and report a result.")

    return Pair(
        id=pair_id,
        title=str(raw["title"]),
        latent=str(raw["latent"]),
        primary=str(raw["primary"]),
        challenges=tuple(str(c) for c in raw["challenges"]),
        expectation=str(raw["expectation"]),
        rationale=" ".join(str(raw["rationale"]).split()),
        kind=str(raw["kind"]),
    )


def run_pair(pair: Pair, by_id: dict[str, Fault]) -> PairResult:
    """Run the combination and both members alone, so the difference is visible."""
    latent, primary = by_id[pair.latent], by_id[pair.primary]
    return PairResult(
        pair_id=pair.id,
        combined=run(primary, latent=latent),
        latent_alone=run(latent),
        primary_alone=run(primary),
    )


def run_all_pairs(pairs: tuple[Pair, ...],
                  by_id: dict[str, Fault]) -> dict[str, PairResult]:
    return {pair.id: run_pair(pair, by_id) for pair in pairs}


def verdict(pair: Pair, result: PairResult) -> tuple[bool, str]:
    """Did the pair behave as the catalog records? Returns (ok, explanation)."""
    if pair.is_latent_kind and not result.latent_is_silent_alone:
        return False, (f"{pair.latent} is not latent: it is detected or hazardous "
                       f"on its own, so this pair proves nothing about latency")
    if not pair.is_latent_kind and result.latent_is_silent_alone:
        return False, (f"{pair.latent} is undetected on its own, so this is a "
                       f"latent fault rather than the dual point fault recorded")

    if pair.expects_violation:
        if not result.safety_goal_violated:
            return False, ("expected the combination to violate the safety goal "
                           "and it did not; the design improved and this entry "
                           "is stale")
        return True, (f"safety goal violated, winding reached "
                      f"{result.combined.true_temperature_c:.0f} C undetected")

    if result.safety_goal_violated:
        return False, ("the combination violated the safety goal but is recorded "
                       "as handled")
    return True, "handled, as documented"
