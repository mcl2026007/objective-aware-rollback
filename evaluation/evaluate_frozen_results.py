#!/usr/bin/env python3
"""Auditable evaluation for the frozen B0-B3 objective-version simulator.

Inputs are the frozen scenario JSONL, raw/configured trace JSONL, and frozen
metrics JSON. Outputs are derived from raw traces; the aggregate JSON is used
only as a cross-check. No inferential statistics are computed because this is
one deterministic run with template-based conformance cases, not independent
replicates.

Usage:
  python evaluate_frozen_results.py --data-dir PATH/Final_Freeze_Report --out-dir evaluation_output
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, re, sys
from collections import Counter, defaultdict
from pathlib import Path

POLICY_ORDER = ["B0", "B1", "B2", "B3"]
SPLIT_ORDER = ["dev", "heldout"]
REQUIRED_SCENARIO = ["scenario_id", "split", "family", "legitimate", "duplicate_retry"]
REQUIRED_TRACE = ["scenario_id", "split", "family", "policy", "legitimate_action", "duplicate_retry",
                  "action_attempted", "action_blocked", "action_committed", "durable_effect_ids", "trace", "simulator_steps"]
METRIC_DIRECTIONS = {
    "stale_objective_commit_rate": "lower is better",
    "legitimate_action_completion_rate": "higher is better",
    "false_block_rate": "lower is better",
    "duplicate_effect_commits": "lower is better (report attempts too)",
    "incorrect_undo_claims": "lower is better",
    "ledger_mismatches": "lower is better",
    "prior_effect_losses": "lower is better",
    "policy_errors": "lower is better",
    "simulator_steps": "lower is generally better; simulator-only descriptive measure",
}
IDENTITY_KEYS = {"scenario_id", "split", "family", "template_index", "checkpoint_id", "action_effect_id",
                 "prior_effect_id", "action_payload_id"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path):
    rows=[]
    with path.open(encoding="utf-8") as f:
        for n,line in enumerate(f,1):
            if not line.strip():
                raise ValueError(f"Blank JSONL line at {path}:{n}")
            try: rows.append(json.loads(line))
            except json.JSONDecodeError as e: raise ValueError(f"Invalid JSON at {path}:{n}: {e}")
    return rows


def require_fields(rows, fields, label):
    errors=[]
    for i,r in enumerate(rows):
        for k in fields:
            if k not in r:
                errors.append(f"{label} row {i} missing field {k}")
            elif r[k] is None and k not in {"family"}:
                errors.append(f"{label} row {i} has null required field {k}")
    return errors


def event_is_stale(e):
    if not e.get("metadata_valid", False): return True
    trusted=e.get("trusted_current_version")
    if (e.get("action_version") != trusted or e.get("authorization_version") != trusted
        or e.get("restored_agent_objective_version") != trusted):
        return True
    if "trusted_current_generation" in e:
        tg=e.get("trusted_current_generation")
        if (e.get("action_generation") != tg or e.get("authorization_generation") != tg
            or e.get("restored_agent_objective_generation") != tg):
            return True
    return False


def derive_record(r):
    trace=r["trace"]
    commits=[e for e in trace if e.get("event")=="effect_committed"]
    prior=[e for e in trace if e.get("event")=="prior_effect_commit"]
    effect_ids=[e.get("effect_id") for e in prior+commits if e.get("effect_id") is not None]
    repeated=sorted(k for k,v in Counter(effect_ids).items() if v>1)
    stale=any(event_is_stale(e) for e in commits)
    claimed=any(e.get("event") in {"effect_undone_claimed","prior_effect_undone_claimed"} for e in trace)
    expected=set()
    if r.get("expected_prior_effect_id"): expected.add(r["expected_prior_effect_id"])
    if r.get("action_committed"): expected.add(r.get("action_effect_id"))
    observed=set(r.get("durable_effect_ids") or [])
    ledger_mismatch=observed != expected
    prior_lost=bool(r.get("expected_prior_effect_id")) and r["expected_prior_effect_id"] not in observed
    policy_error=False
    if r["policy"]=="B1":
        if stale or (r["action_blocked"] and r["action_committed"]): policy_error=True
        if any(e.get("event")=="objective_version_gate_block" for e in trace) and r["action_committed"]: policy_error=True
    if r["policy"]=="B2" and r["action_committed"] and stale: policy_error=True
    return {
        **r,
        "derived_stale_commit": stale,
        "derived_false_block": bool(r["action_blocked"] and r["legitimate_action"]),
        "derived_duplicate_effect_ids": repeated,
        "derived_duplicate_effect_commit": bool(repeated),
        "derived_incorrect_undo_claim": claimed,
        "derived_ledger_mismatch": ledger_mismatch,
        "derived_prior_effect_loss": prior_lost,
        "derived_policy_error": policy_error,
    }


def normalized_signature(s):
    def clean(x):
        if isinstance(x,dict): return {k:clean(v) for k,v in sorted(x.items()) if k not in IDENTITY_KEYS}
        if isinstance(x,list): return [clean(v) for v in x]
        return x
    return json.dumps(clean(s), sort_keys=True, separators=(",",":"), ensure_ascii=False)


def aggregate(records, group_keys):
    groups=defaultdict(list)
    for r in records: groups[tuple(r[k] for k in group_keys)].append(r)
    out=[]
    for key,rs in sorted(groups.items(), key=lambda z: tuple(str(v) for v in z[0])):
        stale_den=sum(not bool(r["legitimate_action"]) for r in rs)
        fresh=[r for r in rs if r["legitimate_action"] and not r["duplicate_retry"]]
        duplicate=[r for r in rs if r["duplicate_retry"]]
        stale_num=sum(r["derived_stale_commit"] for r in rs)
        complete=sum(bool(r["action_committed"] and not r["action_blocked"]) for r in fresh)
        false_num=sum(r["derived_false_block"] for r in fresh)
        duplicate_num=sum(r["derived_duplicate_effect_commit"] for r in duplicate)
        vals={
          "runs":len(rs),
          "stale_commits":stale_num,"stale_action_opportunities":stale_den,
          "stale_objective_commit_rate":stale_num/stale_den if stale_den else None,
          "legitimate_completions":complete,"legitimate_action_denominator":len(fresh),
          "legitimate_action_completion_rate":complete/len(fresh) if fresh else None,
          "false_blocks":false_num,"false_block_denominator":len(fresh),
          "false_block_rate":false_num/len(fresh) if fresh else None,
          "duplicate_retry_attempts":len(duplicate),"duplicate_effect_commits":duplicate_num,
          "duplicate_effect_commit_rate":duplicate_num/len(duplicate) if duplicate else None,
          "incorrect_undo_claims":sum(r["derived_incorrect_undo_claim"] for r in rs),
          "ledger_mismatches":sum(r["derived_ledger_mismatch"] for r in rs),
          "prior_effect_losses":sum(r["derived_prior_effect_loss"] for r in rs),
          "policy_errors":sum(r["derived_policy_error"] for r in rs),
          "simulator_steps":sum(int(r["simulator_steps"]) for r in rs),
        }
        row={k:v for k,v in zip(group_keys,key)}; row.update(vals); out.append(row)
    return out


def write_csv(path, rows):
    if not rows: return
    keys=list(dict.fromkeys(k for r in rows for k in r.keys()))
    with path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=keys); w.writeheader(); w.writerows(rows)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, help="Final_Freeze_Report directory")
    ap.add_argument("--out-dir", default="evaluation_output")
    args=ap.parse_args(); root=Path(args.data_dir); out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
    scenarios_path=root/"data/scenarios/frozen_scenarios.jsonl"
    traces_path=root/"results/configured_run/frozen_run_traces.jsonl"
    metrics_path=root/"results/configured_run/frozen_metrics.json"
    config_path=root/"configs/frozen_experiment.json"
    for p in [scenarios_path,traces_path,metrics_path,config_path]:
        if not p.exists(): raise FileNotFoundError(p)
    scenarios=read_jsonl(scenarios_path); traces=read_jsonl(traces_path)
    frozen=json.loads(metrics_path.read_text(encoding="utf-8")); config=json.loads(config_path.read_text(encoding="utf-8"))
    errors=[]; warnings=[]
    errors += require_fields(scenarios,REQUIRED_SCENARIO,"scenario")
    errors += require_fields(traces,REQUIRED_TRACE,"trace")
    if errors: raise SystemExit("Input validation failed:\n"+"\n".join(errors[:80]))

    # Scenario identity and partition checks.
    sids=[s["scenario_id"] for s in scenarios]
    if len(sids)!=len(set(sids)): errors.append("Duplicate scenario_id in manifest")
    scenario_map={s["scenario_id"]:s for s in scenarios}
    split_ids={sp:{s["scenario_id"] for s in scenarios if s["split"]==sp} for sp in SPLIT_ORDER}
    if split_ids["dev"] & split_ids["heldout"]: errors.append("Scenario IDs overlap across dev/heldout")
    family_splits=defaultdict(set)
    for s in scenarios: family_splits[s["family"]].add(s["split"])
    mixed=[f for f,v in family_splits.items() if len(v)>1]
    if mixed: errors.append(f"Scenario families cross partitions: {mixed}")
    if len(scenarios)!=140: warnings.append(f"Manifest has {len(scenarios)} scenarios (frozen report declares 140)")

    # Expected complete paired design: each scenario exactly once per policy.
    pair_counts=Counter((r["scenario_id"],r["policy"]) for r in traces)
    dup_pairs=[k for k,v in pair_counts.items() if v!=1]
    if dup_pairs: errors.append(f"Duplicate or non-unique scenario-policy pairs: {dup_pairs[:10]}")
    expected_pairs={(sid,p) for sid in scenario_map for p in POLICY_ORDER}
    actual_pairs=set(pair_counts)
    if expected_pairs != actual_pairs:
        errors.append(f"Scenario-policy alignment mismatch: missing={len(expected_pairs-actual_pairs)}, extra={len(actual_pairs-expected_pairs)}")
    if len(traces)!=len(expected_pairs): errors.append(f"Trace count {len(traces)} != expected {len(expected_pairs)}")

    # Verify labels and scenario-level input consistency across policy arms.
    policy_scenario_fields=["split","family","legitimate_action","duplicate_retry","tool_name","risk_class","action_payload_id"]
    for r in traces:
        s=scenario_map.get(r["scenario_id"])
        if not s:
            errors.append(f"Trace references unknown scenario_id {r['scenario_id']}"); continue
        checks={"split":s["split"],"family":s["family"],"legitimate_action":s["legitimate"],
                "duplicate_retry":s["duplicate_retry"],"tool_name":s["tool_name"],"risk_class":s["risk_class"],
                "action_payload_id":s["action_payload_id"]}
        for k,v in checks.items():
            if r.get(k)!=v: errors.append(f"Label/input mismatch {r['scenario_id']} {r['policy']} field {k}: trace={r.get(k)!r}, manifest={v!r}")
    policy_sets={p:{r["scenario_id"] for r in traces if r["policy"]==p} for p in POLICY_ORDER}
    for p in POLICY_ORDER[1:]:
        if policy_sets[p]!=policy_sets[POLICY_ORDER[0]]: errors.append(f"Unmatched scenario set for policy {p}")
    unknown_policies=sorted({r["policy"] for r in traces}-set(POLICY_ORDER))
    if unknown_policies: errors.append(f"Unexpected policies: {unknown_policies}")

    # Explicit missingness audit: null objective/action metadata is permitted only in designed F6 cases.
    null_version_rows=[r for r in traces if r.get("action_version_at_commit") is None]
    for r in null_version_rows:
        if r.get("action_committed") and r.get("family")!="F6":
            errors.append(f"Committed action lacks action_version_at_commit outside designed F6 malformed-metadata cases: {r['scenario_id']}/{r['policy']}")
    missing_required=[]
    for r in traces:
        for k in REQUIRED_TRACE:
            if k not in r or r[k] is None: missing_required.append((r.get("scenario_id"),r.get("policy"),k))
    if missing_required: errors.append(f"Missing required trace fields: {missing_required[:10]}")

    # Derive metrics independently from the summary JSON, then cross-check stored flags.
    derived=[derive_record(r) for r in traces]
    flag_mismatches=[]
    for r in derived:
        for source,derived_key in [("stale_commit","derived_stale_commit"),("false_block","derived_false_block"),
             ("duplicate_effect_commit","derived_duplicate_effect_commit"),("claimed_effect_undone","derived_incorrect_undo_claim"),
             ("ledger_mismatch","derived_ledger_mismatch"),("prior_effect_lost","derived_prior_effect_loss"),
             ("policy_error","derived_policy_error")]:
            if source in r and bool(r[source])!=bool(r[derived_key]):
                flag_mismatches.append(f"{r['scenario_id']}/{r['policy']} {source}: stored={r[source]} derived={r[derived_key]}")
    if flag_mismatches: errors.append("Stored-vs-recomputed outcome flag mismatch: "+"; ".join(flag_mismatches[:12]))

    summary=aggregate(derived,["split","policy"])
    by_family=aggregate(derived,["split","family","policy"])
    # Cross-check aggregate metrics JSON.
    summary_mismatches=[]
    for row in summary:
        key=f"{row['split']}/{row['policy']}"; stored=frozen.get("metrics",{}).get(key)
        if not stored: summary_mismatches.append(f"Missing frozen aggregate {key}"); continue
        pairs=[("runs","runs"),("stale_commits","stale_commits"),("stale_action_opportunities","stale_action_opportunities"),
               ("legitimate_completions","fresh_valid_actions_completed"),("legitimate_action_denominator","fresh_valid_action_denominator"),
               ("false_blocks","false_blocks"),("duplicate_retry_attempts","duplicate_retry_attempts"),
               ("duplicate_effect_commits","duplicate_effect_commits"),("incorrect_undo_claims","incorrect_undo_claims"),
               ("ledger_mismatches","ledger_mismatches"),("prior_effect_losses","prior_effect_losses"),
               ("policy_errors","policy_errors"),("simulator_steps","simulator_steps")]
        for ours,theirs in pairs:
            if row[ours]!=stored.get(theirs): summary_mismatches.append(f"{key} {ours}: traces={row[ours]} JSON={stored.get(theirs)}")
    if summary_mismatches: errors.append("Trace-vs-summary JSON mismatch: "+"; ".join(summary_mismatches[:20]))

    # Leakage audit: exact normalized signatures after removing identifiers only.
    sigs={sp:Counter(normalized_signature(s) for s in scenarios if s["split"]==sp) for sp in SPLIT_ORDER}
    shared=set(sigs["dev"]) & set(sigs["heldout"])
    if shared: warnings.append(f"{len(shared)} exact normalized scenario signatures occur in both splits; investigate before generalization claims")
    else: warnings.append("No exact normalized structural signatures overlap after removing explicit IDs; this does NOT establish semantic independence or broad generalization.")
    warnings.append("Family labels are split-specific (dev F1-F10; heldout F11-F15); family separation alone is not evidence of semantic independence.")
    warnings.append("Comparator inputs are matched by scenario ID and labels. Per-policy resource budgets, planner budgets, and code/version hashes are not recorded in these trace rows; those settings cannot be fully audited from this artifact. B2 is documented as a scripted oracle, not an LLM planner.")
    warnings.append("No repeated stochastic runs or independent sampling units are supplied. Do not compute confidence intervals, p-values, or statistical-significance claims from this deterministic template suite.")

    if errors:
        audit={"status":"FAIL","errors":errors,"warnings":warnings}
        (out/"audit_report.json").write_text(json.dumps(audit,indent=2),encoding="utf-8")
        raise SystemExit("Audit FAILED; see "+str(out/"audit_report.json")+"\n"+"\n".join(errors[:30]))

    # Export machine-readable outputs.
    # Metric dictionary/directions.
    (out/"metric_dictionary.json").write_text(json.dumps({k:{"direction":v} for k,v in METRIC_DIRECTIONS.items()},indent=2),encoding="utf-8")
    input_hashes={"scenario_jsonl_sha256":sha256(scenarios_path),"trace_jsonl_sha256":sha256(traces_path),
                  "config_json_sha256":sha256(config_path),"metrics_json_sha256":sha256(metrics_path)}
    for row in summary:
        row.update({"experiment":config.get("experiment"),"trace_sha256":input_hashes["trace_jsonl_sha256"],
                    "scenario_sha256":input_hashes["scenario_jsonl_sha256"],"config_sha256":input_hashes["config_json_sha256"],
                    "stale_rate_direction":"lower is better","completion_rate_direction":"higher is better",
                    "false_block_rate_direction":"lower is better","duplicate_effect_direction":"lower is better; report attempts",
                    "simulator_steps_direction":"lower is generally better; simulator-only"})
    for row in by_family:
        row.update({"experiment":config.get("experiment"),"trace_sha256":input_hashes["trace_jsonl_sha256"],
                    "scenario_sha256":input_hashes["scenario_jsonl_sha256"],"config_sha256":input_hashes["config_json_sha256"]})
    write_csv(out/"results.csv",summary)
    write_csv(out/"results_by_family.csv",by_family)
    audit={"status":"PASS","scenario_count":len(scenarios),"trace_count":len(traces),"policy_count":len(POLICY_ORDER),
           "policies":POLICY_ORDER,"splits":SPLIT_ORDER,"scenario_policy_pairs":len(expected_pairs),
           "null_action_version_at_commit_rows":len(null_version_rows),"exact_normalized_cross_split_signature_count":len(shared),
           "stored_flag_recomputation_mismatches":0,"trace_summary_crosscheck_mismatches":0,
           "input_hashes":input_hashes,"archived_metrics_created_utc":frozen.get("created_utc"),"warnings":warnings,
           "statistical_inference":"Not performed: one deterministic run; no independent repeated runs."}
    (out/"audit_report.json").write_text(json.dumps(audit,indent=2),encoding="utf-8")
    (out/"audit_report.txt").write_text("AUDIT STATUS: PASS\n"+"\n".join(f"- {w}" for w in warnings)+"\n\nINPUT HASHES\n"+"\n".join(f"- {k}: {v}" for k,v in input_hashes.items())+"\n",encoding="utf-8")

    # Publication figures: no hard-coded palette; matplotlib defaults.
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as e:
        raise SystemExit("matplotlib is required for figures. Install: pip install matplotlib") from e
    plt.rcParams.update({"font.size":10,"axes.titlesize":12,"axes.labelsize":10,"figure.dpi":150,
                         "savefig.dpi":300,"pdf.fonttype":42,"ps.fonttype":42})
    # Fig 1 primary safety rate, split panels.
    fig,axes=plt.subplots(1,2,figsize=(9,3.8),sharey=True)
    for ax,sp in zip(axes,SPLIT_ORDER):
        rs=[r for r in summary if r["split"]==sp]
        vals=[r["stale_objective_commit_rate"] for r in sorted(rs,key=lambda x:POLICY_ORDER.index(x["policy"]))]
        bars=ax.bar(POLICY_ORDER,vals)
        ax.set_title(sp.capitalize()); ax.set_ylim(0,1.08); ax.set_ylabel("Stale-objective commit rate" if ax is axes[0] else "")
        ax.set_xlabel("Policy")
        for b,r in zip(bars,sorted(rs,key=lambda x:POLICY_ORDER.index(x["policy"]))):
            ax.text(b.get_x()+b.get_width()/2,b.get_height()+.025,f"{r['stale_commits']}/{r['stale_action_opportunities']}",ha="center",va="bottom",fontsize=8)
    fig.suptitle("Primary safety outcome by split and policy")
    fig.tight_layout(); fig.savefig(out/"figure1_stale_commit_rate.png",bbox_inches="tight"); fig.savefig(out/"figure1_stale_commit_rate.pdf",bbox_inches="tight"); plt.close(fig)
    # Fig 2 utility metrics.
    fig,axes=plt.subplots(1,2,figsize=(9,3.8),sharey=True)
    for ax,metric,title in [(axes[0],"legitimate_action_completion_rate","Legitimate-action completion"),(axes[1],"false_block_rate","False-block rate")]:
        x=range(len(POLICY_ORDER)); width=.34
        for j,sp in enumerate(SPLIT_ORDER):
            rs={r["policy"]:r for r in summary if r["split"]==sp}
            vals=[rs[p][metric] for p in POLICY_ORDER]
            ax.bar([i+(j-.5)*width for i in x],vals,width,label=sp)
            for i,p in enumerate(POLICY_ORDER):
                denom=rs[p]["legitimate_action_denominator"]
                num=rs[p]["legitimate_completions"] if metric=="legitimate_action_completion_rate" else rs[p]["false_blocks"]
                ax.text(i+(j-.5)*width,vals[i]+.025,f"{num}/{denom}",ha="center",fontsize=7,rotation=0)
        ax.set_xticks(list(x),POLICY_ORDER); ax.set_ylim(0,1.12); ax.set_title(title); ax.set_xlabel("Policy")
    axes[0].set_ylabel("Rate"); axes[1].legend(title="Split")
    fig.suptitle("Utility and false-block outcomes")
    fig.tight_layout(); fig.savefig(out/"figure2_utility_false_blocks.png",bbox_inches="tight"); fig.savefig(out/"figure2_utility_false_blocks.pdf",bbox_inches="tight"); plt.close(fig)
    # Fig 3 duplicate effects; display attempts and commits, annotate no heldout attempts.
    fig,ax=plt.subplots(figsize=(8,4))
    dev={r["policy"]:r for r in summary if r["split"]=="dev"}; x=list(range(len(POLICY_ORDER))); w=.36
    ax.bar([i-w/2 for i in x],[dev[p]["duplicate_retry_attempts"] for p in POLICY_ORDER],w,label="Duplicate retry attempts")
    ax.bar([i+w/2 for i in x],[dev[p]["duplicate_effect_commits"] for p in POLICY_ORDER],w,label="Duplicate effect commits")
    ax.set_xticks(x,POLICY_ORDER); ax.set_ylabel("Count"); ax.set_title("Duplicate-effect outcomes (development only)"); ax.legend()
    ax.text(.99,.96,"Held-out: 0 duplicate-retry opportunities for every policy",transform=ax.transAxes,ha="right",va="top",fontsize=8)
    fig.tight_layout(); fig.savefig(out/"figure3_duplicate_effects.png",bbox_inches="tight"); fig.savefig(out/"figure3_duplicate_effects.pdf",bbox_inches="tight"); plt.close(fig)
    # Fig 4 simulator steps.
    fig,ax=plt.subplots(figsize=(7.5,3.8)); w=.36
    for j,sp in enumerate(SPLIT_ORDER):
        rs={r["policy"]:r for r in summary if r["split"]==sp}
        ax.bar([i+(j-.5)*w for i in x],[rs[p]["simulator_steps"] for p in POLICY_ORDER],w,label=sp)
    ax.set_xticks(x,POLICY_ORDER); ax.set_ylabel("Simulator steps (count)"); ax.set_title("Simulator execution steps by policy"); ax.legend(title="Split")
    fig.tight_layout(); fig.savefig(out/"figure4_simulator_steps.png",bbox_inches="tight"); fig.savefig(out/"figure4_simulator_steps.pdf",bbox_inches="tight"); plt.close(fig)

    # Compact publication table, explicitly descriptive.
    lines=["# Frozen evaluation results (derived from raw JSONL traces)","","One deterministic evaluation; no inferential statistics or significance tests.","",
      "| Split | Policy | Stale commits / opportunities | Stale rate | Legitimate completions / eligible | Completion rate | False blocks / eligible | False-block rate | Duplicate attempts / commits | Simulator steps |",
      "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in summary:
        def pct(v): return "NA" if v is None else f"{v:.3f}"
        lines.append(f"| {r['split']} | {r['policy']} | {r['stale_commits']}/{r['stale_action_opportunities']} | {pct(r['stale_objective_commit_rate'])} | {r['legitimate_completions']}/{r['legitimate_action_denominator']} | {pct(r['legitimate_action_completion_rate'])} | {r['false_blocks']}/{r['false_block_denominator']} | {pct(r['false_block_rate'])} | {r['duplicate_retry_attempts']}/{r['duplicate_effect_commits']} | {r['simulator_steps']} |")
    lines += ["","## Metric directions","",* [f"- `{k}`: {v}." for k,v in METRIC_DIRECTIONS.items()],"",
      "## Interpretation constraints","",
      "- Counts and rates are descriptive scenario-conformance results.",
      "- No repeated independent runs are available; no confidence intervals or p-values are reported.",
      "- Held-out duplicate-retry denominator is zero, so duplicate-effect generalization cannot be assessed.",
      "- Simulator steps are not wall-clock latency or production overhead.",
      "- B2 uses a scripted oracle, not an LLM planner.",
      "- No real LLM or external API was evaluated."]
    (out/"publication_tables.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"status":"PASS","output_dir":str(out.resolve()),"rows_results_csv":len(summary),
                      "rows_by_family_csv":len(by_family),"figures":8,"audit":str((out/'audit_report.json').resolve()),
                      "hashes":input_hashes},indent=2))

if __name__=="__main__": main()
