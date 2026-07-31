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
| That this evidence is independently confirmed | Everything here was produced by one author in one effort, with no second party review. Both standards scale required independence with ASIL or SIL. See section 5. |
| That the DUT is production code | It is a simulation, deliberately, so that faults can be injected at points a real drive would not expose. |

What the report **does** compute is **detection coverage over the injected fault
set**: of the 23 faults in this catalog, how many the design detects, how many
it detects in time, and after how many steps. That is a statement about this catalog and nothing wider. The two
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
| Fault catalog: 23 entries across sensor, actuator, communication and timing, with three outcomes: detected, detected late, residual | `catalog/faults.yaml` | The fault set is data, reviewable by someone who does not read Python |
| Campaign: one fault per run, fresh device, fixed step budget, no randomness | `src/fih/campaign.py` | Reproducibility. The same fault gives the same result, asserted by test |
| Latent plus primary pair campaign, with both members also run alone | `catalog/dual_point.yaml`, `report/dual_point.md` | A latent fault is defined by the difference, so the difference is what is reported |
| Bidirectional traceability, build fails on a gap in either direction | `src/fih/traceability.py`, `report/traceability.md` | Every requirement is verified and every fault answers a requirement |
| Coverage report with latency against each FTTI | `report/coverage.md` | Detection *in time*, not just detection |
| 144 tests, 100% branch coverage, ruff and mypy strict, gated in CI | `.github/workflows/verify.yml` | The harness itself is not the weak link |

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

**A protection channel can only be as good as the thing it measures, and the
answer to that was never a second thermometer. It was a channel of a different
kind.**

This finding has been revised three times. Every revision came from a test
failing, and every one of those tests was written to fail exactly that way.

### The FTTI is derived, not chosen

Under locked rotor current the winding covers its entire permitted rise, 40 C to
140 C, in **7 steps**. That is how long any thermal protection has. Earlier
versions budgeted 20 steps because somebody picked 20, and budgets nobody can
defend are the quiet failure mode of a safety argument, because everything
downstream measures against them.

Budgets differ by condition and each is measured: **7 steps** under locked rotor,
**36 steps** under a sustained twice rated overload, **154 steps** under degraded
cooling at rated load.

### The same fault, against four successive designs

FLT-S01 holds the winding sensor at a safe 40 C with the rotor stalled.

| Design | Trip | Peak winding |
|---|---|---|
| One temperature sensor | **never** | **past 1100 C** |
| Two sensors, with a cross check | step 12 | 207 C, past the limit |
| Two sensors, frame channel latently dead | **never** | **1617 C** |
| Two sensors plus a diverse estimator | **step 7** | **139.6 C** |

Rows two and three are the argument. A second sensor bounded the damage without
preventing it, because the frame is a larger thermal mass and therefore lags, and
a cross check cannot react faster than its slower channel. Then row three: that
bound held only for as long as the second channel was alive, and nothing in the
design noticed when it stopped.

### Why the third channel is diverse and not just additional

The estimator does not measure temperature. It integrates the loss the drive is
commanding and predicts what the winding must be doing, and that single
difference is what closed three separate findings at once:

| Fault | Before | With the estimator |
|---|---|---|
| FLT-S01, winding sensor lying | late, 207 C | step 7, 139.6 C |
| FLT-S05, **both** sensors lying (common cause) | never detected | step 7 |
| DP-01, lying sensor plus latently dead frame | never detected, 1617 C | step 7 |

A third *thermometer* would have closed none of them. Anything that defeats
measurement defeats every channel that measures, which is what "common cause"
means and why two of the same kind is not really two.

### What it costs, which is the half usually left out

The estimator knows only what was **commanded**, so it cannot see the plant.
FLT-A03 degrades real cooling to a third of nominal: the machine runs hot, the
command is unchanged, and the estimator predicts the nominal and **misses it
entirely**. The winding sensor catches it at step 154.

So neither kind of channel is sufficient. The pair is not redundancy, it is
coverage of two disjoint failure classes, and that is what diversity actually
means. An argument for diversity that demonstrates only the flattering half is
not an argument, which is why FLT-A03 is catalogued even though it passes.

### What still defeats the design, found while checking that something did

A campaign in which nothing fails is a campaign that has stopped asking. After
the estimator closed every catalogued pair, the obvious question was whether
anything still gets through, and something does:

> At 0.9 of rated load with cooling degraded to 0.35, the estimator's nominal
> prediction peaks at 120 C and never trips. With the winding sensor **also**
> lying and the frame channel **also** dead, the winding reached **270.7 C
> entirely undetected.**

That is **three** faults, not two, so this harness cannot express it as a
catalogued pair and it is recorded here rather than in the campaign. The shape is
worth stating: it is the estimator's blind spot, the plant, combined with the
sensors' blind spot, themselves. Diversity means the two classes are disjoint. It
does not mean their union is everything.

Closing it needs either a fourth channel or, more realistically, a plausibility
check between the estimate and the measurement that flags a persistent
divergence as a fault in its own right rather than waiting for either to cross a
limit.

### Three outcomes, and a universal reading of satisfaction

The catalog distinguishes **detected**, **detected but outside budget**, and
**residual**, because a design can detect a fault and still fail to protect
against it. Requirement satisfaction is treated as a **universal** claim: a
requirement is satisfied only when *every* fault challenging it is detected
inside its budget. The weaker existential rule was in place first and scored
SR-10 as satisfied while a sensor stuck at ambient let the winding reach 207 C.

Three of eleven requirements remain unmet:

| | Why |
|---|---|
| SR-06 | FLT-C08 undetected: the protocol carries no request identifier |
| SR-09 | FLT-S04 and FLT-A02 undetected: single source blind spots |
| SR-11 | FLT-S07 undetected: a frame sensor reading low contradicts nothing |

SR-10, which drove all of the above, is now met.

## 5. Verification, validation, and independence

The single most useful question to ask about this project, and the one an
assessor opens with. The two words are not synonyms and the honest answer is
different for each.

**Verification** asks whether the thing was built right, against its
specification. **Validation** asks whether it was the right thing, in the real
operating context. This project is **well verified and essentially not
validated**, and no amount of additional testing changes the second half.

### What is genuinely verified

| Property | How it is established |
|---|---|
| The harness does what it claims | 128 tests, 100% statement and branch coverage, gated in CI |
| Every requirement has evidence, every fault answers a requirement | Bidirectional gate that fails the build on a gap in either direction, and is itself tested by being deliberately broken |
| Results are reproducible | No randomness in the campaign, asserted by test: same fault, identical result |
| The published evidence matches the code | CI rebuilds the report and fails if the committed artifacts have gone stale |
| A malformed catalog cannot inflate coverage | Strict loader, unknown fields and unknown hooks are hard errors, tested |

That is a real verification story and it is the part that transfers.

### What is not validated, and cannot be from here

**The device is a model that has never been compared to a device.** Its
parameters are grounded in a Siemens data sheet, which fixes the operating
envelope; that is provenance, not validation. Nothing here has been run against a
real drive, so nothing confirms the model behaves as the motor does.

**The timing dimension is uncalibrated by construction.** The thermal time scale
is deliberately compressed because a real winding thermal constant is minutes
while the mechanical response is milliseconds. So every latency is in simulation
steps, no step maps to a duration, and therefore **no FTTI in this project has
been validated against a real time budget**. The timing results are internally
consistent and externally meaningless.

**The requirements have never been confirmed against an operating context.**
There is no machine, no installation, no operator, no duty cycle. Safety
requirements are only correct relative to a context, and this one has none.

### Independence is zero, and that is structural

The device under test, the hazard analysis, the safety requirements, the fault
catalog, the acceptance criteria and the tests were all produced by **one author
in one effort**. Nothing has been reviewed by a second party.

Both standards treat this as a first order concern rather than a detail. ISO
26262 defines confirmation measures, a confirmation review, a functional safety
audit and a functional safety assessment, and scales the required *independence*
of whoever performs them with ASIL. IEC 61508 handles the same problem through
independent assessment scaled with SIL. The reason is not bureaucratic: the
author of a hazard analysis is the person least able to notice the hazard they
did not think of.

This cannot be closed by writing more tests. It closes only when someone else
reviews it.

### The oracle was adjusted after seeing the results

Worth stating plainly, because it is the methodological weakness a reviewer would
find on their own. On four occasions the expected result was changed *after*
observing the actual one:

- FLT-T04's FTTI was raised from 1 step to 20, once the run showed the safe state
  takes 2 steps to enter.
- FLT-C07's declared safe state was changed to `none`, once the run showed the
  drive is genuinely healthy and only the supervisor's view breaks.
- FLT-S01 and FLT-S03 moved from residual to detected after the device gained a
  second temperature source.
- The headline excursion figure was corrected twice: 422 C to 409.6 C after the
  injection model was found to understate cooling, and again to 1167 C after the
  device's thermal model was validated against its data sheet.
- SR-10 moved from satisfied back to **not satisfied** once requirement
  satisfaction was treated as a universal claim rather than an existential one.
- The thermal FTTI budgets moved from a chosen 20 steps to a derived 7.

Every one of those changes is documented with its reasoning, and each is
defensible on the merits. The pattern is still a weakness. In a controlled
process the expected result is baselined before the run, and a mismatch is
resolved as either a defect or a **reviewed** specification change. Here the same
person observed the mismatch, decided which of the two it was, and applied the
change immediately. That the decisions look right is not evidence that the
process was sound, and with no independent reviewer there is nothing to
distinguish a correct reclassification from a comfortable one.

### Completeness is asserted, not argued

Traceability proves that every requirement has a test and every fault answers a
requirement. It proves nothing about whether the **requirement set itself is
complete**, and that is the gap it is most often mistaken for closing.

There are six hazards. They were not derived by a documented systematic method:
no HAZOP guide word sweep, no FMEA worksheet, no fault tree, no STPA control
structure, and no review. Asked "how do you know you have not missed a hazard",
the honest answer is that we do not.

The same applies to the fault set. Twenty faults were chosen because they were
considered interesting, not sampled from a defined fault space, so **the 16 of 20
figure describes this catalog and estimates nothing**. There is no confidence
interval on it and none could be computed without a sampling argument.

### There is no acceptance criterion

Nothing in this project states what would constitute enough. Real projects carry
quantitative targets, diagnostic coverage, safe failure fraction, SPFM, LFM,
PFH or PFD, and judge the evidence against them. This report **describes** the
result and never declares it sufficient, because there is no validated threshold
to declare it against.

### The tools are not qualified

ISO 26262 requires confidence in software tools to be established, from the
tool's impact and the likelihood of detecting its malfunction. IEC 61508
classifies offline support tools in a similar spirit. Neither has been done here
for pytest, coverage.py, hypothesis, uv, or, most importantly, **for this harness
itself**.

The harness is the case that matters, because its malfunction is
safety-relevant in a specific way: if it silently fails to inject a fault, it
reports coverage that does not exist. Exactly one mitigation is in place, the
loader raises on an unknown injection hook rather than skipping it, and that is
a sensible design choice rather than a qualification argument.

### So what is this evidence good for

It is a credible demonstration of **method**: hazard derived faults, budgets
judged rather than assumed, traceability enforced in both directions, gaps named
instead of hidden, and a finding that forced a change to the device rather than
to the test. That method is what transfers to a real project.

It is not, and is nowhere claimed to be, evidence that a motor controller is
safe.

## 6. Limitations

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

**Redundancy is itself a hazard, and this was found late.** Adding a second
temperature channel halved exposure to a missed detection and doubled exposure to
a spurious shutdown, and nobody assessed that until a review did. The hazard
analysis now carries HAZ-07 and HAZ-08, SG-07 and SR-11, and a change impact
table per release. The underlying process failure, changing the item twice
without revisiting the analysis, is recorded there rather than quietly corrected.

**Single fault at a time, except for catalogued pairs.** The main campaign
injects exactly one fault per run. A separate pair campaign, `report/dual_point.md`,
injects a **latent fault plus a primary one**, which is where a two channel
design actually fails, and it changed the reading of this whole argument.

The result deserves its own statement, because it qualifies everything the
second temperature source is credited with above:

| | Alone | With the frame channel already dead |
|---|---|---|
| FLT-S01, sensor stuck | detected, bounded at 207 C | **undetected, 1617 C** |
| FLT-S08, sensor stuck under overload | detected in time, 117 C | **undetected, 383 C** |

FLT-S08 is the entry that justifies having the second source at all: caught in
time, inside the limit. A latent fault removes exactly that. So the second
temperature source bounds the damage **for as long as it is working**, and
nothing in this design notices when it stops. A safety mechanism nobody checks
is a safety mechanism you do not have.

Two control pairs are catalogued for the opposite reason. DP-03 and DP-04 pair
the same latent fault with primaries the design handles anyway, and both come
out unchanged. Without them the pair campaign would read as "two faults are
worse than one", which is true and says nothing; with them, the claim is the
sharper one, that a latent fault is consequential only in combination with
something that needed the mechanism it removed.

What remains out of scope: combinations beyond two, and any quantity resembling
an ISO 26262 **latent fault metric**, which is computed over a real hardware
architecture with failure rates in FIT. What this measures is whether four
specific catalogued combinations defeat the design.

**The DUT's parameters are grounded**The DUT's parameters are grounded, its dynamics are not.** Speeds, currents,
torques and the temperature limit come from a Siemens SIMOTICS S-1FK2 datasheet,
archived in `docs/datasheets/` and labelled `[DS]` at each constant. The thermal
and speed *response* constants are fitted or illustrative and are labelled
`[DERIVED]` or `[ILLUSTRATIVE]`. That split is stated in P1's
`docs/REFERENCES.md` rather than blurred, because a model that looks grounded
everywhere is more misleading than one that says where it is not.

**The harness verifies the design, not the implementation.** The DUT is a Python
simulation. Nothing here says anything about a compiler, a scheduler, memory
protection, or any of the things that dominate real embedded failure.

## 7. What would make this stronger

In the order a real project would do them:

0. **An independent review**, by someone who did not write any of it, of the
   hazard analysis first and the fault catalog second. It is listed at zero
   because it is the only item here that addresses a structural weakness rather
   than a scope one, it is the cheapest thing on the list, and until it happens
   every other entry is an improvement to evidence nobody has checked.
1. ~~A second temperature source in the DUT~~ **done in DUT v1.5.** SR-10 moved
   from unsatisfied to satisfied for independent sensor failures, and FLT-S05
   was added to name the common cause case that remains. It was, as predicted,
   the smallest change with the largest effect on the argument.
2. **Diverse** channels rather than merely redundant ones, which is what FLT-S05
   actually needs: a different sensing principle, supply and conversion path,
   plus an FMEDA to show the common cause fraction is acceptable. Note this is
   the first item on this list that cannot be done in software.
3. ~~Multi point fault injection, starting with a latent diagnostic failure plus
   a primary fault~~ **done.** It found that a dead frame channel turns FLT-S01
   from a bounded 207 C excursion into an undetected 1617 C runaway, and defeats
   FLT-S08, the very case the redundancy was credited with handling.
4. **A diagnostic on the safety mechanism itself**, which is what that finding
   asks for. Not a better mechanism: a periodic check that the frame channel
   still responds, since a frame reading that never moves while the winding
   rises is stuck and is detectable without a third sensor. This is the item
   that would close DP-01 and DP-02.
5. An FMEDA over a real bill of materials with SN 29500 rates, which is the only
   route to a defensible diagnostic coverage figure. The pair campaign now
   supplies the latent fault observations such an analysis would need.
6. Running the campaign against a real drive over the actual fieldbus, at which
   point the transport faults stop being decorators and become a broken cable.
