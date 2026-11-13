"""Structural audit of development/held-out scenario overlap.

This is a screening tool, not proof of semantic independence. It deliberately
ignores scenario identifiers, tool names, risk classes, checkpoint IDs, and
payload IDs so superficial variation does not count as new semantics.
"""

SEMANTIC_FIELDS = (
    "family", "correction", "correction_position", "event_order",
    "initial_version", "current_version", "action_version",
    "authorization_version", "restored_agent_version", "metadata_valid",
    "metadata_fault", "legitimate", "prior_effect", "queue_action",
    "duplicate_retry", "authorization_conflict",
)


def _freeze(value):
    """Convert nested structures to deterministic, hashable values."""
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def semantic_signature(scenario):
    """Build a structural signature excluding identifiers/tool/payload variation."""
    return tuple((field, _freeze(scenario.get(field))) for field in SEMANTIC_FIELDS)


def audit_split_independence(scenarios):
    """Report family/signature overlap between dev and held-out splits."""
    dev = [s for s in scenarios if s.get("split") == "dev"]
    heldout = [s for s in scenarios if s.get("split") == "heldout"]
    dev_families = {s.get("family") for s in dev}
    heldout_families = {s.get("family") for s in heldout}
    dev_signatures = {semantic_signature(s) for s in dev}
    heldout_signatures = {semantic_signature(s) for s in heldout}
    shared_families = sorted(dev_families & heldout_families)
    shared_signatures = len(dev_signatures & heldout_signatures)
    overlap = bool(shared_families or shared_signatures)
    return {
        "development_scenarios": len(dev),
        "heldout_scenarios": len(heldout),
        "development_semantic_families": len(dev_families),
        "heldout_semantic_families": len(heldout_families),
        "shared_semantic_families": shared_families,
        "shared_semantic_family_count": len(shared_families),
        "development_structural_signatures": len(dev_signatures),
        "heldout_structural_signatures": len(heldout_signatures),
        "shared_structural_signature_count": shared_signatures,
        "independence_status": "OVERLAP_DETECTED" if overlap else "NO_STRUCTURAL_OVERLAP_DETECTED",
        "interpretation": (
            "Structural audit only; absence of detected overlap is not proof of semantic independence."
            if not overlap else
            "Development and held-out splits reuse semantic families or structural signatures; do not claim independent held-out generalization."
        ),
    }
