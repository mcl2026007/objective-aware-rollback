"""Print a structural overlap audit for development and held-out scenarios."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from objective_gate.scenarios import generate_all
from objective_gate.scenario_audit import audit_split_independence

if __name__ == "__main__":
    print(json.dumps(audit_split_independence(generate_all()), indent=2))
