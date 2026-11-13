"""Deterministic checkpoint/restore and objective-version-gate simulator.

Mock environment only; not an agent or production safety mechanism.
"""
from objective_gate.objective_epoch_gate import (
    ObjectiveEpoch,
    is_valid_generation,
    may_commit_action,
)

POLICIES = ("B0", "B1", "B2", "B3")


def _uses_explicit_generations(scenario):
    gen_keys = (
        "initial_generation",
        "current_generation",
        "action_generation",
        "authorization_generation",
        "restored_agent_generation",
        "correction_sequence",
    )
    return any(key in scenario for key in gen_keys)


def _metadata_is_valid(scenario):
    version = scenario.get("action_version")
    base_valid = bool(scenario.get("metadata_valid")) and isinstance(version, str) and bool(version.strip())
    if not base_valid:
        return False
    if _uses_explicit_generations(scenario):
        for key in ("action_generation", "authorization_generation", "restored_agent_generation"):
            if key in scenario and not is_valid_generation(scenario.get(key)):
                return False
    return True


def validate_scenario(scenario):
    required = ("scenario_id", "family", "split", "event_order", "initial_version", "current_version",
                "correction", "checkpoint_id", "action_effect_id", "metadata_valid", "action_version",
                "legitimate", "prior_effect", "tool_name", "risk_class", "action_payload_id",
                "authorization_version", "restored_agent_version")
    missing = [key for key in required if key not in scenario]
    if missing:
        raise ValueError(f"Scenario missing required fields: {missing}")
    events = scenario["event_order"]
    if not isinstance(events, list) or not all(isinstance(e, str) for e in events):
        raise ValueError("event_order must be a list of event names")
    for required_event in ("checkpoint", "restore", "action_commit"):
        if events.count(required_event) != 1:
            raise ValueError(f"event_order must contain exactly one {required_event!r}")
    if not (events.index("checkpoint") < events.index("restore") < events.index("action_commit")):
        raise ValueError("event_order must place checkpoint before restore before action_commit")
    correction_count = events.count("correction")
    if bool(scenario["correction"]) != (correction_count >= 1):
        raise ValueError("correction flag contradicts event_order")
    if correction_count > 1:
        seq = scenario.get("correction_sequence")
        if not isinstance(seq, list) or len(seq) != correction_count:
            raise ValueError("multiple correction events require matching correction_sequence")
    uses_gen = _uses_explicit_generations(scenario)
    init_gen = scenario.get("initial_generation", 1)
    curr_gen = scenario.get("current_generation", 2 if scenario["correction"] else init_gen)
    if scenario["correction"]:
        same_label = scenario["current_version"] == scenario["initial_version"]
        same_gen = (curr_gen == init_gen) if uses_gen else True
        if same_label and same_gen:
            raise ValueError("correction scenario must change the objective version")
    if not scenario["correction"]:
        if scenario["current_version"] != scenario["initial_version"] or (uses_gen and curr_gen != init_gen):
            raise ValueError("scenario without correction cannot change the objective version")
    if events.count("prior_effect_commit") != int(bool(scenario["prior_effect"])):
        raise ValueError("prior_effect flag contradicts event_order")
    if scenario["prior_effect"] and not scenario.get("prior_effect_id"):
        raise ValueError("prior effect requires prior_effect_id")
    if bool(scenario.get("queue_action")) != (events.count("queue_action") == 1):
        raise ValueError("queue_action flag contradicts event_order")
    auth_gen = scenario.get("authorization_generation", curr_gen)
    auth_conflict_actual = (
        scenario["authorization_version"] != scenario["current_version"]
        or (uses_gen and auth_gen != curr_gen)
    )
    if scenario.get("authorization_conflict") != auth_conflict_actual:
        raise ValueError("authorization conflict flag contradicts authorization version")
    if scenario.get("duplicate_retry") and scenario.get("prior_effect_id") != scenario["action_effect_id"]:
        raise ValueError("duplicate retry must reuse the prior effect identifier")
    if not scenario.get("action_effect_id"):
        raise ValueError("action_effect_id must be non-empty")


def _safe_epoch(label, generation):
    safe_label = label if isinstance(label, str) else ""
    safe_gen = generation if is_valid_generation(generation) else 0
    return ObjectiveEpoch(label=safe_label, generation=safe_gen)


def run_scenario(scenario, policy):
    validate_scenario(scenario)
    if policy not in POLICIES:
        raise ValueError(f"Unknown policy: {policy}")
    uses_gen = _uses_explicit_generations(scenario)
    trace, steps, durable_effect_ids = [], 0, []
    if scenario.get("prior_effect"):
        prior_id = scenario["prior_effect_id"]
        durable_effect_ids.append(prior_id)
        trace.append({"event": "prior_effect_commit", "effect_id": prior_id, "objective_version": scenario["initial_version"]})
        steps += 1
    trusted_current_version = scenario["initial_version"]
    trusted_current_generation = scenario.get("initial_generation", 1)
    checkpoint_version = trusted_current_version
    checkpoint_generation = trusted_current_generation
    action_version = scenario.get("action_version")
    authorization_version = scenario.get("authorization_version")
    restored_agent_version = scenario.get("restored_agent_version", checkpoint_version)

    default_curr_gen = scenario.get("current_generation", 2 if scenario["correction"] else trusted_current_generation)
    action_generation = scenario.get(
        "action_generation",
        default_curr_gen if action_version == scenario["current_version"] else trusted_current_generation,
    )
    authorization_generation = scenario.get(
        "authorization_generation",
        default_curr_gen if authorization_version == scenario["current_version"] else trusted_current_generation,
    )
    restored_agent_generation = scenario.get(
        "restored_agent_generation",
        default_curr_gen if restored_agent_version == scenario["current_version"] else checkpoint_generation,
    )

    metadata_valid = _metadata_is_valid(scenario)
    replanned = action_blocked = action_committed = False
    action_effect_id = scenario["action_effect_id"]
    correction_seq = list(scenario.get("correction_sequence") or [])
    correction_idx = 0

    for event in scenario["event_order"]:
        if event == "prior_effect_commit":
            continue
        if event == "checkpoint":
            checkpoint_version = trusted_current_version
            checkpoint_generation = trusted_current_generation
            ev = {"event": "checkpoint_created", "checkpoint_id": scenario["checkpoint_id"],
                  "checkpoint_objective_version": checkpoint_version}
            if uses_gen:
                ev["checkpoint_objective_generation"] = checkpoint_generation
            trace.append(ev); steps += 1
        elif event == "queue_action":
            ev = {"event": "action_queued", "action_version": action_version,
                  "authorization_version": authorization_version,
                  "action_payload_id": scenario["action_payload_id"]}
            if uses_gen:
                ev["action_generation"] = action_generation
                ev["authorization_generation"] = authorization_generation
            trace.append(ev); steps += 1
        elif event == "correction":
            if correction_idx < len(correction_seq):
                step_corr = correction_seq[correction_idx]
                trusted_current_version = step_corr["version"]
                trusted_current_generation = step_corr.get("generation", trusted_current_generation + 1)
            else:
                trusted_current_version = scenario["current_version"]
                trusted_current_generation = scenario.get("current_generation", trusted_current_generation + 1)
            correction_idx += 1
            ev = {"event": "objective_corrected", "trusted_current_version": trusted_current_version,
                  "correction_position": scenario.get("correction_position")}
            if uses_gen:
                ev["trusted_current_generation"] = trusted_current_generation
            trace.append(ev); steps += 1
        elif event == "restore":
            ev = {"event": "checkpoint_restored", "checkpoint_id": scenario["checkpoint_id"],
                  "restored_agent_objective_version": restored_agent_version,
                  "trusted_current_version": trusted_current_version,
                  "durable_ledger_preserved": True}
            if uses_gen:
                ev["restored_agent_objective_generation"] = restored_agent_generation
                ev["trusted_current_generation"] = trusted_current_generation
            trace.append(ev); steps += 1
        elif event == "replan":
            current_epoch = _safe_epoch(trusted_current_version, trusted_current_generation)
            gate_allows = may_commit_action(
                action_objective=_safe_epoch(action_version, action_generation),
                current_objective=current_epoch,
                authorization_objective=_safe_epoch(authorization_version, authorization_generation),
                restored_agent_objective=_safe_epoch(restored_agent_version, restored_agent_generation),
                metadata_valid=metadata_valid,
            )
            if policy == "B2" and not gate_allows:
                action_version = authorization_version = restored_agent_version = trusted_current_version
                action_generation = authorization_generation = restored_agent_generation = trusted_current_generation
                metadata_valid = True; replanned = True
                ev = {"event": "scripted_oracle_replan", "authorized_version": action_version}
                if uses_gen:
                    ev["authorized_generation"] = action_generation
                trace.append(ev); steps += 1
        elif event == "action_commit":
            current_epoch = _safe_epoch(trusted_current_version, trusted_current_generation)
            version_matches = may_commit_action(
                action_objective=_safe_epoch(action_version, action_generation),
                current_objective=current_epoch,
                authorization_objective=_safe_epoch(authorization_version, authorization_generation),
                restored_agent_objective=_safe_epoch(restored_agent_version, restored_agent_generation),
                metadata_valid=metadata_valid,
            )
            if policy == "B1" and not version_matches:
                action_blocked = True
                ev = {"event": "objective_version_gate_block", "action_version": action_version,
                      "authorization_version": authorization_version,
                      "restored_agent_objective_version": restored_agent_version,
                      "trusted_current_version": trusted_current_version,
                      "metadata_valid": metadata_valid, "tool_name": scenario["tool_name"],
                      "risk_class": scenario["risk_class"], "action_payload_id": scenario["action_payload_id"]}
                if uses_gen:
                    ev["action_generation"] = action_generation
                    ev["authorization_generation"] = authorization_generation
                    ev["restored_agent_objective_generation"] = restored_agent_generation
                    ev["trusted_current_generation"] = trusted_current_generation
                trace.append(ev); steps += 1

            elif policy == "B3" and (not version_matches or action_effect_id in durable_effect_ids):
                action_blocked = True
                ev = {"event": "objective_version_gate_block", "action_version": action_version,
                      "authorization_version": authorization_version,
                      "restored_agent_objective_version": restored_agent_version,
                      "trusted_current_version": trusted_current_version,
                      "metadata_valid": metadata_valid, "tool_name": scenario["tool_name"],
                      "risk_class": scenario["risk_class"], "action_payload_id": scenario["action_payload_id"],
                      "idempotency_block": action_effect_id in durable_effect_ids}
                if uses_gen:
                    ev["action_generation"] = action_generation
                    ev["authorization_generation"] = authorization_generation
                    ev["restored_agent_objective_generation"] = restored_agent_generation
                    ev["trusted_current_generation"] = trusted_current_generation
                trace.append(ev); steps += 1
            elif policy == "B2" and not version_matches:
                action_version = authorization_version = restored_agent_version = trusted_current_version
                action_generation = authorization_generation = restored_agent_generation = trusted_current_generation
                metadata_valid = True; replanned = True
                ev = {"event": "scripted_oracle_replan", "authorized_version": action_version}
                if uses_gen:
                    ev["authorized_generation"] = action_generation
                trace.append(ev); steps += 1
            if not action_blocked:
                action_committed = True
                durable_effect_ids.append(action_effect_id)
                ev = {"event": "effect_committed", "effect_id": action_effect_id,
                      "action_version": action_version, "authorization_version": authorization_version,
                      "restored_agent_objective_version": restored_agent_version,
                      "trusted_current_version": trusted_current_version, "metadata_valid": metadata_valid,
                      "tool_name": scenario["tool_name"], "risk_class": scenario["risk_class"],
                      "action_payload_id": scenario["action_payload_id"]}
                if uses_gen:
                    ev["action_generation"] = action_generation
                    ev["authorization_generation"] = authorization_generation
                    ev["restored_agent_objective_generation"] = restored_agent_generation
                    ev["trusted_current_generation"] = trusted_current_generation
                trace.append(ev); steps += 1

    result = {"scenario_id": scenario["scenario_id"], "family": scenario["family"], "split": scenario["split"],
              "policy": policy, "action_attempted": True, "action_committed": action_committed,
              "action_blocked": action_blocked, "legitimate_action": scenario["legitimate"],
              "prior_effect_exists": bool(scenario.get("prior_effect")),
              "expected_prior_effect_id": scenario.get("prior_effect_id"), "action_effect_id": action_effect_id,
              "tool_name": scenario["tool_name"], "risk_class": scenario["risk_class"],
              "metadata_fault": scenario.get("metadata_fault"), "action_payload_id": scenario["action_payload_id"],
              "durable_effect_ids": durable_effect_ids, "trusted_current_version_at_end": trusted_current_version,
              "action_version_at_commit": action_version if action_committed else None,
              "authorization_version_at_commit": authorization_version if action_committed else None,
              "restored_agent_version_at_commit": restored_agent_version if action_committed else None,
              "metadata_valid_at_commit": metadata_valid if action_committed else None, "replanned": replanned,
              "duplicate_retry": bool(scenario.get("duplicate_retry")), "simulator_steps": steps, "trace": trace}
    if uses_gen:
        result["trusted_current_generation_at_end"] = trusted_current_generation
        result["action_generation_at_commit"] = action_generation if action_committed else None
        result["authorization_generation_at_commit"] = authorization_generation if action_committed else None
        result["restored_agent_generation_at_commit"] = restored_agent_generation if action_committed else None
    return result