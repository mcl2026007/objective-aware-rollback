"""Independent trace checks and metric aggregation for prototype runs."""


def _commit_is_stale(event):
    if not event.get("metadata_valid", False):
        return True
    if (
        event.get("action_version") != event.get("trusted_current_version")
        or event.get("authorization_version") != event.get("trusted_current_version")
        or event.get("restored_agent_objective_version") != event.get("trusted_current_version")
    ):
        return True
    if "trusted_current_generation" in event:
        trusted_gen = event.get("trusted_current_generation")
        if (
            event.get("action_generation") != trusted_gen
            or event.get("authorization_generation") != trusted_gen
            or event.get("restored_agent_objective_generation") != trusted_gen
        ):
            return True
    return False


def evaluate_trace(record):
    trace = record["trace"]
    commits = [event for event in trace if event.get("event") == "effect_committed"]
    prior_commits = [event for event in trace if event.get("event") == "prior_effect_commit"]
    expected_effect_ids = set()
    if record.get("expected_prior_effect_id"):
        expected_effect_ids.add(record["expected_prior_effect_id"])
    if record["action_committed"]:
        expected_effect_ids.add(record["action_effect_id"])
    observed_effect_ids = set(record["durable_effect_ids"])

    stale_commit = any(_commit_is_stale(event) for event in commits)
    all_effect_events = prior_commits + commits
    effect_ids = [event.get("effect_id") for event in all_effect_events]
    duplicate_effect_ids = sorted({effect_id for effect_id in effect_ids if effect_ids.count(effect_id) > 1})
    claimed_effect_undone = any(
        event.get("event") in {"effect_undone_claimed", "prior_effect_undone_claimed"}
        for event in trace
    )
    ledger_mismatch = observed_effect_ids != expected_effect_ids
    prior_effect_lost = bool(record.get("expected_prior_effect_id")) and (
        record["expected_prior_effect_id"] not in observed_effect_ids
    )
    gate_block_events = [event for event in trace if event.get("event") == "objective_version_gate_block"]
    # Policy errors are derived from the trace/outcome, not prefilled constants.
    policy_error = False
    if record["policy"] == "B1":
        if stale_commit or (record["action_blocked"] and record["action_committed"]):
            policy_error = True
        if gate_block_events and record["action_committed"]:
            policy_error = True
    if record["policy"] == "B2" and record["action_committed"] and stale_commit:
        policy_error = True

    return {
        **{k: v for k, v in record.items() if k != "trace"},
        "stale_commit": stale_commit,
        "false_block": bool(record["action_blocked"] and record["legitimate_action"]),
        "claimed_effect_undone": claimed_effect_undone,
        "ledger_mismatch": ledger_mismatch,
        "prior_effect_lost": prior_effect_lost,
        "duplicate_effect_ids": duplicate_effect_ids,
        "duplicate_effect_commit": bool(duplicate_effect_ids),
        "policy_error": policy_error,
        "trace": trace,
    }


def aggregate_metrics(records):
    """Aggregate outcomes with explicit, non-overlapping denominators.

    Duplicate retries are reported separately and are not credited as fresh
    legitimate-action completions. Scenario templates are conformance cases,
    not independent statistical samples.
    """
    groups = {}
    for split in sorted({r["split"] for r in records}):
        for policy in sorted({r["policy"] for r in records}):
            subset = [r for r in records if r["split"] == split and r["policy"] == policy]
            if not subset:
                continue
            stale_opportunities = sum(not bool(r["legitimate_action"]) for r in subset)
            valid_fresh = [r for r in subset if r["legitimate_action"] and not r.get("duplicate_retry", False)]
            fresh_denominator = len(valid_fresh)
            fresh_completed = sum(bool(r["action_committed"] and not r["action_blocked"]) for r in valid_fresh)
            duplicate_retries = [r for r in subset if r.get("duplicate_retry", False)]
            duplicate_commits = sum(bool(r.get("duplicate_effect_commit")) for r in subset)
            stale_commits = sum(bool(r["stale_commit"]) for r in subset)
            false_blocks = sum(bool(r["false_block"]) for r in valid_fresh)
            groups[f"{split}/{policy}"] = {
                "runs": len(subset),
                "stale_action_opportunities": stale_opportunities,
                "stale_commits": stale_commits,
                "stale_objective_commit_rate": stale_commits / stale_opportunities if stale_opportunities else None,
                "fresh_valid_action_denominator": fresh_denominator,
                "legitimate_action_denominator": fresh_denominator,  # backward-compatible field name, now excludes retries
                "fresh_valid_actions_completed": fresh_completed,
                "legitimate_action_completion_rate": fresh_completed / fresh_denominator if fresh_denominator else None,
                "false_blocks": false_blocks,
                "false_block_denominator": fresh_denominator,
                "false_block_rate": false_blocks / fresh_denominator if fresh_denominator else None,
                "duplicate_retry_attempts": len(duplicate_retries),
                "duplicate_effect_commits": duplicate_commits,
                "incorrect_undo_claims": sum(bool(r["claimed_effect_undone"]) for r in subset),
                "ledger_mismatches": sum(bool(r["ledger_mismatch"]) for r in subset),
                "prior_effect_losses": sum(bool(r["prior_effect_lost"]) for r in subset),
                "policy_errors": sum(bool(r["policy_error"]) for r in subset),
                "simulator_steps": sum(int(r["simulator_steps"]) for r in subset),
            }
    return groups
