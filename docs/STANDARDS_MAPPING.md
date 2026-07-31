# Standards mapping

One safety requirement, carried through the automotive stack and the industrial
stack side by side.

This is the document the rest of the project exists to make possible. Anyone can
list four standards. What is worth something is being able to take a single
requirement and say what it is called, where it lives, and how it is verified in
both worlds, including the place where the two stop agreeing.

**Nothing here is a claim of conformance.** ISO 26262, IEC 61508, IEC 61800-5-2,
IEC 61784-3 and Automotive SPICE are paid documents, and conformance is a
judgement made by an assessor, not by a test suite. This is a mapping of concepts
and vocabulary, built by implementing the shared mechanism once and configuring
it two ways. See `docs/SAFETY_ARGUMENT.md` for the full limitations.

## 1. Why the two stacks exist at all

They answer the same question for different industries and they arrived at
nearly the same answer.

| | Automotive | Industrial |
|---|---|---|
| Base standard | ISO 26262 (an IEC 61508 derivative for road vehicles) | IEC 61508, with IEC 61800-5-2 for drives |
| Integrity level | ASIL A to D, from a vehicle level HARA | SIL 1 to 4, from risk graph or LOPA |
| Communication protection | AUTOSAR E2E | PROFIsafe (IEC 61784-3-3) |
| Process assessment | Automotive SPICE (VDA scope) | IEC 61508 part 1 lifecycle |
| Safe states, drive | application defined | STO, SS1, SS2, SLS, standardised in IEC 61800-5-2 |

The last row is the one that matters for this project's device under test. The
DUT is grounded in a servo drive datasheet, and the industrial stack has a
precise, standardised vocabulary for what a drive does when things go wrong,
where the automotive stack would say "the item enters its safe state" and leave
the definition to the item.

## 2. The worked example: SR-05

Take one requirement all the way through. From `docs/HAZARD_ANALYSIS.md`:

> **SR-05**: Loss of the command channel beyond the watchdog budget shall enter
> STO. FTTI: watchdog budget plus one step.

It traces to **SG-02** (on detection of a fault, the drive shall reach a safe
state) and **SG-04** (corrupted, stale, lost or repeated commands shall not be
acted upon), which come from **HAZ-02** (the motor continues to drive when a stop
is required) and **HAZ-04**. It is challenged by faults **FLT-C03** (silent
channel), **FLT-C06** (dropped commands), **FLT-T01** (starved watchdog) and
**FLT-T02** (a kick one step late).

### The same requirement, in both vocabularies

| Concept | Automotive | Industrial | In this repo |
|---|---|---|---|
| The hazard | The motor drives on when a stop is required | Uncontrolled motion on loss of the safety function | `docs/HAZARD_ANALYSIS.md`, HAZ-02 |
| The derived goal | Safety Goal SG-02, SG-04 | Safety function, drive shall be de-energised | SG-02, SG-04 |
| The requirement | Technical Safety Requirement | Safety requirement specification entry | SR-05 |
| Time budget | FTTI, fault tolerant time interval | Safety function response time, and F_WD_Time for the bus part | `ftti_steps` in `catalog/faults.yaml` |
| The safe state | Item defined, here "torque removed" | **STO**, Safe Torque Off, IEC 61800-5-2 clause 4.2.2.2 | `safe_state: STO` |
| Detecting the loss | E2E timeout, max delta counter exceeded | F_WD_Time expiry, F-Host passivates | `ProtectedTransport.timed_out` |
| The verification | Fault injection per ISO 26262-4 and -6 | Fault insertion testing per IEC 61508-7 | `src/fih/campaign.py` |
| Traceability of that verification | Automotive SPICE SWE.4, SWE.6 | IEC 61508-1 lifecycle documentation | `src/fih/traceability.py` |
| The result | Detected at step 10, budget 11, PASS | Same, expressed as within F_WD_Time | `report/coverage.md` |

The point of reading that table top to bottom is that **nothing in the middle
column changes what you build.** The hazard is the same hazard, the timeout is
the same timeout, and the safe state is the same de-energised drive. What changes
is what it is called, which document it is written in, and who assesses it.

## 3. Safe states, per IEC 61800-5-2

The DUT is a servo drive controller, so its safe states are named from the drive
standard rather than described in prose. This is the correct vocabulary for the
reference hardware and it is more precise than "motor stopped", which does not
say whether the drive decelerates first or whether power is removed immediately.

| Function | IEC 61800-5-2 | What it means | Used here |
|---|---|---|---|
| **STO** | Safe Torque Off, 4.2.2.2 | Power that can cause rotation is not applied. The motor coasts. No braking is implied. | The safe state for every detected fault in this catalog |
| **SS1** | Safe Stop 1, 4.2.2.3 | Controlled deceleration, then STO once stopped or after a delay | Not implemented. See below |
| SS2 | Safe Stop 2, 4.2.2.4 | Controlled deceleration to a standstill that is then actively held | Out of scope |
| SLS | Safely Limited Speed, 4.2.3.4 | Speed kept below a safe limit rather than stopped | Out of scope |

### Why STO and not SS1, stated rather than glossed

**SS1 would be the better engineering choice for most of these faults**, and the
DUT cannot offer it.

SS1 decelerates under control before removing power. For a loaded spindle or a
vertical axis, coasting to a halt under STO can be the more dangerous outcome:
the load keeps moving, and on a vertical axis without a brake it falls. Real
drives implement SS1 for exactly this reason.

SS1 requires the drive to *keep controlling* the motor during the fault
reaction, which means the fault reaction depends on the very control path that
may be what failed. That is why SS1 needs its own diagnostics and why STO is the
fallback when they cannot be trusted.

The DUT models torque command and thermal response, not a controlled
deceleration profile, so implementing SS1 here would be naming a function it does
not perform. The catalog therefore declares STO throughout, and this paragraph is
the honest version of why, rather than a footnote claiming both were considered.

## 4. Communication protection, measured rather than asserted

`src/fih/protection.py` implements the mechanism **once** and configures it
twice. The comparison table below is generated from an actual run:
`report/protection.md`.

| Concept | AUTOSAR E2E | PROFIsafe (IEC 61784-3-3) |
|---|---|---|
| Checksum | CRC, per profile | CRC2 |
| Sequence | Alive Counter, 4 bits in Profile 1 | Consecutive Number, 24 bits in V2 |
| Endpoint binding | **Data ID**, identifies a *data element* | **F_Destination_Address**, identifies a *device* |
| Timeout | max delta counter | **F_WD_Time** |
| Verdict on failure | E2E state: OK, REPEATED, WRONG_SEQUENCE, ERROR | Safety telegram invalid, F-Host passivates |
| Parameters agreed at design time | Data ID, counter width, max delta | F-Parameters: F_Dest_Add, F_Source_Add, F_WD_Time, F_iPar_CRC |

### Where they agree

Against corruption, repetition, loss and delay, they are the same mechanism and
the measured results are identical. Every one of FLT-C01 through FLT-C07 is
refused at the first exchange under both profiles, and for FLT-C03, FLT-C04 and
FLT-C06 that is **nine steps earlier than the bare protocol managed**, because
the bare protocol had nothing but the watchdog and the watchdog has to wait out
its budget.

That earliness is the real argument for a protection layer, and it is worth
being precise about why: the frame is refused **before the payload reaches the
device**. The watchdog detects that something has been wrong for a while. The
protection layer detects that this particular frame is wrong, now, and never
acts on it.

### Where they disagree, which is the interesting part

**FLT-C08** is a correctly formed, correctly checksummed, correctly sequenced
reply about the wrong quantity: the supervisor asks for a speed and is answered
with a temperature. No checksum can catch it, because nothing is corrupted. No
sequence counter can catch it, because nothing is out of order.

**E2E detects it.** A Data ID identifies a data element, so the reply carries a
different Data ID from the one expected, and the receiver refuses it:
`WRONG_ID: Data ID 162 is not the expected 11`.

**PROFIsafe does not.** An F_Destination_Address identifies a device. Every
message on the link to that device carries the same address, so a reply about the
wrong quantity from the *right* device passes every check the layer performs.

This is not an artifact of the implementation. It follows from what each
identifier identifies, and it is pinned by
`test_e2e_catches_the_masquerade_and_profisafe_does_not` so that a refactor
making the two agree fails the build and forces this section to be rewritten.

The practical consequence: under PROFIsafe, binding a response to the request
that caused it is an **application layer** responsibility. The bus layer will not
do it for you. Under E2E it comes for free, provided the Data IDs are actually
distinct, which is a configuration mistake waiting to happen and is why E2E
Data IDs are reviewed rather than generated.

## 5. Process: Automotive SPICE

The relevant processes for a verification harness are the software verification
ones. This project is *structured per* them; it is not assessed against them, and
an ASPICE capability level is a rating awarded by an assessor to an organisation,
not a property a repository can have.

| Process | What it asks for | Where it is in this repo |
|---|---|---|
| **SWE.4** Unit Verification | Unit verification strategy, criteria, results, and bidirectional traceability to detailed design | `docs/TEST_STRATEGY.md` in P1; `src/fih/traceability.py`; 100% branch coverage gated in CI |
| **SWE.6** Software Qualification Test | Qualification test against software requirements, with results and bidirectional traceability | `catalog/faults.yaml` as the test specification, `report/coverage.md` as the results |
| **SUP.9** Problem Resolution | Problems recorded, analysed, and their resolution tracked | Residual faults are recorded *as findings with rationale* rather than closed |
| **SUP.10** Change Request Management | Changes to a verified baseline are controlled | The DUT is pinned to tag v3.0, never to a branch |

The item that carries the most weight is **bidirectional** traceability. ASPICE
asks for it in both directions deliberately, and this harness enforces both and
**fails the build on a gap in either**:

- A requirement with no fault is a hole in the argument. Specified, never
  verified, and nothing would have said so.
- A fault with no requirement is scope creep or a typo. It runs, it passes, it
  appears in the coverage figure, and it verifies nothing that was asked for.

The second is the one that quietly inflates a report, and one mistyped character
is enough to cause it. `tests/test_catalog_and_traceability.py` verifies the gate
by breaking it in both directions, because a gate nobody has watched fail is an
assumption rather than a control.

## 6. What this mapping does not cover

- **No ASIL and no SIL.** Both come from a system level risk assessment with
  operational context. A bench simulation has none. `docs/SAFETY_ARGUMENT.md`
  states what would be needed.
- **Neither protection standard is implemented.** The shared skeleton is, with
  the real CRC widths and counter widths noted rather than reproduced.
- **No hardware architectural metrics.** SPFM, LFM and PMHF need an FMEDA over a
  real bill of materials with FIT rates.
- **Single fault at a time.** Latent plus primary fault combinations, which is
  where single channel designs actually fail, are out of scope and named as a
  gap rather than omitted.
