# Fault injection harness

[![CI](https://github.com/MKamel7/fault-injection-harness/actions/workflows/verify.yml/badge.svg)](https://github.com/MKamel7/fault-injection-harness/actions)
[![Faults](https://img.shields.io/badge/faults-29%20injected%2C%2024%20caught-brightgreen)](docs)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.12-blue)](https://www.python.org)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue)](LICENSE)


Hazard derived fault injection against an embedded motor controller, producing a
requirement to test traceability matrix and a fault coverage report with
detection latency measured against a fault tolerant time interval budget.

Communication faults are additionally run through a CRC, counter and timeout
protection layer configured as **both AUTOSAR E2E and PROFIsafe**, and the two
are compared on the same fault set.

> **This models the mechanism, it does not implement either standard.** The CRC8
> uses the SAE J1850 polynomial `0x1D`, which is correct for E2E Profile 1, and
> the same 8-bit CRC is reused for the PROFIsafe configuration. Real PROFIsafe
> uses a wider CRC and a 24-bit consecutive number over its F-Parameters. What
> is being compared here is the behaviour of a CRC plus counter plus timeout
> scheme under injected faults, not conformance to either specification. See
> "What this is not" below.

```
29 faults   24 detected in time   0 detected late   5 residual   5 catalogued pairs
326 tests   100% branch coverage   ruff + mypy strict   these counts gated in CI
3 of 11 safety requirements currently NOT met, each named with why
```

## 🖼️ The whole argument, on one picture

![hazard to evidence](docs/traceability-chain.svg)

Hazard, safety goal, safety requirement, fault, and the FTTI budget each one is
judged against. Until now that chain was spread across `docs/HAZARD_ANALYSIS.md`,
`docs/SAFETY_ARGUMENT.md` and `report/traceability.md`, so seeing that any
particular hazard is answered by anything at all meant reading three documents
side by side. It is the intellectual contribution of the repository and it was
the one thing not on a page.

**It is generated, not drawn**, by `scripts/render_chain.py`, from the same
loaders the campaign uses. Every arrow is a link one of those files asserts:
a goal connects to a hazard because the goal's own row names it, and a fault
connects to a requirement because the fault's `challenges` list names it.
`scripts/check_docs.py` regenerates the SVG and compares, so a stale diagram
fails the build. That check exists because this repository has already been
bitten by the drawn-once version of the same problem: for four weeks this
README claimed a test count 21 short of the real one while the docs gate failed
on it, and a number in a README at least gets read. A picture is never diffed.

(The gate caught this paragraph too, on its first draft, because quoting the
old figure reads as claiming it. That is the check being right rather than
annoying, so the sentence was reworded instead of the rule being loosened.)

Faults are coloured by their **catalogued expectation**, not by the last run:
green detected inside its FTTI, amber late, red residual. The picture states
what the argument claims; `report/coverage.md` states whether the claim held.
Colouring by live result would make the same committed diagram mean different
things on different days.

## 🛠️ Built with

| | |
| --- | --- |
| **Language** | Python |
| **Safety methods** | Hazard analysis, FMEDA, fault tree analysis |
| **Protection layers** | CRC, counter and timeout, configured as AUTOSAR E2E and PROFIsafe |
| **Device under test** | Simulated embedded motor controller |
| **Engineering** | Requirement-to-test traceability, GitHub Actions CI |

## 🎯 What this is for

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

**The gaps are named.** Five of the twenty nine faults are residual: the design cannot
detect them. Each one records what design change would be needed, and one of them
exists specifically to stop a fix being oversold. A campaign reporting complete
detection would not be credible.

## 📊 The headline finding

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
136 for a sustained 2x overload, 1041 for cooling degraded to 0.35 of nominal.
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
has used **87% of its headroom to the insulation limit** (100 K of 115 K), so
solving the bounding constraints gave a tolerable prediction error of **0.00%**. An accumulator sits
at *zero* during rated duty instead, and tolerates about +7% over-reading and
46 to 75% under-reading. Real drives protect this way for exactly this reason.

**What it costs.** The overload channel knows only the current, so a degraded
plant still drawing rated current leaves it at exactly zero and only a
temperature measurement notices. Neither
kind is sufficient; the pair covers two disjoint failure classes. That is what
diversity means, and it is why the fault the channel *cannot* see is catalogued
even though it passes.

**And something still gets through.** Combining both blind spots, cooling degraded
to 0.7 of nominal plus a lying winding sensor plus a dead frame channel, drives
the winding to about 165 C, past its 155 C limit, undetected. The cooling fault
alone is caught by the frame sensor; with both temperature channels gone,
nothing is left that can see it. That is three faults, so the harness cannot
express it as a pair, and it is written into the safety argument rather than left
to be found.

## ⚖️ Three outcomes, not two

A design can detect a fault and still fail to protect against it, so the catalog
distinguishes **detected**, **detected but outside budget**, and **residual**.
Collapsing the first two is how a coverage report ends up describing a drive that
burns out.

Requirement satisfaction is a **universal** claim: satisfied only when *every*
fault challenging it is detected inside its budget. The weaker existential rule
was in place first and scored SR-10 as satisfied while a sensor stuck at ambient
let the winding reach 207 C.

## 🔄 The cross domain comparison

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

## 📁 Layout

```
docs/HAZARD_ANALYSIS.md      8 hazards, 7 safety goals, 11 safety requirements with FTTI budgets
docs/SAFETY_ARGUMENT.md      claim, evidence, and at length what is NOT claimed
docs/STANDARDS_MAPPING.md    one requirement through the automotive and industrial stacks
catalog/faults.yaml          the 29 faults, as reviewable data rather than code
src/fih/campaign.py          one fault per run, deterministic, records what the device did
src/fih/report.py            judges those runs against the budgets
src/fih/traceability.py      bidirectional gate; fails the build on a gap either way
src/fih/protection.py        the shared mechanism, two profiles
report/                      generated evidence, rebuilt and checked on every push
```

## ▶️ Running it

```sh
uv run --group dev pytest                       # the catalog driven suite
uv run --group dev python scripts/build_report.py   # regenerate report/
```

The device under test is **imported, not copied**: it is
[`embedded-test-automation`](https://github.com/MKamel7/embedded-test-automation)
pinned to tag `v3.1`. Both halves of that matter. Copying would fork the thing
being verified, so the evidence would no longer refer to the original. Tracking
`main` would let the device's thresholds move underneath a published coverage
report, and that has happened at every release: the overheat trip moved, a second
temperature channel appeared, the thermal model was validated and corrected, and
a third channel replaced the second. Each arrived as a deliberate repin with the
evidence regenerated, rather than as a silent shift under a published report.

## 📋 The FMEDA, and the wall next to it

`catalog/fmeda.yaml` is an **educational** FMEDA over a **hypothetical** bill of
materials. **Every failure rate in it is invented.** Nothing computed from it
says anything about any real device, and no ASIL claim follows from it. It is
here because being able to do the arithmetic is worth demonstrating, and because
being honest about what a real one would need is worth demonstrating too.

| | |
|---|---|
| **SPFM 90.7%** | against the ASIL D target of 99%, which it does **not** meet |
| **LFM 81.7%** | against the ASIL D target of 90%, which it does **not** meet |
| **17 modes** | 725 FIT total, of which 690 safety related and 35 safe |

A synthetic analysis that happened to clear every target would be the least
believable possible outcome, so the shipped numbers are reported as they fall
and `test_fmeda.py` asserts they still miss.

Both figures went **down** when the FMEDA was brought in line with the v3.1
design (they were 93.8% and 87.9%). The element for the withdrawn estimator is
now the current sensor under the overload channel, and nothing detects that
sensor failing, so its modes are latent. The output stage mode had claimed 90%
coverage on the strength of two stall faults that never exercise it; with no
fault able to test it, the claim was withdrawn and its whole rate is now
single point. Moving the winding sensor modes to multiple point, which the fault
tree requires, pulled SPFM back up, but not by as much.

> **"Residual" means two different things in this repository, and the docs gate
> caught them colliding.** In `catalog/faults.yaml` a *residual fault* is one the
> design cannot catch at all, catalogued deliberately with the change that would
> close it: there are **five**. In ISO 26262-5, a *residual fault* is the
> uncovered fraction of a failure mode that DOES have a safety mechanism, which
> is a rate rather than a count. They are not the same idea and this note is
> here so nobody adds them together.

**The single-point term is made of two gaps, and both are named elsewhere.**
FM-CO-03, uniform latency growth with the frame sequence intact, is the gap the
campaign found by injecting FLT-T07 and watching a counter and timeout fail to
see it. FM-DR-01, torque left on after STO, is the output stage event the fault
tree declares unattackable. A test asserts every uncovered single-point mode
traces to one or the other, because an SPF contribution that no other artefact
names is a gap nobody has looked at.

### The distinction that is easy to lose

    detection coverage    24 of 29 injected faults caught. MEASURED, and a
                          statement about the contents of catalog/faults.yaml.
    diagnostic coverage   the fraction of a failure mode's RATE a mechanism
                          detects. ASSUMED, and an INPUT to the FMEDA.

A campaign cannot produce a DC number: it samples a fault list somebody wrote,
while DC integrates over a rate distribution. Letting "we caught 24 of 29"
become "diagnostic coverage is 83%" is the kind of sentence that reaches a
safety case and is not true.

What the campaign legitimately does is **falsify**. Every mode claiming
`diagnostic_coverage > 0` must name at least one injected fault that challenges
its mechanism, and the build fails if it names none, because a coverage figure
nobody has ever tested is an assumption wearing a number. That traffic runs in
one direction only. Modes that claim nothing, like the watchdog that cannot be
observed failing on its own, need no fault and are the honest latent case.

## 🌳 The fault tree, and what it found

![the fault tree](docs/fault-tree.svg)

The traceability chain proves every injected fault descends from a hazard:
nothing is injected because it seemed interesting. It cannot prove the converse,
that every **way the hazard can happen** has been attacked, because it only ever
walks outwards from faults that already exist. A fault tree starts at the top
event and decomposes downwards, so its minimal cut sets are a list the campaign
can be held against. One artefact justifies what is there; this one looks for
what is missing.

The top event is HAZ-03, the winding passing its insulation limit. The device
does not vote: any thermal channel that fires stops the drive. So protection
fails only when **every channel that could have fired in time** has failed, and
the tree is an AND over those channels (winding sensor, the frame sensor's cross
check and limit, and the overload channel on the current sensor), plus the
common causes and the output stage.

| | |
|---|---|
| **6 basic events** | 5 minimal cut sets: **3 of order 1**, 2 of order 2 |
| **1 of 3** single points of failure | challenged by an injected fault (`BE-CCF-TEMP`, by FLT-S05) |
| **2 of 3** | `BE-CCF-SUPPLY` and `BE-STO-INEFFECTIVE`, declared unattackable by this harness, with the reason |
| **2 order-2 cut sets** | 1 mapped to catalogued pairs, **1 unattacked.** An open finding |

### The result worth reading

**Which channels count depends on the demand, and that is where the single
points come from.** The frame is a large thermal mass and the overload channel
integrates current, so a locked rotor is too fast for the frame paths and
degraded cooling is invisible to the overload channel. Each demand is a gate over
the channels it can credit, and the demand itself stays out of the cut sets.

**`BE-CCF-TEMP` is an order-1 cut set.** One cause taking both temperature
sensors is caught under a stall, because the overload channel sees the current,
which is why FLT-S05 passes in the campaign. Under degraded cooling the current
is rated and the accumulator never grows, so the same common cause reaches the
top event alone: both sensors stuck with cooling degraded runs to 204 C
undetected. A test runs that combination rather than asserting it. The
diversity argument holds for heat that comes from current and not for heat that
does not.

**`BE-CCF-SUPPLY` is an order-1 cut set** for the older reason. A shared supply,
reference or ADC under the temperature AND current sensors defeats every channel
under every demand. DP-05 shows its consequence as two faults, reaching 1329 C,
but this harness cannot inject it as one event. **`BE-STO-INEFFECTIVE`** is the
third: STO in the device is a software state, so an output stage that keeps
conducting cannot be injected at all.

**The open double failure is the winding sensor reading low with the current
sensor under-reading, under a locked rotor.** Measured: the cross check does
fire, at step 28, with the winding already at 187.5 C. The other order-2 cut set,
both temperature sensors reading low, is mapped to DP-01, DP-02 and DP-04, with a
caveat the mapping code cannot see: those pairs ran under a stall or an overload,
where the overload channel caught them, and the cut set bites under degraded
cooling. A test holds the unattacked count at one so it cannot grow quietly.

**This tree replaced one that modelled a design that did not exist.** It
described a 2-of-3 majority over two sensors and a predicted-temperature
estimator, which was withdrawn in v3.0, and it carried communication faults that
cannot overheat a winding whose protection is local. That version reported 7
single points of failure, 6 of them attacked. The honest count is 3, with 1
attacked, and the difference is not an improvement or a regression in the
device: it is the tree catching up with it.

### A modelling error worth recording

The first version of this tree made the top event `AND(heat is generated,
protection fails)`. That is true as a sentence and useless as a tree: every cut
set then contains a demand event, every order rises by one, and there are **no
order-1 cut sets at all**. The single-point-of-failure gate passed while
guarding nothing, which is precisely the shape of check this repository argues
against everywhere else.

The demand is a **condition**, not a fault, which is also how IEC 61508 and ISO
26262 treat it: the operating condition under which a safety function is
required, not a failure of it. The tree is now scoped to the protection function
**on demand**, the demand is recorded separately so it stays visible, and order 1
means what it is supposed to mean. A test asserts the demand events are not in
the cut sets.

The v3.1 rebuild keeps that rule and adds its complement. The demand still
decides **which channels can act**, so each demand is a gate over the channels
it credits, never a basic event. Leaving that out is the opposite error:
crediting the overload channel against degraded cooling it cannot see, which is
exactly how `BE-CCF-TEMP` would have been hidden at order 2.

## 💡 What I learned

- **"Pass" and "fail" are not enough outcomes.** A fault that is detected late is not
  the same as one that is never detected, and calling both a failure throws away the
  information that matters most to a safety argument. Splitting the result into three
  outcomes changed what the report could say.

- **Detection latency only means something against a budget.** Measuring how fast a
  fault is caught is useless on its own. Measuring it against the fault-tolerant time
  interval turns a number into a verdict.

- **Modelling a standard is not implementing it, and saying so costs nothing.** The
  CRC8 here uses the J1850 polynomial, correct for E2E Profile 1, and the same 8-bit
  CRC is reused for the PROFIsafe configuration, where the real thing uses a wider CRC
  and a 24-bit consecutive number. Writing that limitation into the README made the
  comparison more useful, not less, because a reader knows exactly what they are
  looking at.

- **The faults you do not catch are the interesting output.** Reporting the 5 that got
  through, alongside 3 of 11 requirements not yet satisfied, is what makes the 24 that
  were caught believable.

- **An outside reviewer found what two of my own reviews missed.** A reviewer at TU
  Munich noticed the overload channel had no current sensor and therefore privileged
  access to the plant, which made my headline diversity result partly self-fulfilling.
  Two earlier model reviews had walked straight past it. The author of a hazard
  analysis is the last person able to see the hazard they did not think of, and that is
  the argument for review rather than a slogan about it. The three rounds are recorded
  in full in [`docs/REVIEW.md`](docs/REVIEW.md), including that one.

## 🔭 Future improvements

Timing faults landed on 31 August and the result is in `report/coverage.md`: **jitter is caught, drift is not.** FLT-T07 is now a documented residual, because a counter and timeout pair cannot see uniform latency growth. Every frame is individually perfect, the consecutive number is exactly one more than the last, and it arrives before the timeout; what is wrong is the relationship between the frame sequence and real elapsed time, and neither a checksum nor a counter carries any information about that. Closing it needs a timestamp in the protected frame, which is a change to what the frame carries rather than to the checks over it.

- **Implement PROFIsafe properly and delete the caveat.** The 8-bit CRC currently stands in for a scheme that really uses a wider CRC and a 24-bit consecutive number over its F-Parameters. It is the only asterisk on the headline claim.

Not doing: **renaming this to a "Framework".** It breaks every link and claims more than "harness" does, which cuts against the accuracy discipline that makes this worth reading. And not chasing 100% detection: five faults are residual by design, each recording what would be needed to catch it.

---

Built by **Mo Kamel**, M.Eng. student, Mechatronic and Cyber-Physical Systems, Technische
Hochschule Deggendorf.
[Portfolio](https://mkamel7.github.io) · [LinkedIn](https://linkedin.com/in/mo-kamel7)
