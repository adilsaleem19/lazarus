import enum


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    DONE = "done"
    FAILED = "failed"


class InvalidTransition(Exception):
    pass


_ALLOWED: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.ANALYZING, JobStatus.FAILED},
    JobStatus.ANALYZING: {JobStatus.DONE, JobStatus.FAILED},
    JobStatus.DONE: set(),
    JobStatus.FAILED: set(),
}


def assert_transition(old: JobStatus, new: JobStatus) -> None:
    if new not in _ALLOWED[old]:
        raise InvalidTransition(f"job cannot move from {old.value!r} to {new.value!r}")
