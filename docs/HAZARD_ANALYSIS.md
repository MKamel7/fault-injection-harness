# Hazard analysis and safety requirements

Every fault in `catalog/faults.yaml` is derived from this document. Nothing is
injected because it seemed interesting; each fault exists to challenge a
requirement, each requirement answers a safety goal, and each safety goal
addresses a hazard.

## 1. Item definition

The item is an embedded motor controller driving a permanent-magnet synchronous
servomotor, commanded over a line-based serial protocol, with thermal
protection, stall handling and a software watchdog.

The device under test is `embedded-test-automation` v3.0, imported as a pinned
dependency. Its operating envelope and protection thresholds are grounded in the
data sheet for a **Siemens SIMOTICS S-1FK2**, article `1FK2105-6AF10-0SA0`, on a
SINAMICS S210 drive:

| Property | Value | Source |
|---|---|---|
| Maximum speed | 6,000 rpm | data sheet |
| Rated speed / torque | 3,000 rpm / 6.60 Nm | data sheet |
| Maximum torque | 24.00 Nm | data sheet |
| Rotor inertia | 3.5e-4 kg m² | data sheet |
| Winding limit | 140 °C | thermal class 155 (F), dT = 100 K at 40 °C ambient |
| Simulation step | 1 ms | fitted to the data sheet mechanical response |

## 2. Method, and what this analysis is not

This is a **HARA-lite**: hazards, safety goals, safety requirements, and a fault
tolerant time interval for each. It follows the shape of an ISO 26262 hazard
analysis without being one.

Three limits stated up front, because each is a claim someone could otherwise
read into this document:

- **No ASIL is assigned.** ASIL is determined by severity, exposure and
  controllability **at vehicle level**. This is a bench item with no vehicle
  context, so any ASIL here would be fabricated. Assigning one would require the
  item to be placed in a defined vehicle and operational situation.
- **No compliance is claimed**, to ISO 26262, IEC 61508 or IEC 61800-5-2. The
  vocabulary and method are used; the standards are not worked from.
- **This is not an FMEDA.** There are no component failure rates, so no
  quantitative diagnostic coverage, SPFM or LFM follows from it. What the
  campaign later reports is **detection coverage over the injected fault set**,
  which is a different and weaker claim, deliberately named as such.

## 3. Operational situation

A machine axis in a production cell. Personnel may be within reach of the driven
mechanism during setup and maintenance. The controller is commanded over a
serial link by a supervisory controller that is **not** assumed trustworthy: it
may fall silent, repeat itself, or send corrupted frames.

## 4. Hazards

| ID | Hazard | Consequence |
|---|---|---|
| HAZ-01 | Motion faster than the rated maximum | mechanical overload, ejected parts |
| HAZ-02 | Motor continues to drive when a stop is required | crushing or entanglement, no means to stop |
| HAZ-03 | Winding temperature exceeds the insulation limit | insulation breakdown, smoke, fire |
| HAZ-04 | A corrupted, stale or out of sequence command is acted upon | unintended motion in the wrong direction or at the wrong speed |
| HAZ-05 | A protection fault clears without deliberate intervention | the hazardous condition recurs unnoticed and unlogged |
| HAZ-06 | Protection depends on a single sensor that misreports | the trip never fires, and nothing indicates why |
| HAZ-07 | A failed diagnostic channel stops a healthy machine | unnecessary downtime, and protection that nuisance trips is protection that gets bypassed |
| HAZ-08 | A redundant channel fails silently | the item believes it has two channels and has one, so the argument for SG-06 quietly stops holding |

## 5. Safety goals

| ID | Safety goal | From |
|---|---|---|
| SG-01 | The commanded speed shall never exceed the rated maximum | HAZ-01 |
| SG-02 | On detection of a fault, the drive shall reach a safe state | HAZ-01, HAZ-02, HAZ-03 |
| SG-03 | The winding temperature shall not exceed the insulation limit | HAZ-03 |
| SG-04 | Corrupted, stale, lost or repeated commands shall not be acted upon | HAZ-04 |
| SG-05 | A safe state, once entered, shall persist until a deliberate reset | HAZ-05 |
| SG-06 | Overtemperature protection shall not depend solely on a reported sensor value | HAZ-06 |
| SG-07 | A fault in a diagnostic channel shall not be reported as a fault in the machine, and shall not stop it unnecessarily | HAZ-07, HAZ-08 |

## 6. Safe states

Named per **IEC 61800-5-2**, which is the functional safety standard for
adjustable speed drives and therefore the correct vocabulary for the reference
device. The mapping to what the DUT actually implements:

| Function | Meaning | In the DUT |
|---|---|---|
| **STO** (Safe Torque Off) | torque removed immediately, motor coasts | the `FAULT` state: speed forced to zero, speed commands rejected |
| **SS1** (Safe Stop 1) | controlled deceleration, then STO | approximated by `STOP` followed by a fault, **not** safety rated here |

The DUT's safe state is **STO**. `STOP` is a functional stop, not a safety
function, and this document does not treat it as one.

## 7. Fault tolerant time intervals, and one that does not fit

FTTI is the time from fault occurrence to the hazard, so detection plus
reaction must complete inside it. Where possible these are **derived**, not
chosen.

### 7.1 Overspeed, and why it is out of scope

At maximum torque the drive accelerates at `M/J = 24.0 / 3.5e-4 = 68,571 rad/s²`.
From the 6,000 rpm limit:

| Overspeed criterion | Time to reach it |
|---|---|
| +5% (6,300 rpm) | **0.46 ms** |
| +10% (6,600 rpm) | **0.92 ms** |
| +20% (7,200 rpm) | **1.83 ms** |

The FTTI for overspeed is therefore **under one millisecond**, which the 1 ms
command layer cannot resolve. That is not a modelling failure, it is the correct
conclusion: **overspeed reaction belongs in the drive's own fast control loop,
not in the command channel.** A supervisory link that can only observe the drive
every millisecond is structurally incapable of meeting that budget.

So this harness verifies the **command acceptance** boundary (SR-01: an
out of range speed is never accepted) and explicitly does **not** claim to
verify overspeed reaction time. That limit is carried into the safety argument.

### 7.2 Thermal

Measured on the DUT: at steady running the winding reaches equilibrium at
**53.1 °C** at 3,000 rpm and **66.2 °C** at 6,000 rpm, both far below the 140 °C
limit. **Normal operation never trips the thermal protection**, which is correct
behaviour and means overtemperature is reachable only through a stall or a
sensor fault. A stalled rotor at 5,000 rpm commanded reaches the limit in
**4 steps**.

Thermal FTTI is set at **20 steps**, comfortably above the observed 4. It is
quoted in steps only: P1 deliberately compresses the thermal time scale, so
converting it to seconds would be meaningless.

### 7.3 Command channel

Detection time for a silent channel is the watchdog budget itself, verified as
exact (a 10 step budget trips at 10 steps, a 50 step budget at 50). FTTI is
therefore **budget + 1 step**. For corrupted or out of range commands the FTTI is
**1 step**: the command must be rejected on arrival, never acted upon and undone.

## 8. Safety requirements

Each is testable, and each is challenged by at least one fault in the catalog.

| ID | Requirement | Goal | FTTI |
|---|---|---|---|
| SR-01 | A speed command above the rated maximum shall be rejected, not clamped | SG-01 | 1 step |
| SR-02 | A malformed or non-numeric speed command shall be rejected | SG-01, SG-04 | 1 step |
| SR-03 | On winding temperature reaching the limit, the drive shall enter STO | SG-02, SG-03 | per condition |
| SR-04 | On a stalled rotor with torque commanded, the drive shall enter STO before the insulation limit is exceeded | SG-02, SG-03 | per condition |
| SR-05 | Loss of the command channel beyond the watchdog budget shall enter STO | SG-02, SG-04 | budget + 1 |
| SR-06 | Repeated or stale responses shall not be accepted as evidence of liveness | SG-04 | budget + 1 |
| SR-07 | In STO, speed commands shall be rejected | SG-05 | invariant |
| SR-08 | STO shall persist through cooldown and through every command except an explicit reset | SG-05 | invariant |
| SR-09 | Telemetry shall remain readable in STO, so the cause is diagnosable | SG-02 | invariant |
| SR-10 | Overtemperature protection shall not be defeated by a sensor reporting implausible values | SG-06 | per condition |
| SR-11 | A contradiction between temperature channels shall be reported as a sensor fault, not as an overtemperature, and shall stop the drive only while torque is commanded | SG-07 | per condition |

## 9. Notes carried into the catalog

- **SR-06 and SR-10 are the defence in depth pair.** A channel that echoes stale
  `OK` responses defeats every protocol level check and is caught only by the
  watchdog. A temperature sensor that reports a safe value defeats the reported
  reading and is caught only by an independent trip. Together they are the
  argument that no single mechanism is load bearing.
- **Some faults are expected to be residual.** They are catalogued deliberately,
  reported as undetected, and answered with what design change would be needed.
  A campaign reporting 100% detection would not be credible.


## 9. Change impact analysis

Added after a review found that the item had changed twice while this document
had not. Both standards require the safety analysis to be revisited when the
item changes, and skipping it is what allowed HAZ-07 to exist unnoticed: a
hazard analysis re-run after v1.5 would have asked what happens when the new
sensor fails, and would have found the answer in minutes.

Recorded per release from here on, however short.

| Release | Change to the item | Impact on this analysis |
|---|---|---|
| v1.2 | Overheat trip moved from 90 C to 140 C, derived from thermal class 155 (F) | No new hazard. SR-03 and SR-04 thresholds restated as derived rather than chosen. |
| v1.4 | Typed package marker only | None. No behavioural change. |
| v1.5 | **Second temperature channel added**, with a frame node, a frame limit and a cross check | **Not assessed at the time, and it should have been.** Adds a component with its own failure modes, one of which stops a healthy machine. Now covered by HAZ-07, HAZ-08, SG-07 and SR-11, and by faults FLT-S06 and FLT-S07. |
| v2.0 | Thermal model validated against the data sheet: loss follows current rather than speed, rated duty calibrated to the permitted temperature | No new hazard, but every thermal FTTI changed. SR-03, SR-04 and SR-10 moved from a chosen 20 steps to a **derived 7**, being the time the winding takes to cover its whole permitted rise under locked rotor current. |
| v2.1 | Contradiction between channels reported as SENSOR_DISAGREEMENT rather than as an overtemperature; no trip without commanded torque; annunciation added | Closes SR-11. Also demotes the frame limit from "independent path" to "slow backstop", since it is suppressed whenever the channels disagree. |
| v2.2 | **Third channel added**, a model based estimator predicting absolute winding temperature | Closed SR-10 for the independent and common cause sensor faults. Not assessed at the time: the channel's own accuracy requirement, which turned out to be the thing that mattered. |
| v3.0 | **Thermal model rebuilt** after independent review: real margin between rated duty and the trip, series thermal network, current driven heating, RESET no longer erases thermal state; **third channel replaced** by an accumulated overload on measured current | Every thermal FTTI changed and is now stated per condition. No new hazard, but the v2.2 estimator was withdrawn: solving its bounding constraints gave a tolerable prediction error of 0.00 percent, so it required exact knowledge. The replacement tolerates roughly +7 percent over-reading and 46 to 75 percent under-reading. |

### Why four thermal requirements say "per condition" rather than a number

Because a single number would be wrong, and stating one invited a real error. A
thermal FTTI is the interval from the hazardous condition arising to the hazard
occurring, and for a thermal hazard that interval depends entirely on how hard
the machine is being driven: a locked rotor covers the permitted rise in 22
steps and an obstructed installation at rated load takes 1041.

An earlier version quoted the locked rotor figure as though it applied to all of
them. A fault exercising the slow condition was then judged on its own much
larger budget while being cited as evidence for a requirement that said 22, and
nothing compared the two. That is the easiest possible way to inflate a coverage
report, and the traceability gate now refuses it: a fault may not be judged
against a budget looser than the requirement it is evidence for. These four are
exempt from that numeric comparison because their budget genuinely is
per-condition, and the table below is the authority.

SR-07 is exempt for a different reason. "In STO, speed commands shall be
rejected" is an invariant, not a race: it must hold on every command, not within
a window. It is gated by an observation rather than a latency, so a step count
would be meaningless there too.

### FTTI budgets, and why they differ by condition

Every thermal budget is now measured rather than chosen: the steps the winding
takes to cover its whole permitted rise, 40 C to 140 C, under the condition being
tested.

| Condition | Current | Budget |
|---|---|---|
| Locked rotor | 4.29x rated | **22 steps** |
| Sustained overload, still turning | 2x rated | **136 steps** |
| Cooling degraded to 0.35 of nominal | rated | **1041 steps** |

Both are worth carrying, and testing only the first was misleading. Under
overload the cross check fires at step 27 with the winding at 117 C, inside both
budget and limit, so the second temperature source **does** protect against a
lying sensor there. It fails only under locked rotor, where the winding covers
its entire rise faster than the frame can follow. A catalog that exercised only
the stall made the redundancy look simply inadequate; it is adequate for the
likelier hazard and inadequate for the fastest one.

### What the v1.5 omission cost, stated plainly

Adding redundancy halves exposure to a missed detection and **doubles exposure
to a spurious one**, because a second channel is a second thing that can fail.
The design was changed to improve SG-06 and nobody asked what it did to
availability. The answer, measured, was that a frame sensor reading a plausible
120 C stopped a healthy motor at step 1, and did so at idle as well, on a machine
that had never moved.

That is the kind of finding a change impact analysis exists to produce, and it
took an adversarial review to surface instead.

### The trade that was never made explicitly

On a disagreement the item can stop, which is safe and less available, or
continue on one channel with annunciation, which is available and less safe.
This analysis now records the decision rather than leaving it implicit in code:

**Stop while torque is commanded, annunciate otherwise.** An item with no
trustworthy temperature reading should not keep producing torque, and a
stationary drive producing none is not a thermal hazard. The asymmetry is
deliberate: it takes the safe option exactly where the hazard exists and refuses
to take the machine down where it does not.
