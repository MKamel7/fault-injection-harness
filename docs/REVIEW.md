# Review record

What has been reviewed, by whom, and what was found. Including where the answer
was "nothing", because a list of findings without a list of what survived is not
calibrated.

## What this record is careful not to claim

None of the reviews below is a **qualified functional safety assessment**. That
is a judgement made by an assessor against a standard, and no such person has
looked at this. What these are is **independent review**: people and tools that
did not write the work, given it cold, asked to find what is wrong with it.

The distinction matters and is easy to blur, so it is stated once here and the
entries below use the precise wording.

---

## R-03: Independent peer review

**Date:** 31 July 2026
**Reviewer:** an independent reviewer at TU Munich, working from
`docs/REVIEW_BRIEF.md` and a self contained snapshot of both repositories, and
using a language model for a first pass over the pack.
**Independence:** different person, different institution, no involvement in the
work at any point.
**Scope:** the whole pack, with emphasis on the physics and the safety argument.
**Snapshot:** `fault-injection-harness` at `428308a`,
`embedded-test-automation` at `1796f6a`.

Seven findings. Four high, all reproduced against the code before being acted
on, all now closed.

| | Finding | Outcome |
|---|---|---|
| 1 | `reset()` cleared winding temperature, frame temperature, peak history, cooling degradation and load, while its own docstring said thermal state is not cleared and a release note repeated the claim | Fixed in DUT v3.1. Clears controller state only, with a test that loops RESET twenty times and fails if the winding returns to ambient |
| 2 | The overload channel had **no current sensor**. It read exact plant current while both temperature channels could be made to lie | Fixed in DUT v3.1. Real measurement seam added, and the consequence catalogued as DP-05 |
| 3 | Maximum current was treated as locked rotor current. The data sheet gives maximum, rated and static current and **no** locked rotor figure | Fixed. Stall current is machine state, and FLT-A04 blocks the rotor at the data sheet's static current |
| 4 | The hazard analysis still carried a free running equilibrium and a stall latency from a thermal model retired two rebuilds earlier | Fixed. Prose defers to generated reports, and `check_docs.py` fails on retired values outside a passage marked historical |
| 5 | The two node topology was asserted as proven rather than chosen, argued from natural cooling and IP64 | Fixed. Called a chosen lumped approximation, with the flange, end shield, bearing and shaft paths named |
| 6 | The overspeed interval divides maximum torque by **rotor inertia alone**, but the item is a machine axis carrying a driven mechanism | Fixed. Relabelled a bare rotor lower bound, not the item's FTTI |
| 7 | The `FAULT` state zeroes speed instantly, which is an ideal brake rather than the coast down STO actually describes | Documented. The model verifies STO **state logic** and nothing about motion after torque removal. Coast down dynamics remain unmodelled |

### Why finding 2 was the important one

It did not just break a claim, it explained why the claim had looked so good.

The temperature sensors had seams so they could be made to lie. The overload
channel read plant truth directly through a private method, and the same value
drove both the physical heating and the protection. So the design's headline
result, that a diverse third channel closed three separate findings, was partly
**self-fulfilling**: two channels could fail and the third could not.

The reviewer found it by reading two documents against each other and noticing
that `report/coverage.md` says the item has no current sensing while
`docs/SAFETY_ARGUMENT.md` describes the third channel as operating on measured
current. Nothing internal had caught that contradiction.

Giving the channel a real seam immediately made **DP-05** expressible, and it
violates: a stuck current sensor is caught alone, both temperature sensors lying
is caught alone, and together they are an undetected runaway. Diversity closed
common cause between the two temperature sensors. It does not survive a common
cause spanning all three.

### What the reviewer checked and found sound

- Every constant taken directly from the article data sheet is transcribed
  correctly, including the 3.5 kg·cm² to 3.5e-4 kg·m² conversion.
- The project is unusually explicit about its limitations: no hardware
  validation, uncalibrated thermal time, zero independence, incomplete hazard
  and fault sets, no acceptance criteria, unqualified tools.
- The generated coverage report distinguishes detected faults from documented
  residuals and reports unmet safety requirements openly rather than hiding
  them.

### Left open by this review

The reviewer flagged one question this project cannot answer from the material
it has: **whether rated continuous duty actually reaches the permitted 100 K
rise**, or whether that figure is only a permitted maximum. The whole
steady state thermal gain is calibrated on the assumption that it is reached. If
it is a limit rather than an operating point, the 15 K margin, the overload
budgets and the channel tolerance figures are properties of the calibration
rather than of the motor. Answering it needs the Siemens series documentation,
which is not archived here.

---

## R-02: Adversarial self review

**Date:** 31 July 2026
**Reviewer:** the author, deliberately adversarially.
**Independence:** none. Recorded for completeness, not as evidence.

Eight findings, all closed. The two that mattered were that adding a second
temperature sensor created a spurious trip hazard nobody had assessed, and that
the hazard analysis had not been revisited across two device changes. Both are
in the change impact table in `docs/HAZARD_ANALYSIS.md`.

This review is listed because it happened, and because the contrast is
instructive: it found real defects and it missed everything in R-03. An author
reviewing their own work shares its blind spots by construction.

---

## R-01: Cold context model reviews

**Date:** 31 July 2026
**Reviewers:** two language model agents, given the repositories with no context
from the author, one on the physics and one on the harness logic.
**Independence:** partial. No shared context, but the same class of tool as the
author used to build the work.
**Scope:** one on the device model and its validation claims, one on the harness
logic and its claims.

Thirteen findings between them. The most serious were that rated duty sat
3.4e-13 K from the trip threshold, that a validation criterion had become a
tautology, that energy was not conserved between the two thermal nodes, and that
four requirements read green on evidence that would not have changed had the
device violated them. All closed in DUT v3.0 and the corresponding harness
release.

---

## Still not done

**A qualified assessment.** Everything above is review by people or tools that
did not write the work. None of it is an assessor's judgement against a standard,
and the safety argument's improvement list keeps that at position zero until it
happens.
