# Fault injection harness

Hazard derived fault injection against an embedded motor controller, producing a
requirement to test traceability matrix and a fault coverage report with
detection latency measured against a fault tolerant time interval budget.

Communication faults are additionally run through a CRC, counter and timeout
protection layer configured as **both AUTOSAR E2E and PROFIsafe**, and the two
are compared on the same fault set.

```
24 faults   20 detected in time   4 residual   4 latent-plus-primary pairs
176 tests   100% branch coverage   ruff + mypy strict   all gated in CI
3 of 11 safety requirements currently NOT met, each named with why
```

## What this is for

There is a version of "fault injection" that means generating training data for a
classifier, and a version that means generating evidence. This is the second one.
The deliverable is not an accuracy figure, it is a traceability matrix, a
coverage report, and a written argument about what the design does not do.

Three properties are worth more than the fault count:

**The faults are derived, not listed.** Every entry in `catalog/faults.yaml`
traces to a safety requirement in `docs/HAZARD_ANALYSIS.md`, which traces to a
safety goal, which traces to a hazard. A fault that challenges nothing fails the
build.

**Detection alone is not a pass.** Each fault carries an FTTI budget and the
report judges latency against it. Noticing a fault after the hazard has occurred
is not a safety mechanism.

**The gaps are named.** Four of the twenty faults are residual: the design cannot
detect them. Each one records what design change would be needed, and one of them
exists specifically to stop a fix being oversold. A campaign reporting complete
detection would not be credible.

## The headline finding

**The obvious fix for a sensor you cannot trust is a second sensor. It was the
wrong fix**, and the campaign proved it three separate ways before a channel of a
different *kind* closed all three.

The same fault, a winding sensor stuck at a safe value with the rotor stalled,
against four successive designs:

| Design | Trip | Peak winding |
|---|---|---|
| One temperature sensor | **never** | ran away |
| Two sensors, with a cross check | late | past the limit |
| Two sensors, frame channel latently dead | **never** | ran away |
| Two sensors plus an accumulated overload channel | **step 2** | **51.6 C** |

Budgets are **derived and differ by condition**: 22 steps for a locked rotor,
136 for a sustained 2x overload, 1041 for cooling degraded to a third of nominal.
A fault judged on a budget looser than its requirement is the easiest way to
inflate a coverage report, and the traceability gate refuses it.

**Why a different kind, and not a third sensor.** The third channel does not
measure temperature; it integrates current above rated. Anything that defeats
measurement defeats every channel that measures, so a third thermometer would
have closed none of these:

| Fault | Two sensors | With the overload channel |
|---|---|---|
| Winding sensor lying | late, past the limit | step 2 |
| **Both** sensors lying (common cause) | never detected | step 2 |
| Lying sensor plus latently dead frame | never detected | step 2 |

**The sharpest result is why the first attempt failed.** A predicted-temperature
channel looked right and passed every test, and was only passing because its
model shared the plant's coefficients. A class 155 machine at a 100 K rated rise
runs at **87% of its absolute insulation limit**, so solving the bounding
constraints gave a tolerable prediction error of **0.00%**. An accumulator sits
at *zero* during rated duty instead, and tolerates about +7% over-reading and
46 to 75% under-reading. Real drives protect this way for exactly this reason.

**What it costs.** The overload channel knows only what was commanded, so a
degraded plant leaves it at exactly zero and only a measurement notices. Neither
kind is sufficient; the pair covers two disjoint failure classes. That is what
diversity means, and it is why the fault the channel *cannot* see is catalogued
even though it passes.

**And something still gets through.** Combining both blind spots, a mild cooling
degradation plus a lying winding sensor plus a dead frame channel, still drives
the winding past its limit undetected. That is three faults, so the harness cannot
express it as a pair, and it is written into the safety argument rather than left
to be found.

## Three outcomes, not two

A design can detect a fault and still fail to protect against it, so the catalog
distinguishes **detected**, **detected but outside budget**, and **residual**.
Collapsing the first two is how a coverage report ends up describing a drive that
burns out.

Requirement satisfaction is a **universal** claim: satisfied only when *every*
fault challenging it is detected inside its budget. The weaker existential rule
was in place first and scored SR-10 as satisfied while a sensor stuck at ambient
let the winding reach 207 C.

## The cross domain comparison

`src/fih/protection.py` implements one CRC plus counter plus timeout mechanism
and configures it two ways, because AUTOSAR E2E and PROFIsafe are the same idea
in different vocabularies. Against corruption, repetition, loss and delay they
behave identically, and both refuse the frame **nine steps earlier than the bare
protocol's watchdog managed**, before the payload ever reaches the device.

They disagree on exactly one fault, and the disagreement is real rather than an
implementation artifact:

| | E2E | PROFIsafe |
|---|---|---|
| FLT-C08, a valid reply about the wrong quantity | detected, `WRONG_ID` | **not detected** |

An E2E Data ID identifies a *data element*, so a reply carrying a temperature has
a different Data ID from one carrying a speed. A PROFIsafe F_Destination_Address
identifies a *device*, so every message on the link carries the same one and the
reply passes every check. Under PROFIsafe, binding a response to its request is
an application layer job.

`docs/STANDARDS_MAPPING.md` carries one requirement, SR-05, through both stacks
side by side.

## Layout

```
docs/HAZARD_ANALYSIS.md      8 hazards, 7 safety goals, 11 safety requirements with FTTI budgets
docs/SAFETY_ARGUMENT.md      claim, evidence, and at length what is NOT claimed
docs/STANDARDS_MAPPING.md    one requirement through the automotive and industrial stacks
catalog/faults.yaml          the 24 faults, as reviewable data rather than code
src/fih/campaign.py          one fault per run, deterministic, records what the device did
src/fih/report.py            judges those runs against the budgets
src/fih/traceability.py      bidirectional gate; fails the build on a gap either way
src/fih/protection.py        the shared mechanism, two profiles
report/                      generated evidence, rebuilt and checked on every push
```

## Running it

```sh
uv run --group dev pytest                       # the catalog driven suite
uv run --group dev python scripts/build_report.py   # regenerate report/
```

The device under test is **imported, not copied**: it is
[`embedded-test-automation`](https://github.com/MKamel7/embedded-test-automation)
pinned to tag `v3.0`. Both halves of that matter. Copying would fork the thing
being verified, so the evidence would no longer refer to the original. Tracking
`main` would let the device's thresholds move underneath a published coverage
report, and that has happened at every release: the overheat trip moved, a second
temperature channel appeared, the thermal model was validated and corrected, and
a third channel replaced the second. Each arrived as a deliberate repin with the
evidence regenerated, rather than as a silent shift under a published report.

## What is not claimed

No conformance, no certification, no ASIL and no SIL. ISO 26262, IEC 61508,
IEC 61800-5-2, IEC 61784-3 and Automotive SPICE are paid standards and
conformance is an assessor's judgement. This work is *structured per* and *mapped
to* their concepts.

The figure computed here is **detection coverage over the injected fault set**,
which is a statement about this catalog. It is **not** diagnostic coverage in the
ISO 26262 sense: that requires an FMEDA with component failure rates in FIT, and
there are none here. Latencies are in **simulation steps**, never seconds,
because the device's thermal time scale is deliberately compressed.

**Nothing here is independently reviewed.** The device, the hazard analysis, the
requirements, the fault catalog, the acceptance criteria and the tests all come
from one author in one effort. Both ISO 26262 and IEC 61508 treat independence of
assessment as a first order concern, scaled with ASIL or SIL, and for good
reason: the author of a hazard analysis is the person least able to notice the
hazard they did not think of. That gap does not close by writing more tests.

The work is **well verified and essentially not validated**. Verified: the
harness does what it claims, reproducibly, with the evidence regenerated and
staleness-checked on every push. Not validated: the device is a model that has
never been compared to a real drive, and its thermal time scale is deliberately
compressed, so every latency is internally consistent and externally meaningless.

`docs/SAFETY_ARGUMENT.md` sections 5 and 6 give the full account, including the
four occasions where an expected result was revised after observing the actual
one.
