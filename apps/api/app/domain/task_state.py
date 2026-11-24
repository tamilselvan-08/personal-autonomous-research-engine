"""Research task state machine (PRD §8.1).

This is the single place that decides which status transitions are legal. Phase 1
only creates and edits drafts, but the full table is defined now so later phases add
triggers rather than rewriting rules.
"""

from app.models.enums import TaskStatus

S = TaskStatus

ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    S.DRAFT: frozenset({S.PLANNING}),
    S.PLANNING: frozenset({S.AWAITING_APPROVAL, S.DRAFT}),
    S.AWAITING_APPROVAL: frozenset({S.PLANNING, S.DRAFT, S.APPROVED}),
    S.APPROVED: frozenset({S.QUEUED, S.AWAITING_APPROVAL}),
    S.QUEUED: frozenset({S.RUNNING, S.CANCELLED}),
    S.RUNNING: frozenset({S.PAUSED, S.COMPLETED, S.FAILED, S.CANCELLED}),
    S.PAUSED: frozenset({S.RUNNING, S.CANCELLED}),
    S.COMPLETED: frozenset({S.QUEUED}),
    S.FAILED: frozenset({S.QUEUED}),
    S.CANCELLED: frozenset(),
}

EDITABLE_STATUSES = frozenset({S.DRAFT})
# Tasks with live work must be cancelled before deletion.
NON_DELETABLE_STATUSES = frozenset({S.QUEUED, S.RUNNING, S.PAUSED, S.PLANNING})
ACTIVE_STATUSES = frozenset({S.QUEUED, S.RUNNING, S.PAUSED, S.PLANNING})
TERMINAL_STATUSES = frozenset({S.COMPLETED, S.FAILED, S.CANCELLED})


class InvalidTransitionError(ValueError):
    def __init__(self, current: TaskStatus, target: TaskStatus) -> None:
        super().__init__(f"Cannot move a task from '{current.value}' to '{target.value}'.")
        self.current = current
        self.target = target


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def assert_transition(current: TaskStatus, target: TaskStatus) -> None:
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)


def allowed_transitions(current: TaskStatus) -> list[TaskStatus]:
    return sorted(ALLOWED_TRANSITIONS[current], key=lambda s: list(TaskStatus).index(s))


def is_editable(status: TaskStatus) -> bool:
    return status in EDITABLE_STATUSES


def is_deletable(status: TaskStatus) -> bool:
    return status not in NON_DELETABLE_STATUSES
