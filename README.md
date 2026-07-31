# Fault injection harness

Hazard derived fault injection against an embedded motor controller, producing a
requirement to test traceability matrix and a fault coverage report with
detection latency measured against a fault tolerant time interval budget.

Communication faults are additionally run through a CRC, counter and timeout
protection layer configured as **both AUTOSAR E2E and PROFIsafe**, and the two
are compared on the same fault set.

```
23 faults   17 detected in time   1 detected too late   5 residual
144 tests   100% branch coverage   ruff + mypy strict   all gated in CI
4 of 11 safety requirements currently NOT met, each named with why
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

**Detection is not protection**, and this project's central result is a case
where the difference decides whether a motor survives.

A single temperature source cannot protect against its own sensor. Adding a
second one bounds the damage and still does not prevent it, because the second
channel is physically too slow.

| FLT-S01, winding sensor stuck at a safe value | Trip | Peak winding |
|---|---|---|
| One temperature source | **never** | **1167 C** and climbing |
| Two, with a cross check | step 12 | **207 C** |
| Budget | by step 7 | 140 C |

The budget is **derived, not chosen**: under locked rotor current the winding
covers its entire permitted rise, 40 C to 140 C, in 7 steps. That is all the time
any thermal protection has.

The second source converts an unbounded excursion into a bounded one, which is a
large improvement and is not protection. The cause is structural: the frame is a
larger thermal mass, so it necessarily lags, and a cross check cannot react
faster than its slower channel responds. Closing it needs a different **kind** of
channel, a model based estimator that integrates commanded current and has no
thermal mass and therefore no lag, which is exactly why real drives use one.

**Where the second source does work.** Two cases, and the second only became
visible once the catalog stopped testing thermal faults exclusively at the
extreme. A sensor drifting 60 C low is caught at step 1 by the disagreement
alone, because neither temperature limit is ever reached. And under a **sustained
overload rather than a locked rotor**, twice rated torque with the shaft still
turning, the same lie as above is caught at step 27 with the winding at 117 C,
inside both the 36 step budget and the 140 C limit.

So the redundancy is **adequate for the likelier hazard and inadequate for the
fastest one**, which is a far more useful statement than the one a stall-only
catalog produced.

**And the redundancy is itself a new failure source.** A frame sensor reading a
plausible 120 C used to stop a healthy motor at step 1, reported as an
overtemperature the motor was not having, and did the same at idle on a machine
that had never moved. Two channels can detect a contradiction and cannot
attribute it, so the diagnostic now says `SENSOR_DISAGREEMENT`, and a
disagreement with no torque commanded annunciates instead of tripping. A frame
sensor reading *low* remains undetectable and is catalogued as such: it is a
latent fault, harmless alone, and it removes a backstop that only matters once
the primary channel has failed too.

**And it is deliberately not oversold.** FLT-S05 injects the same lie into *both*
channels and is residual: the winding runs past 1500 C undetected, exactly as the
single channel design did. Redundancy defeats independent failures and does
nothing about common cause.

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
docs/HAZARD_ANALYSIS.md      hazards, safety goals, 10 safety requirements with FTTI budgets
docs/SAFETY_ARGUMENT.md      claim, evidence, and at length what is NOT claimed
docs/STANDARDS_MAPPING.md    one requirement through the automotive and industrial stacks
catalog/faults.yaml          the 20 faults, as reviewable data rather than code
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
pinned to tag `v1.5`. Both halves of that matter. Copying would fork the thing
being verified, so the evidence would no longer refer to the original. Tracking
`main` would let the device's thresholds move underneath a published coverage
report, and that has already happened twice: v1.2 changed the overheat trip from
90 C to 140 C, and v1.5 added the second temperature source that this campaign
asked for. Both times the pin meant the change arrived as a deliberate repin with
the evidence regenerated, rather than as a silent shift under a published
report.

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
