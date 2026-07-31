# Requirement to test traceability

Generated from `catalog/faults.yaml` and `docs/HAZARD_ANALYSIS.md`. Do not edit by hand.

Both directions are enforced and the build fails on a gap in either: a requirement with no fault is a hole in the argument, and a fault with no requirement is scope creep or a typo that would inflate coverage.

| Requirement | Challenged by | Verdict |
|---|---|---|
| SR-01 | FLT-C01 | satisfied |
| SR-02 | FLT-C02, FLT-C05, FLT-C07 | satisfied |
| SR-03 | FLT-S02 | satisfied |
| SR-04 | FLT-A01 | satisfied |
| SR-05 | FLT-C03, FLT-T01, FLT-T02 | satisfied |
| SR-06 | FLT-C04, FLT-C06, FLT-C08 | satisfied |
| SR-07 | FLT-T04 | satisfied |
| SR-08 | FLT-T02, FLT-T03, FLT-T04 | satisfied |
| SR-09 | FLT-S04, FLT-A02, FLT-T05 | satisfied |
| SR-10 | FLT-S01, FLT-S03, FLT-S05 | satisfied |

| Fault | Class | Challenges | Expectation |
|---|---|---|---|
| FLT-C01 | communication | SR-01 | detected |
| FLT-C02 | communication | SR-02 | detected |
| FLT-C03 | communication | SR-05 | detected |
| FLT-C04 | communication | SR-06 | detected |
| FLT-C05 | communication | SR-02 | detected |
| FLT-C06 | communication | SR-06 | detected |
| FLT-C07 | communication | SR-02 | detected |
| FLT-C08 | communication | SR-06 | residual |
| FLT-S01 | sensor | SR-10 | detected |
| FLT-S02 | sensor | SR-03 | detected |
| FLT-S03 | sensor | SR-10 | detected |
| FLT-S05 | sensor | SR-10 | residual |
| FLT-S04 | sensor | SR-09 | residual |
| FLT-A01 | actuator | SR-04 | detected |
| FLT-A02 | actuator | SR-09 | residual |
| FLT-T01 | timing | SR-05 | detected |
| FLT-T02 | timing | SR-05, SR-08 | detected |
| FLT-T03 | timing | SR-08 | detected |
| FLT-T04 | timing | SR-07, SR-08 | detected |
| FLT-T05 | timing | SR-09 | detected |
