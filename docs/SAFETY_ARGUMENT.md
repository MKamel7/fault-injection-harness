# Safety argument

Claim, evidence, and limitations for the fault injection campaign against the
simulated motor controller.

This is written the way a safety case is written: the claim first, then what
actually supports it, then, at length, what it does not. The last section is the
important one. An argument that only lists its strengths is marketing.

## 1. What this is, and what it is not

**It is** a fault injection campaign against a simulated servo drive controller,
where the faults are derived from a hazard analysis rather than chosen because
they were easy to inject, and where the result is judged against a time budget
rather than a boolean.

**It is not** a compliance artifact. Nothing here is assessed, certified, or
claimed to conform to ISO 26262, IEC 61508, IEC 61800-5-2, IEC 61784-3 or
Automotive SPICE. Those are paid standards and conformance is a judgement made by
people, not by a test suite. The work is *structured per* their concepts and
*mapped to* their vocabulary, and that is the whole of the claim.

Specifically **not** claimed:

| Not claimed | Why not, and what it would take |
|---|---|
| An ASIL | ASIL is assigned by a vehicle level HARA over severity, exposure and controllability. A bench simulation has no vehicle context, no driver, no operational situation. There is nothing to classify. |
| Diagnostic coverage, SPFM, LFM | Those are FMEDA quantities and need component failure rates in FIT, from a source such as SN 29500 or IEC 62380, applied to a real bill of materials. This device has no components, so no rate exists to integrate. |
| Conformance to any standard | Requires an assessor, an assessment, and the standard text. |
| That the DUT is production code | It is a simulation, deliberately, so that faults can be injected at points a real drive would not expose. |

What the report **does** compute is **detection coverage over the injected fault
set**: of the 19 faults in this catalog, how many the design detects, and after
how many steps. That is a statement about this catalog and nothing wider. The two
get conflated constantly and the distinction is the first thing an assessor
checks.

## 2. The claim

> For the fault set catalogued in `catalog/faults.yaml`, the device under test
> detects every fault its design is capable of detecting, reaches its declared
> safe state within the fault tolerant time interval budgeted for that fault, and
> the faults it cannot detect are named, explained, and traced to the specific
> design change that would be required to close them.

Note the shape of that sentence. It is bounded by the catalog, it is conditional
on the design, and it commits to naming the gaps. A claim that could not be
falsified by running the campaign would not be worth making.

## 3. The evidence

| Evidence | Where | What it supports |
|---|---|---|
| Hazard analysis: 6 hazards, 6 safety goals, 10 safety requirements, each with an FTTI budget | `docs/HAZARD_ANALYSIS.md` | The faults are derived, not invented |
| Fault catalog: 19 entries across sensor, actuator, communication and timing | `catalog/faults.yaml` | The fault set is data, reviewable by someone who does not read Python |
| Campaign: one fault per run, fresh device, fixed step budget, no randomness | `src/fih/campaign.py` | Reproducibility. The same fault gives the same result, asserted by test |
| Bidirectional traceability, build fails on a gap in either direction | `src/fih/traceability.py`, `report/traceability.md` | Every requirement is verified and every fault answers a requirement |
| Coverage report with latency against each FTTI | `report/coverage.md` | Detection *in time*, not just detection |
| 86 tests, 100% branch coverage, ruff and mypy strict, gated in CI | `.github/workflows/verify.yml` | The harness itself is not the weak link |

### Why the traceability gate runs in both directions

Each direction catches a different mistake, and only one of them is obvious.

A **requirement with no fault** is a hole in the argument: something was
specified and never verified, and nothing would have said so.

A **fault with no requirement** is the quiet one. It runs, it passes, it appears
in the coverage report, and it answers nothing that was ever asked for. A single
typo in a requirement id is enough to cause it, and the effect is to inflate the
coverage figure. So a fault referencing `SR-0l` instead of `SR-01` fails the
build rather than counting as coverage. `tests/test_catalog_and_traceability.py`
verifies the gate by deliberately breaking it in both directions, because a gate
that has never been seen to fail is an assumption, not a control.

## 4. The headline finding

**SR-10 is not satisfied by this design, and the campaign proves it rather than
suspecting it.**

SR-10 requires that overtemperature protection not be defeated by a sensor
reporting implausible values. FLT-S01 injects a temperature sensor stuck at a
safe 40 C while the drive runs into a stall.

Measured result: **the winding reached 422 C**, far past the 140 C limit implied
by the thermal class 155 (F) insulation of the reference motor, **while the
sensor reported 40 C and the drive kept running**. Nothing tripped. Nothing
could have: the item has a single temperature source, and the protection trips
on the reported value.

FLT-S03 is the same root cause and worse, because it is harder to notice. A
sensor drifting 60 C low produces readings that are individually plausible; the
winding passed 120 C while the sensor showed 60 C. There is no reading you could
point at and call wrong.

This is the defence in depth argument in one measurement. A protection mechanism
is only as good as the independence of what it measures, and a single channel
device has no independence to offer. Closing it needs a second temperature
source, or a plausibility model of temperature rise against commanded torque and
elapsed time. Both are design changes, not test improvements, which is exactly
why the finding belongs in the safety argument rather than in a bug tracker.

The same structural argument covers the other residual faults: FLT-S04 (speed
feedback stuck at zero) and FLT-A02 (torque silently lost) are both single source
blind spots, and FLT-C08 (a well formed reply to the wrong command) cannot be
detected by a protocol that carries no request identifier.

FLT-S01 is pinned by an explicit test, `test_the_lying_sensor_actually_overheats_
the_winding`, so that a future change to the DUT which closes it **fails the
build**. That sounds backwards. It is deliberate: if the design improves, this
argument is out of date and must be rewritten, and a safety case that silently
absorbs good news would also silently absorb bad news.

## 5. Limitations

Ordered by how much they should worry a reader.

**The device is simulated, and its time scale is compressed.** The thermal model
advances fast enough to be testable in milliseconds of wall clock. Real winding
thermal time constants are minutes. Every latency in this report is therefore in
**simulation steps** and does not convert to seconds. Reporting them in
milliseconds would invent precision that does not exist.

**Overspeed reaction is out of scope, and for a defensible reason.** The FTTI for
an overspeed hazard on the reference motor works out at 0.46, 0.92 and 1.83 ms
for a 5, 10 and 20 percent overshoot. The command layer modelled here has a
1 ms resolution, so the entire budget is at or below one step. That is the
correct answer rather than a gap: overspeed reaction belongs in the drive's fast
current loop or in dedicated safety silicon, not in a supervisory command layer,
and a harness claiming to verify it at this layer would be verifying the wrong
thing. `docs/HAZARD_ANALYSIS.md` derives the numbers.

**Detection coverage is over the injected set only.** Faults nobody thought of
are not in the denominator. The catalog is a considered fault set, not an
exhaustive one, and no argument here says otherwise.

**Single fault at a time.** Each run injects exactly one fault. Multi point
faults, and in particular a latent fault plus a second fault, are not covered.
This is a real gap: ISO 26262 latent fault metrics exist precisely because that
combination is where single channel designs fail.

**The DUT's parameters are grounded, its dynamics are not.** Speeds, currents,
torques and the temperature limit come from a Siemens SIMOTICS S-1FK2 datasheet,
archived in `docs/datasheets/` and labelled `[DS]` at each constant. The thermal
and speed *response* constants are fitted or illustrative and are labelled
`[DERIVED]` or `[ILLUSTRATIVE]`. That split is stated in P1's
`docs/REFERENCES.md` rather than blurred, because a model that looks grounded
everywhere is more misleading than one that says where it is not.

**The harness verifies the design, not the implementation.** The DUT is a Python
simulation. Nothing here says anything about a compiler, a scheduler, memory
protection, or any of the things that dominate real embedded failure.

## 6. What would make this stronger

In the order a real project would do them:

1. A second temperature source in the DUT, then re-run FLT-S01 and FLT-S03 and
   watch SR-10 move from unsatisfied to satisfied. That is the smallest change
   with the largest effect on the argument.
2. Multi point fault injection, starting with a latent diagnostic failure plus a
   primary fault.
3. An FMEDA over a real bill of materials with SN 29500 rates, which is the only
   route to a defensible diagnostic coverage figure.
4. Running the campaign against a real drive over the actual fieldbus, at which
   point the transport faults stop being decorators and become a broken cable.
