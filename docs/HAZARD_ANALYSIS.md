# Hazard analysis and safety requirements

Every fault in `catalog/faults.yaml` is derived from this document. Nothing is
injected because it seemed interesting; each fault exists to challenge a
requirement, each requirement answers a safety goal, and each safety goal
addresses a hazard.

## 1. Item definition

The item is an embedded motor controller driving a permanent-magnet synchronous
servomotor, commanded over a line-based serial protocol, with thermal
protection, stall handling and a software watchdog.

The device under test is `embedded-test-automation` v1.3, imported as a pinned
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

## 5. Safety goals

| ID | Safety goal | From |
|---|---|---|
| SG-01 | The commanded speed shall never exceed the rated maximum | HAZ-01 |
| SG-02 | On detection of a fault, the drive shall reach a safe state | HAZ-01, HAZ-02, HAZ-03 |
| SG-03 | The winding temperature shall not exceed the insulation limit | HAZ-03 |
| SG-04 | Corrupted, stale, lost or repeated commands shall not be acted upon | HAZ-04 |
| SG-05 | A safe state, once entered, shall persist until a deliberate reset | HAZ-05 |
| SG-06 | Overtemperature protection shall not depend solely on a reported sensor value | HAZ-06 |

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
| SR-03 | On winding temperature reaching the limit, the drive shall enter STO | SG-02, SG-03 | 7 steps |
| SR-04 | On a stalled rotor with torque commanded, the drive shall enter STO before the insulation limit is exceeded | SG-02, SG-03 | 7 steps |
| SR-05 | Loss of the command channel beyond the watchdog budget shall enter STO | SG-02, SG-04 | budget + 1 |
| SR-06 | Repeated or stale responses shall not be accepted as evidence of liveness | SG-04 | budget + 1 |
| SR-07 | In STO, speed commands shall be rejected | SG-05 | 1 step |
| SR-08 | STO shall persist through cooldown and through every command except an explicit reset | SG-05 | invariant |
| SR-09 | Telemetry shall remain readable in STO, so the cause is diagnosable | SG-02 | invariant |
| SR-10 | Overtemperature protection shall not be defeated by a sensor reporting implausible values | SG-06 | 7 steps |

## 9. Notes carried into the catalog

- **SR-06 and SR-10 are the defence in depth pair.** A channel that echoes stale
  `OK` responses defeats every protocol level check and is caught only by the
  watchdog. A temperature sensor that reports a safe value defeats the reported
  reading and is caught only by an independent trip. Together they are the
  argument that no single mechanism is load bearing.
- **Some faults are expected to be residual.** They are catalogued deliberately,
  reported as undetected, and answered with what design change would be needed.
  A campaign reporting 100% detection would not be credible.
