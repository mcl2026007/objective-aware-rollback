import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from objective_gate.objective_epoch_gate import ObjectiveEpoch, may_commit_action
from objective_gate.simulator import run_scenario
from objective_gate.evaluation import evaluate_trace


def _make_aba_scenario(*, action_gen=1, auth_gen=1, restored_gen=1, legitimate=False, metadata_valid=True):
    return {
        "scenario_id": f"test-aba-gen-{action_gen}-{auth_gen}-{restored_gen}",
        "family": "F_ABA",
        "split": "heldout",
        "checkpoint_id": "cp-aba-01",
        "correction": True,
        "correction_position": "aba_multi_step",
        "correction_sequence": [
            {"version": "O2", "generation": 2},
            {"version": "O1", "generation": 3},
        ],
        "event_order": ["checkpoint", "correction", "correction", "restore", "action_commit"],
        "initial_version": "O1",
        "initial_generation": 1,
        "current_version": "O1",
        "current_generation": 3,
        "action_version": "O1",
        "action_generation": action_gen,
        "authorization_version": "O1",
        "authorization_generation": auth_gen,
        "restored_agent_version": "O1",
        "restored_agent_generation": restored_gen,
        "metadata_valid": metadata_valid,
        "legitimate": legitimate,
        "prior_effect": False,
        "prior_effect_id": None,
        "action_effect_id": "effect-aba-01",
        "tool_name": "delete_resource",
        "risk_class": "high",
        "metadata_fault": None if metadata_valid else "invalid_generation",
        "action_payload_id": "payload-aba-01",
        "queue_action": False,
        "duplicate_retry": False,
        "authorization_conflict": auth_gen != 3,
    }


def test_aba_old_action_is_rejected_even_when_label_matches_again():
    objective_a_generation_1 = ObjectiveEpoch(label="A", generation=1)
    objective_b_generation_2 = ObjectiveEpoch(label="B", generation=2)
    objective_a_generation_3 = ObjectiveEpoch(label="A", generation=3)

    # History: A(gen 1) -> B(gen 2) -> A(gen 3).
    assert objective_a_generation_1.label == objective_a_generation_3.label
    assert objective_b_generation_2.generation < objective_a_generation_3.generation

    # An action prepared under the first A must not commit under the new A.
    assert not may_commit_action(
        action_objective=objective_a_generation_1,
        current_objective=objective_a_generation_3,
    )


def test_action_for_current_generation_is_allowed():
    current = ObjectiveEpoch(label="A", generation=3)
    assert may_commit_action(action_objective=current, current_objective=current)


def test_invalid_metadata_fails_closed_even_for_matching_generation():
    current = ObjectiveEpoch(label="A", generation=3)
    assert not may_commit_action(
        action_objective=current,
        current_objective=current,
        metadata_valid=False,
    )


def test_simulator_b1_blocks_stale_aba_generation_while_b0_commits():
    s = _make_aba_scenario(action_gen=1, auth_gen=1, restored_gen=1, legitimate=False)
    b0 = evaluate_trace(run_scenario(s, "B0"))
    b1 = evaluate_trace(run_scenario(s, "B1"))
    assert b0["action_committed"] and b0["stale_commit"]
    assert b1["action_blocked"] and not b1["action_committed"]
    assert not b1["stale_commit"]
    assert not b1["policy_error"]


def test_simulator_b1_allows_current_aba_generation_3():
    s = _make_aba_scenario(action_gen=3, auth_gen=3, restored_gen=3, legitimate=True)
    b1 = evaluate_trace(run_scenario(s, "B1"))
    assert b1["action_committed"] and not b1["action_blocked"]
    assert not b1["stale_commit"]
    assert not b1["false_block"]
    assert b1["action_generation_at_commit"] == 3


def test_simulator_b1_blocks_stale_authorization_or_restored_generation_in_aba():
    s_stale_auth = _make_aba_scenario(action_gen=3, auth_gen=1, restored_gen=3, legitimate=False)
    res_auth = evaluate_trace(run_scenario(s_stale_auth, "B1"))
    assert res_auth["action_blocked"] and not res_auth["action_committed"]

    s_stale_restored = _make_aba_scenario(action_gen=3, auth_gen=3, restored_gen=1, legitimate=False)
    res_restored = evaluate_trace(run_scenario(s_stale_restored, "B1"))
    assert res_restored["action_blocked"] and not res_restored["action_committed"]


def test_simulator_b1_fails_closed_on_invalid_generation_number():
    s_bad_gen = _make_aba_scenario(action_gen=0, auth_gen=3, restored_gen=3, legitimate=False)
    res = evaluate_trace(run_scenario(s_bad_gen, "B1"))
    assert res["action_blocked"] and not res["action_committed"]
