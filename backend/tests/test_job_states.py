"""Tests for the job state machine: queued -> analyzing -> done/failed."""

import pytest

from app.job_states import InvalidTransition, JobStatus, assert_transition


class TestValidTransitions:
    @pytest.mark.parametrize(
        ("old", "new"),
        [
            (JobStatus.QUEUED, JobStatus.ANALYZING),
            (JobStatus.QUEUED, JobStatus.FAILED),
            (JobStatus.ANALYZING, JobStatus.DONE),
            (JobStatus.ANALYZING, JobStatus.FAILED),
        ],
    )
    def test_allowed(self, old, new):
        assert_transition(old, new)  # must not raise


class TestInvalidTransitions:
    @pytest.mark.parametrize(
        ("old", "new"),
        [
            (JobStatus.QUEUED, JobStatus.DONE),  # cannot skip analysis
            (JobStatus.DONE, JobStatus.ANALYZING),  # terminal
            (JobStatus.DONE, JobStatus.FAILED),  # terminal
            (JobStatus.FAILED, JobStatus.ANALYZING),  # terminal
            (JobStatus.ANALYZING, JobStatus.QUEUED),  # no going back
        ],
    )
    def test_rejected(self, old, new):
        with pytest.raises(InvalidTransition):
            assert_transition(old, new)


def test_statuses_serialize_to_strings():
    assert JobStatus.QUEUED.value == "queued"
    assert JobStatus.ANALYZING.value == "analyzing"
    assert JobStatus.DONE.value == "done"
    assert JobStatus.FAILED.value == "failed"
