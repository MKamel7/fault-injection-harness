# Reviewer brief

You have been asked to review this project. Thank you: an outside opinion is the
one thing the work cannot produce for itself, and this page exists so you are not
handed a repository and asked "is it good?", which is a question nobody can
usefully answer.

**Budget about 60 to 90 minutes.** You are not expected to read everything.

## What this is, so you can calibrate

A simulated servo drive controller and a harness that injects faults into it, to
practise the *method* of functional safety verification: derive faults from
hazards, judge detection against a time budget, and say plainly what the design
cannot do.

It is a **portfolio project**, not a real safety case. Nothing is certified, no
ASIL or SIL is claimed, and the device is a Python simulation grounded in a
Siemens SIMOTICS S-1FK2 datasheet. Judge it as an engineering argument, not as a
compliance artifact.

## What would actually help

**Be unkind.** The failure mode for this kind of review is a friend saying "looks
solid". That outcome is worth nothing to anybody. Assume something is wrong and
go looking for it.

**Prefer evidence to opinion.** "This equation is wrong because heat cannot flow
that way" is useful. "The docs feel long" is not. If you can run something that
demonstrates a problem, that is worth more than any amount of reading.

**"I found nothing here" is a real and useful answer.** Please say it rather than
inventing something to justify the time. Knowing which areas survived scrutiny is
as valuable as knowing which did not.

**Do not assume the documents are true.** Several claims carry specific numbers.
Checking one against the code is more valuable than reading ten.

## Where to aim, given your background

Mechanical and mechatronics is exactly the right lens for the first section
below, which is where an outside eye can see things the author cannot.

### 1. Is the machine physically plausible? (the highest value area)

The thermal model is a two node network in
`src/dut_sim/motor_controller.py` (in the `embedded-test-automation`
repository). Heat is generated in the winding and leaves through the frame to
ambient, in series, because the reference motor is natural cooling, IP64.

Questions worth attacking:

- **Is the topology right?** Should the winding have any path to ambient that
  does not pass through the frame? What is missing that would matter?
- **The two time constants are chosen, not published**: 125 steps for the
  winding, 300 for the frame, a ratio of 2.4. Real winding to housing ratios are
  larger. Does that ratio being too small break anything the design depends on?
- **Iron loss is not modelled at all**, only copper loss. The consequence is that
  the same load at any speed produces the same temperature. How wrong is that for
  a PMSM, and does it matter for the conclusions?
- **Acceleration current is excluded from heating**, on the grounds that a 17 ms
  acceleration is nothing against a thermal constant of minutes. Fair?
- **The claim that a locked rotor is an overcurrent event, not a thermal one**,
  and therefore belongs in the drive's fast current loop rather than in thermal
  protection. This is load bearing for the whole argument. Is it right?
- **The datasheet is archived at `docs/datasheets/`.** Pick two or three numbers
  the code claims come from it and check they are actually there and used
  correctly. One that has already been through this: the thermal class is *not*
  in the article datasheet and is now labelled as coming from series
  documentation instead.

### 2. Does the safety argument hold together?

Read `docs/SAFETY_ARGUMENT.md`, particularly section 4 (the headline finding) and
section 5 (what is verified, what is not validated, and why independence is
zero). Then read `report/coverage.md`, which is generated from the code.

- **Does the prose overclaim relative to the numbers?** If a sentence sounds
  stronger than the table it sits next to, say so.
- **Are the scope exclusions honest or convenient?** Overspeed is excluded
  because its budget is below the command layer's resolution. Locked rotor is
  handed to overcurrent protection. Latent faults are covered for pairs only.
  Each has a stated reason. Do you believe them?
- **Three of eleven safety requirements are reported as NOT met.** Does the
  document make that clear enough, or does the surrounding text soften it?

### 3. Anything at all that reads as wrong

You are not restricted to the above. If something looks off, it probably is.

## Already known and open, so you do not spend time re-finding it

- No hardware comparison. Nothing has been run against a real motor.
- The thermal *time constant* is deliberately compressed and cannot be validated,
  so all latencies are in simulation steps and never in seconds.
- A three fault combination (mild cooling degradation plus a lying winding sensor
  plus a dead frame sensor) defeats the design. The harness only injects pairs,
  so this is documented rather than tested.
- No FMEDA, so no diagnostic coverage, SPFM or LFM figures.
- The tools, including this harness, are not qualified.

## Running it, if you want to

Both repositories use `uv`. Nothing needs installing beyond that.

```sh
git clone https://github.com/MKamel7/embedded-test-automation
cd embedded-test-automation
uv run --group dev pytest -q
```

```sh
git clone https://github.com/MKamel7/fault-injection-harness
cd fault-injection-harness
uv run --group dev pytest -q
uv run --group dev python scripts/build_report.py   # regenerates report/
```

To poke at the machine directly:

```sh
uv run --group dev python -c "
from dut_sim.motor_controller import *
s = MotorControllerSim()
s.handle_command('SET_SPEED 3000')      # rated speed, rated load by default
for _ in range(40000): s.step(1)
print(s.temperature_c, s.housing_temperature_c, s.state)
"
```

Useful things to try: `s.inject_stall(True)`, `s.cooling_scale = 0.5`,
`s.load_torque_nm = RATED_TORQUE_NM * 2`, and `GET_TEMP`, `GET_HOUSING_TEMP`,
`GET_OVERLOAD`, `GET_FAULT`, `GET_HEALTH` over `handle_command`.

**You do not have to run anything.** Reading `report/coverage.md` and
`docs/SAFETY_ARGUMENT.md` against each other is a legitimate review on its own.

## How to report back

Whatever is easiest, but this shape is the most useful:

```
Finding: one sentence saying what is wrong
Severity: high / medium / low, your judgement
Evidence: the file and line, or the command you ran and what it printed
Why it matters: what breaks, or what conclusion stops being supported
```

Plus, at the end: **what did you check that seemed fine?** That list calibrates
everything else.

## What happens to your review

It gets recorded in `docs/REVIEW.md` with your name, the date, what you looked
at, and what you found, including "nothing" where that is the answer. It will be
described as **independent peer review**, not as a qualified assessment, because
that is what it is.
