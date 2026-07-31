# Fault injection harness

Hazard derived fault injection against an embedded motor controller, producing a
requirement to test traceability matrix and a fault coverage report with
detection latency measured against a fault tolerant time interval budget.

Communication faults are additionally run through a CRC, counter and timeout
protection layer configured as **both AUTOSAR E2E and PROFIsafe**, and the two
are compared on the same fault set.

```
20 faults    16 detected    4 residual, each named with its rationale
128 tests    100% branch coverage    ruff + mypy strict    all gated in CI
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

**A single temperature source cannot protect against its own sensor.** The
campaign measured it rather than suspecting it, and the measurement drove a
change to the device itself. Like for like, same physics, same injection, with
only the second channel suppressed:

| | Trip | Peak winding temperature |
|---|---|---|
| One temperature source | **never** | **409.6 C** |
| Two, with a cross check | step 2 | 115.5 C, inside the 140 C limit |

The drive never noticed and could not have: the protection trips on the reported
value, and the reported value was a lie. So DUT v1.5 gained a frame thermal node
with its own sensor, and three checks now run across the two channels. The
interesting one is the cross check: heat flows from the winding outward, so while
torque is commanded the frame is necessarily the cooler node, and a frame reading
above the winding reading is not a hot motor but an impossible one. That check is
the **only** thing that catches a sensor drifting 60 C low, because such a sensor
never reaches either temperature limit.

**And the fix is deliberately not oversold.** FLT-S05 injects the same lie into
*both* channels, and it is residual: the winding reached **409.6 C undetected**,
exactly as the single channel design did. Redundancy defeats independent
failures and does nothing whatever about common cause. Two sensors are two
channels only for as long as they fail independently, and a shared supply,
reference or harness makes them one channel wearing two names. Closing that one
is not a software change.

Both results are pinned by tests, so a change in either direction fails the
build. The first of those tests used to assert the opposite, that the winding
cooked undetected; that assertion failing is what forced the second source to be
built.

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

`docs/SAFETY_ARGUMENT.md` section 5 lists the limitations in full, including the
ones that should worry a reader most.
