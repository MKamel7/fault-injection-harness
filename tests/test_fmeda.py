"""The educational FMEDA, and the wall between it and the campaign.

Most of these are arithmetic. Four are not, and they are the reason the file
exists:

  * `test_no_mode_claims_coverage_nothing_has_challenged` is the only permitted
    traffic between the campaign and the FMEDA. Detection coverage cannot
    MEASURE diagnostic coverage, but an untested DC figure is an assumption
    wearing a number, and this fails the build on one.
  * `test_every_challenging_fault_exists_in_the_fault_catalog` stops the bridge
    rotting: a mode may not point at a fault that was renamed or deleted.
  * `test_a_vacuous_metric_is_reported_as_vacuous` guards the shape of gate this
    repository is otherwise careful about. An SPFM of 100% over nothing is the
    best possible number and means nothing was analysed.
  * `test_the_documented_residual_is_the_largest_single_point_contributor` is
    the cross-check worth having. The campaign found the clock-drift gap
    qualitatively, by injecting FLT-T07 and watching it survive. The FMEDA finds
    it again from rates alone. Two independent routes to the same conclusion is
    the point of doing both.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fih.catalog import load_catalog
from fih.fmeda import (
    ASIL_TARGETS,
    Classification,
    FailureMode,
    FmedaError,
    Metrics,
    load_fmeda,
    metrics,
    untested_coverage_claims,
)

CATALOG = Path(__file__).resolve().parent.parent / "catalog" / "fmeda.yaml"


def _mode(**over: object) -> FailureMode:
    base: dict[str, object] = {
        "identifier": "FM-X-01", "element": "X", "title": "t",
        "lambda_fit": 100.0, "safety_related": True, "can_violate_alone": True,
        "mechanism": "a check", "diagnostic_coverage": 0.9,
        "challenged_by": ("FLT-C01",), "note": ""}
    base.update(over)
    return FailureMode(**base)  # type: ignore[arg-type]


# --- classification ----------------------------------------------------------
def test_a_non_safety_related_mode_is_a_safe_fault() -> None:
    assert _mode(safety_related=False).classification is Classification.SAFE


def test_an_uncovered_mode_that_can_violate_alone_is_a_single_point_fault() -> None:
    mode = _mode(mechanism="none", diagnostic_coverage=0.0)
    assert mode.classification is Classification.SINGLE_POINT
    assert mode.undetected_fit == 100.0


def test_a_covered_mode_that_can_violate_alone_leaves_a_residual() -> None:
    mode = _mode(diagnostic_coverage=0.9)
    assert mode.classification is Classification.RESIDUAL
    assert mode.undetected_fit == pytest.approx(10.0)


def test_a_mode_needing_a_second_fault_is_a_multiple_point_fault() -> None:
    mode = _mode(can_violate_alone=False, diagnostic_coverage=0.7)
    assert mode.classification is Classification.MULTIPLE_POINT_LATENT
    assert mode.undetected_fit == pytest.approx(30.0)


def test_a_fully_covered_multiple_point_mode_is_detected() -> None:
    mode = _mode(can_violate_alone=False, diagnostic_coverage=1.0)
    assert mode.classification is Classification.MULTIPLE_POINT_DETECTED
    assert mode.undetected_fit == 0.0


def test_a_mechanism_named_none_is_not_a_mechanism() -> None:
    """The catalog keeps `mechanism` as one readable column, so "none" is data."""
    assert not _mode(mechanism="none", diagnostic_coverage=0.0).has_mechanism
    assert not _mode(mechanism="", diagnostic_coverage=0.0).has_mechanism
    assert _mode().has_mechanism


# --- the metrics -------------------------------------------------------------
def test_spfm_counts_single_point_and_residual_against_the_safety_related_rate() -> None:
    m = Metrics(modes=(
        _mode(identifier="a", mechanism="none", diagnostic_coverage=0.0,
              lambda_fit=10.0, challenged_by=()),
        _mode(identifier="b", lambda_fit=90.0, diagnostic_coverage=0.9),
    ), target_asil="D")
    # 10 SPF + 9 RF against 100 safety related
    assert m.spf_fit == pytest.approx(10.0)
    assert m.rf_fit == pytest.approx(9.0)
    assert m.spfm == pytest.approx(0.81)


def test_a_safe_fault_is_excluded_from_both_denominators() -> None:
    """Otherwise a design improves its metrics by adding harmless parts."""
    dangerous = _mode(identifier="a", lambda_fit=100.0, diagnostic_coverage=0.9)
    harmless = _mode(identifier="b", lambda_fit=900.0, safety_related=False)
    with_safe = Metrics(modes=(dangerous, harmless), target_asil="D")
    without = Metrics(modes=(dangerous,), target_asil="D")
    assert with_safe.spfm == pytest.approx(without.spfm)
    assert with_safe.safe_fit == pytest.approx(900.0)


def test_lfm_excludes_faults_that_already_failed_the_first_metric() -> None:
    """Counting them twice lets a big SPF term post a flattering LFM."""
    m = Metrics(modes=(
        _mode(identifier="a", mechanism="none", diagnostic_coverage=0.0,
              lambda_fit=50.0, challenged_by=()),
        _mode(identifier="b", can_violate_alone=False, lambda_fit=50.0,
              diagnostic_coverage=0.8),
    ), target_asil="D")
    # denominator is 100 - 50 SPF - 0 RF = 50; latent is 10
    assert m.lfm == pytest.approx(0.8)


def test_a_vacuous_metric_is_reported_as_vacuous() -> None:
    """100% over nothing is the best possible number and means nothing ran."""
    m = Metrics(modes=(_mode(safety_related=False),), target_asil="D")
    assert m.spfm == 1.0
    assert m.is_vacuous, "a perfect score over no safety-related rate must say so"


def test_a_real_analysis_is_not_vacuous() -> None:
    assert not metrics().is_vacuous


def test_lfm_is_one_when_nothing_remains_after_the_first_metric() -> None:
    m = Metrics(modes=(_mode(mechanism="none", diagnostic_coverage=0.0,
                             challenged_by=()),), target_asil="D")
    assert m.lfm == 1.0


@pytest.mark.parametrize("asil", sorted(ASIL_TARGETS))
def test_every_asil_target_can_be_compared_against(asil: str) -> None:
    m = Metrics(modes=(_mode(),), target_asil=asil)
    assert isinstance(m.meets_target(), tuple)


def test_the_totals_add_up() -> None:
    m = metrics()
    assert m.total_fit == pytest.approx(m.safety_related_fit + m.safe_fit)


def test_a_modes_detected_and_undetected_rate_account_for_all_of_it() -> None:
    """No rate may be lost or invented between the two halves."""
    for coverage in (0.0, 0.6, 1.0):
        mode = _mode(diagnostic_coverage=coverage)
        assert mode.detected_fit + mode.undetected_fit == pytest.approx(
            mode.lambda_fit)


def test_an_uncovered_mode_detects_nothing() -> None:
    assert _mode(mechanism="none", diagnostic_coverage=0.0,
                 challenged_by=()).detected_fit == 0.0


def test_the_detected_multiple_point_term_is_the_covered_part_of_those_modes() -> None:
    """The label says latent while most of the rate is detected.

    This is the arithmetic the `Classification` docstring warns not to read off
    the labels: a multiple-point mode at DC 0.8 is LABELLED latent and still
    contributes four fifths of its rate to the detected total.
    """
    m = Metrics(modes=(
        _mode(identifier="a", can_violate_alone=False, lambda_fit=100.0,
              diagnostic_coverage=0.8),
        _mode(identifier="b", lambda_fit=50.0, diagnostic_coverage=0.5),
    ), target_asil="D")
    assert m.modes[0].classification is Classification.MULTIPLE_POINT_LATENT
    # only the multiple-point mode contributes; the single-point-capable one
    # is accounted as residual and must not leak into this term.
    assert m.mpf_detected_fit == pytest.approx(80.0)
    assert m.mpf_latent_fit == pytest.approx(20.0)


# --- the catalog parses, and refuses to parse nonsense -----------------------
def test_the_shipped_catalog_loads() -> None:
    modes, target = load_fmeda()
    assert modes and target in ASIL_TARGETS


def _write(tmp_path: Path, doc: object) -> Path:
    path = tmp_path / "fmeda.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


def _doc(**mode_over: object) -> dict[str, object]:
    mode: dict[str, object] = {
        "id": "FM-A-01", "title": "t", "lambda_fit": 10.0,
        "safety_related": True, "can_violate_alone": True,
        "mechanism": "none", "diagnostic_coverage": 0.0}
    mode.update(mode_over)
    return {"target_asil": "D",
            "elements": [{"id": "A", "modes": [mode]}]}


def test_a_coverage_above_one_is_refused(tmp_path: Path) -> None:
    """DC is a proportion of a rate. 90 means somebody typed a percentage."""
    path = _write(tmp_path, _doc(mechanism="a check", diagnostic_coverage=90))
    with pytest.raises(FmedaError, match="not a fraction"):
        load_fmeda(path)


def test_a_negative_failure_rate_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FmedaError, match="negative failure rate"):
        load_fmeda(_write(tmp_path, _doc(lambda_fit=-1.0)))


def test_a_mechanism_that_covers_nothing_is_refused(tmp_path: Path) -> None:
    """Either it covers something or it is not a mechanism."""
    path = _write(tmp_path, _doc(mechanism="a check", diagnostic_coverage=0.0))
    with pytest.raises(FmedaError, match="not a mechanism"):
        load_fmeda(path)


def test_coverage_without_a_mechanism_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, _doc(mechanism="none", diagnostic_coverage=0.5))
    with pytest.raises(FmedaError, match="no mechanism"):
        load_fmeda(path)


def test_a_duplicate_mode_id_is_refused(tmp_path: Path) -> None:
    doc = _doc()
    doc["elements"] = [{"id": "A", "modes": [
        {"id": "FM-A-01", "title": "t", "lambda_fit": 1.0,
         "safety_related": True, "can_violate_alone": True},
        {"id": "FM-A-01", "title": "t", "lambda_fit": 1.0,
         "safety_related": True, "can_violate_alone": True}]}]
    with pytest.raises(FmedaError, match="duplicate failure mode"):
        load_fmeda(_write(tmp_path, doc))


def test_a_missing_required_field_is_refused(tmp_path: Path) -> None:
    doc = _doc()
    del doc["elements"][0]["modes"][0]["lambda_fit"]  # type: ignore[index]
    with pytest.raises(FmedaError, match="lambda_fit"):
        load_fmeda(_write(tmp_path, doc))


def test_an_unknown_asil_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FmedaError, match="target_asil"):
        load_fmeda(_write(tmp_path, {**_doc(), "target_asil": "E"}))


def test_a_catalog_with_no_elements_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FmedaError, match="no elements"):
        load_fmeda(_write(tmp_path, {"target_asil": "D", "elements": []}))


def test_a_catalog_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FmedaError, match="not a mapping"):
        load_fmeda(_write(tmp_path, ["not", "a", "mapping"]))


def test_an_element_without_an_id_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FmedaError, match="missing 'id'"):
        load_fmeda(_write(tmp_path, {"target_asil": "D",
                                     "elements": [{"modes": []}]}))


# --- the wall between the campaign and the FMEDA -----------------------------
def test_no_mode_claims_coverage_nothing_has_challenged() -> None:
    """A diagnostic coverage nobody has tested is an assumption with a number.

    This is the ONLY direction of travel permitted between the two artefacts.
    The campaign cannot measure DC, because it samples a fault list somebody
    wrote while DC integrates over a rate distribution. It can falsify the claim
    that a mechanism works at all, and that is what this enforces.
    """
    untested = untested_coverage_claims(load_fmeda()[0])
    assert not untested, (
        "these modes claim diagnostic coverage that no injected fault "
        f"challenges: {[m.identifier for m in untested]}")


def test_every_challenging_fault_exists_in_the_fault_catalog() -> None:
    """The bridge must not rot when a fault is renamed or removed."""
    known = {f.id for f in load_catalog()}
    dangling = {m.identifier: sorted(set(m.challenged_by) - known)
                for m in load_fmeda()[0]
                if set(m.challenged_by) - known}
    assert not dangling, f"these point at faults that do not exist: {dangling}"


def test_the_gate_would_actually_catch_an_untested_claim() -> None:
    """A gate nobody has watched fail is an assumption.

    Without this, `test_no_mode_claims_coverage_nothing_has_challenged` passes
    on an empty result whether or not the check works at all.
    """
    invented = _mode(identifier="FM-UNTESTED", diagnostic_coverage=0.99,
                     challenged_by=())
    assert untested_coverage_claims((invented,)) == (invented,)


def test_a_mode_with_no_coverage_needs_no_challenging_fault() -> None:
    """An acknowledged gap is not an untested claim.

    FM-CO-03 and FM-WD-01 claim nothing, so there is nothing to falsify. Making
    them name a fault would be paperwork, not evidence.
    """
    honest = _mode(mechanism="none", diagnostic_coverage=0.0, challenged_by=())
    assert untested_coverage_claims((honest,)) == ()


# --- the cross-check worth having --------------------------------------------
def test_the_documented_residual_is_the_largest_single_point_contributor() -> None:
    """Two independent routes to the same gap.

    The campaign found it qualitatively: inject FLT-T07, watch a counter and
    timeout fail to see uniform latency growth, catalogue it residual. The FMEDA
    finds it again from rates alone, with no knowledge of that result. If these
    two ever disagree, one of them is wrong and it matters which.
    """
    modes = load_fmeda()[0]
    single_point = [m for m in modes
                    if m.classification is Classification.SINGLE_POINT]
    assert single_point, "the analysis has no single-point fault at all"
    worst = max(single_point, key=lambda m: m.lambda_fit)
    assert "FLT-T07" in worst.challenged_by, (
        f"the largest single-point contributor is {worst.identifier}, which "
        f"does not trace to the documented clock-drift residual")


def test_the_metrics_are_reported_against_a_named_asil_and_not_claimed() -> None:
    """Meeting a metric is not conformance, and the shipped result says so.

    The shipped rates do NOT meet ASIL D, which is deliberate. A synthetic
    analysis that happened to clear every target would be the least believable
    possible outcome.
    """
    m = metrics()
    assert m.target_asil in ASIL_TARGETS
    assert m.meets_target() == (False, False)
