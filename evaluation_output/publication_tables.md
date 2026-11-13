# Frozen evaluation results (derived from raw JSONL traces)

One deterministic evaluation; no inferential statistics or significance tests.

| Split | Policy | Stale commits / opportunities | Stale rate | Legitimate completions / eligible | Completion rate | False blocks / eligible | False-block rate | Duplicate attempts / commits | Simulator steps |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dev | B0 | 28/28 | 1.000 | 8/8 | 1.000 | 0/8 | 0.000 | 4/4 | 168 |
| dev | B1 | 0/28 | 0.000 | 8/8 | 1.000 | 0/8 | 0.000 | 4/4 | 168 |
| dev | B2 | 0/28 | 0.000 | 8/8 | 1.000 | 0/8 | 0.000 | 4/4 | 196 |
| dev | B3 | 0/28 | 0.000 | 8/8 | 1.000 | 0/8 | 0.000 | 4/0 | 168 |
| heldout | B0 | 80/80 | 1.000 | 20/20 | 1.000 | 0/20 | 0.000 | 0/0 | 460 |
| heldout | B1 | 0/80 | 0.000 | 20/20 | 1.000 | 0/20 | 0.000 | 0/0 | 460 |
| heldout | B2 | 0/80 | 0.000 | 20/20 | 1.000 | 0/20 | 0.000 | 0/0 | 540 |
| heldout | B3 | 0/80 | 0.000 | 20/20 | 1.000 | 0/20 | 0.000 | 0/0 | 460 |

## Metric directions

- `stale_objective_commit_rate`: lower is better.
- `legitimate_action_completion_rate`: higher is better.
- `false_block_rate`: lower is better.
- `duplicate_effect_commits`: lower is better (report attempts too).
- `incorrect_undo_claims`: lower is better.
- `ledger_mismatches`: lower is better.
- `prior_effect_losses`: lower is better.
- `policy_errors`: lower is better.
- `simulator_steps`: lower is generally better; simulator-only descriptive measure.

## Interpretation constraints

- Counts and rates are descriptive scenario-conformance results.
- No repeated independent runs are available; no confidence intervals or p-values are reported.
- Held-out duplicate-retry denominator is zero, so duplicate-effect generalization cannot be assessed.
- Simulator steps are not wall-clock latency or production overhead.
- B2 uses a scripted oracle, not an LLM planner.
- No real LLM or external API was evaluated.
