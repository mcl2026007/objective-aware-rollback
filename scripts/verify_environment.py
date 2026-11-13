import sys
import json
import hashlib
import pathlib
import collections
import datetime
import importlib.util
import platform

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

checks = []

def check(name, condition, detail):
    status = "PASS" if condition else "FAIL"
    checks.append((name, status, detail))
    print(f"[{status}] {name}: {detail}")

print("===== RESEARCH ENVIRONMENT VERIFICATION =====")

check(
    "Python version",
    sys.version_info >= (3, 12),
    sys.version.split()[0]
)

for module in [
    "json", "hashlib", "pathlib",
    "collections", "datetime"
]:
    try:
        __import__(module)
        check(module, True, "Import successful")
    except Exception as exc:
        check(module, False, str(exc))

check(
    "pytest installed",
    importlib.util.find_spec("pytest") is not None,
    "pytest available"
)

for folder in [
    "data", "logs", "results", "scripts",
    "src", "tests"
]:
    check(
        f"Directory {folder}",
        (ROOT / folder).is_dir(),
        str(ROOT / folder)
    )

dataset = ROOT / "data" / "scenarios" / "frozen_scenarios.jsonl"

check(
    "Scenario dataset",
    dataset.is_file(),
    str(dataset)
)

print("\n===== SYSTEM INFORMATION =====")
print("Platform:", platform.platform())
print("Architecture:", platform.machine())
print("CPU cores:", __import__("os").cpu_count())
print("GPU configuration: CPU-only")

failed = sum(status == "FAIL" for _, status, _ in checks)

print("\n===== FINAL RESULT =====")
print("Passed:", len(checks) - failed)
print("Failed:", failed)
print("Total:", len(checks))

sys.exit(1 if failed else 0)

