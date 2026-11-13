import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from objective_gate.scenarios import generate_all, DEV_FAMILIES, HELDOUT_FAMILIES
from objective_gate.simulator import run_scenario, validate_scenario
from objective_gate.evaluation import evaluate_trace, aggregate_metrics
from objective_gate.scenario_audit import audit_split_independence

def scenario(family, split=None):
    if split is None:
        split = "dev" if family in DEV_FAMILIES else "heldout"
    return next(s for s in generate_all() if s["split"] == split and s["family"] == family)

def test_template_counts_and_splits():
    all_s = generate_all()
    assert len(all_s) == 140
    assert sum(s["split"] == "dev" for s in all_s) == 40
    assert sum(s["split"] == "heldout" for s in all_s) == 100
    assert {s["family"] for s in all_s if s["split"] == "dev"} == set(DEV_FAMILIES)
    assert {s["family"] for s in all_s if s["split"] == "heldout"} == set(HELDOUT_FAMILIES)

def test_f2_and_f3_have_distinct_correction_orderings():
    assert scenario("F2")["event_order"].index("correction") < scenario("F2")["event_order"].index("restore")
    assert scenario("F3")["event_order"].index("restore") < scenario("F3")["event_order"].index("correction")

def test_b0_commits_stale_actions_and_b1_blocks_them():
    for family in ("F2", "F3", "F4", "F6", "F7", "F8", "F10", "F11", "F13", "F14", "F15"):
        b0 = evaluate_trace(run_scenario(scenario(family), "B0"))
        b1 = evaluate_trace(run_scenario(scenario(family), "B1"))
        assert b0["action_committed"] and b0["stale_commit"], family
        assert b1["action_blocked"] and not b1["action_committed"], family
        assert not b1["stale_commit"], family

def test_b1_allows_valid_current_actions():
    for family in ("F1", "F5", "F9", "F12"):
        result = evaluate_trace(run_scenario(scenario(family), "B1"))
        assert result["action_committed"]
        assert not result["stale_commit"]

def test_b2_scripted_replan_handles_stale_and_conflicting_authorization():
    for family in ("F2", "F3", "F6", "F7", "F8", "F10", "F11", "F13", "F14", "F15"):
        result = evaluate_trace(run_scenario(scenario(family), "B2"))
        assert result["action_committed"], family
        assert result["replanned"], family
        assert not result["stale_commit"], family

def test_prior_effect_survives_restore_and_not_claimed_undone():
    result = evaluate_trace(run_scenario(scenario("F4"), "B1"))
    assert result["expected_prior_effect_id"] in result["durable_effect_ids"]
    assert not result["prior_effect_lost"]
    assert not result["claimed_effect_undone"]
    assert not result["ledger_mismatch"]

def test_duplicate_retry_is_detected_and_gate_does_not_claim_idempotency():
    for policy in ("B0", "B1", "B2"):
        result = evaluate_trace(run_scenario(scenario("F9"), policy))
        assert result["action_committed"]
        assert result["duplicate_effect_commit"]
        assert result["duplicate_effect_ids"] == [result["action_effect_id"]]

def test_conflicting_authorization_is_recorded_and_blocked_by_b1():
    s = scenario("F10")
    assert s["authorization_version"] != s["current_version"]
    result = evaluate_trace(run_scenario(s, "B1"))
    assert result["action_blocked"]
    assert not result["action_committed"]

def test_metrics_are_derived_from_trace_outcomes():
    records = [evaluate_trace(run_scenario(s, p)) for s in generate_all() if s["split"] == "heldout" for p in ("B0", "B1", "B2")]
    metrics = aggregate_metrics(records)
    assert len(records) == 300
    assert metrics["heldout/B0"]["stale_commits"] > 0
    assert metrics["heldout/B1"]["stale_commits"] == 0
    assert metrics["heldout/B1"]["ledger_mismatches"] == 0
    assert metrics["heldout/B1"]["legitimate_action_denominator"] > 0
    assert metrics["heldout/B1"]["duplicate_effect_commits"] == 0

def test_jsonl_round_trip_shape():
    sample = evaluate_trace(run_scenario(scenario("F1"), "B1"))
    assert json.loads(json.dumps(sample))["scenario_id"] == sample["scenario_id"]

def test_contradictory_correction_metadata_is_rejected():
    bad = dict(scenario("F2")); bad["correction"] = False
    try: validate_scenario(bad)
    except ValueError as exc: assert "correction flag contradicts event_order" in str(exc)
    else: raise AssertionError("contradictory correction metadata was accepted")

def test_missing_correction_event_is_rejected():
    bad = dict(scenario("F2")); bad["event_order"] = [e for e in bad["event_order"] if e != "correction"]
    try: validate_scenario(bad)
    except ValueError as exc: assert "correction flag contradicts event_order" in str(exc)
    else: raise AssertionError("missing correction event was accepted")

def test_invalid_event_order_is_rejected():
    bad = dict(scenario("F3")); bad["event_order"] = ["restore", "checkpoint", "correction", "action_commit"]
    try: validate_scenario(bad)
    except ValueError as exc: assert "checkpoint before restore" in str(exc)
    else: raise AssertionError("invalid event order was accepted")

def test_templates_cover_tool_risk_profiles_and_unique_payloads():
    heldout = [s for s in generate_all() if s["split"] == "heldout"]
    assert len({s["tool_name"] for s in heldout}) >= 8
    assert {s["risk_class"] for s in heldout} == {"low", "medium", "high"}
    assert len({s["action_payload_id"] for s in heldout}) == 100

def test_f6_invalid_metadata_modes_fail_closed():
    invalid = [s for s in generate_all() if s["split"] == "dev" and s["family"] == "F6"]
    assert len({s["metadata_fault"] for s in invalid}) >= 4
    for s in invalid:
        result = evaluate_trace(run_scenario(s, "B1"))
        assert result["action_blocked"] and not result["action_committed"]

def test_queued_action_is_traced_before_correction():
    s = scenario("F7")
    assert s["event_order"].index("queue_action") < s["event_order"].index("correction")
    result = run_scenario(s, "B1")
    assert any(e["event"] == "action_queued" for e in result["trace"])
    assert result["action_blocked"]

def test_restored_agent_state_version_is_checked():
    s = scenario("F8")
    assert s["restored_agent_version"] == "O1" and s["action_version"] == "O2"
    result = evaluate_trace(run_scenario(s, "B1"))
    assert result["action_blocked"] and not result["action_committed"]

def test_authorization_flag_must_match_metadata():
    bad = dict(scenario("F10")); bad["authorization_conflict"] = False
    try: validate_scenario(bad)
    except ValueError as exc: assert "authorization conflict flag" in str(exc)
    else: raise AssertionError("contradictory authorization metadata was accepted")


def test_metrics_exclude_duplicate_retry_from_fresh_completion_denominator():
    records = [evaluate_trace(run_scenario(s, p))
               for s in generate_all() if s["split"] == "dev"
               for p in ("B0", "B1", "B2")]
    metrics = aggregate_metrics(records)
    b1 = metrics["dev/B1"]
    assert b1["fresh_valid_actions_completed"] > 0
    assert b1["duplicate_retry_attempts"] == 4
    assert b1["duplicate_effect_commits"] == 4


def test_stale_rate_uses_stale_opportunities_not_all_runs():
    records = [evaluate_trace(run_scenario(s, "B0"))
               for s in generate_all() if s["split"] == "heldout"]
    b0 = aggregate_metrics(records)["heldout/B0"]
    assert b0["stale_action_opportunities"] == 80
    assert b0["stale_commits"] == 80
    assert b0["stale_objective_commit_rate"] == 1.0


def test_split_independence_audit_detects_no_overlap_now():
    audit = audit_split_independence(generate_all())
    assert audit["development_scenarios"] == 40
    assert audit["heldout_scenarios"] == 100
    assert audit["shared_semantic_family_count"] == 0
    assert audit["shared_structural_signature_count"] == 0
    assert audit["independence_status"] == "NO_STRUCTURAL_OVERLAP_DETECTED"
