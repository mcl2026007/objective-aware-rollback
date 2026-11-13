#!/usr/bin/env python3
"""Run the deterministic candidate prototype and write validated JSONL/JSON outputs."""
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from objective_gate.scenarios import generate_all
from objective_gate.simulator import POLICIES, run_scenario
from objective_gate.evaluation import evaluate_trace, aggregate_metrics


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


def read_jsonl_validate(path):
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.endswith("\n"):
                raise ValueError(f"JSONL line {line_no} has no newline terminator")
            records.append(json.loads(line))
    return records


def main():
    config_path = ROOT / "configs" / "frozen_experiment.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    policies = config["policies"]
    splits = config["scenario_splits"]
    if not policies or any(policy not in POLICIES for policy in policies):
        raise ValueError("Configuration contains an unsupported policy.")
    if not splits or any(split not in ("dev", "heldout") for split in splits):
        raise ValueError("Configuration contains an unsupported split.")

    scenarios = [s for s in generate_all() if s["split"] in splits]
    traces = [run_scenario(s, policy) for s in scenarios for policy in policies]
    evaluated = [evaluate_trace(r) for r in traces]

    output_dir = ROOT / "results" / "configured_run"
    trace_path = output_dir / "frozen_run_traces.jsonl"
    metrics_path = output_dir / "frozen_metrics.json"
    scenario_path = ROOT / "data" / "scenarios" / "frozen_scenarios.jsonl"
    raw_trace_path = ROOT / "results" / "raw" / "frozen_run_traces.jsonl"
    summary_path = ROOT / "results" / "summary" / "frozen_metrics.json"

    # Write all canonical outputs using actual newline separators, then parse them back.
    write_jsonl(scenario_path, scenarios)
    write_jsonl(trace_path, evaluated)
    write_jsonl(raw_trace_path, evaluated)
    for frozen_path, expected_count in ((scenario_path, len(scenarios)),
                                           (trace_path, len(evaluated)),
                                           (raw_trace_path, len(evaluated))):
        reloaded = read_jsonl_validate(frozen_path)
        if len(reloaded) != expected_count:
            raise RuntimeError(f"JSONL round-trip count mismatch for {frozen_path}: {len(reloaded)} != {expected_count}")

    report = {
        "status": "final_frozen_evaluation",
        "warning": "No real LLM or external service is involved; results establish simulator conformance, not production safety.",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "configuration": config,
        "configuration_sha256": sha256(config_path),
        "scenario_templates": len(scenarios),
        "development_templates": sum(s["split"] == "dev" for s in scenarios),
        "heldout_templates": sum(s["split"] == "heldout" for s in scenarios),
        "policies": policies,
        "total_policy_scenario_runs": len(evaluated),
        "jsonl_round_trip_validated": True,
        "metrics": aggregate_metrics(evaluated),
        "jsonl_round_trip_validated": True,
        "sha256": {
            "scenarios": sha256(scenario_path),
            "configured_traces": sha256(trace_path),
            "raw_traces": sha256(raw_trace_path),
        },
    }
    serialized_report = json.dumps(report, indent=2) + "\n"
    for report_path in (metrics_path, summary_path):
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(serialized_report, encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("\nWrote:", scenario_path)
    print("Wrote:", trace_path)
    print("Wrote:", raw_trace_path)
    print("Wrote:", metrics_path)
    print("Wrote:", summary_path)


if __name__ == "__main__":
    main()
