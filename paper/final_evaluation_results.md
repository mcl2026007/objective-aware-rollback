# Final Experimental Evaluation

**Status: PROTOCOL FROZEN**
**Dataset Independence: NO_STRUCTURAL_OVERLAP_DETECTED**

This document records the official, frozen evaluation results for the objective-version gate simulator experiment.

## Research Question Answered
In a deterministic tool-using agent simulator, an independent generation-aware objective-version gate (`B1`) reduces post-restore actions executed under a superseded objective to **0%**, compared to **100%** failure under ordinary rollback-and-resume (`B0`), while preserving **100%** completion of actions authorized under the current objective.

## Held-out Challenge Set Results
The held-out set (`F11`-`F15`) consists of 100 templates strictly isolated from the development set (`F1`-`F10`). It introduces complex generation-aware scenarios (ABA transitions, multi-step corrections, stale authorization metadata, and stale restored agent states).

| Policy | Stale-Action Opportunities | Stale Commits | Legitimate Denominator | Legitimate Completed | False Blocks |
|---|---:|---:|---:|---:|---:|
| **B0 (Baseline)** | 80 | **80** (100%) | 20 | 20 (100%) | 0 |
| **B1 (Proposed Gate)** | 80 | **0** (0%) | 20 | 20 (100%) | 0 |
| **B2 (Scripted Replan)**| 80 | **0** (0%) | 20 | 20 (100%) | 0 |

## Verification
* **Metric Corrections**: Duplicate retries (`F9` in development) correctly record 0 fresh valid completions and do not inflate legitimate completion metrics.
* **Idempotency Limit**: Objective-version gating alone does not prevent duplicate-effect retries (as proven by 4 duplicate commits in the dev split under all policies). Idempotency remains a distinct engineering requirement.
* **Mutation Tests**: The suite explicitly detects gate bypasses, metadata validity bypasses, and missing prior effects.

## Reproducibility
The exact JSONL traces and scenarios matching these final metrics hash to:
* **Scenarios SHA-256**: `b502f04561e34c2005ad1a358ad84f8c48ecc71831292f4c7f3eab1520572ed7`
* **Traces SHA-256**: `9f46836696b5b8490612a0a9ced0234653db55d059cc94fde9c01fe319c1776d`

## Frozen evaluation v1: complete four-policy results (documentation correction)

The frozen package evaluates **four policies (B0, B1, B2, B3)** over **140 scenario
templates** (40 development and 100 held-out), for **560 policy-scenario runs**.
The held-out results from the frozen metrics artifact are:

| Policy | Stale-action opportunities | Stale commits | Stale-commit rate | Fresh valid actions completed | False blocks |
|---|---:|---:|---:|---:|---:|
| B0 | 80 | 80 | 100% | 20/20 | 0 |
| B1 | 80 | 0 | 0% | 20/20 | 0 |
| B2 | 80 | 0 | 0% | 20/20 | 0 |
| B3 | 80 | 0 | 0% | 20/20 | 0 |

B3 combines the generation-aware objective gate with a durable-effect idempotency
check. In development, each policy encountered four duplicate-retry attempts;
B0, B1, and B2 committed four duplicate effects, while B3 committed zero. The
held-out split contains no duplicate-retry cases, so it provides no held-out
duplicate-effect comparison.

All four policies had zero false blocks on the tested fresh valid actions. These
are deterministic simulator results, not evidence of real-LLM, external-service,
or production-system safety.

### Split-overlap qualification

The scenario audit found no development/held-out overlap under its specified
structural signature. This is a screening result only: the signature includes
the scenario-family field, and distinct family labels can themselves produce
disjoint signatures. It does **not** establish statistical independence or broad
semantic generalization. Describe the held-out families as distinct designed
challenge families, not independent samples.

### Reproducibility identifiers

- Frozen configuration SHA-256: `b1f014100675859214ad874833344f1dc51b48e07f8e3dc79e6cd5834ab75961`
- Scenario JSONL SHA-256: `b502f04561e34c2005ad1a358ad84f8c48ecc71831292f4c7f3eab1520572ed7`
- Actual trace JSONL SHA-256: `9f46836696b5b8490612a0a9ced0234653db55d059cc94fde9c01fe319c1776d`

Historical logs from earlier candidate versions are retained as history and do
not prove that this final frozen package has been rerun on the user's Windows
machine.
