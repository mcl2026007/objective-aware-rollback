"""Generation-aware gate for objective-version and ABA tests.

Integrated into the main simulator's B1 policy commit path.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectiveEpoch:
    label: str
    generation: int


def is_valid_generation(value) -> bool:
    """Return True if value is a positive integer generation (excluding bool)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def may_commit_action(
    *,
    action_objective: ObjectiveEpoch,
    current_objective: ObjectiveEpoch,
    authorization_objective: ObjectiveEpoch | None = None,
    restored_agent_objective: ObjectiveEpoch | None = None,
    metadata_valid: bool = True,
) -> bool:
    """Allow commit only when metadata is valid and all objective labels and generations match."""
    if not metadata_valid:
        return False
    auth_obj = authorization_objective if authorization_objective is not None else action_objective
    restored_obj = restored_agent_objective if restored_agent_objective is not None else current_objective
    for candidate in (action_objective, current_objective, auth_obj, restored_obj):
        if not isinstance(candidate, ObjectiveEpoch):
            return False
        if not isinstance(candidate.label, str) or not candidate.label.strip():
            return False
        if not is_valid_generation(candidate.generation):
            return False
    return (
        action_objective == current_objective
        and auth_obj == current_objective
        and restored_obj == current_objective
    )
