"""Unit tests for the jobs service."""

from datetime import UTC, datetime

from app.services.jobs import (
    _JOB_EXECUTION_HISTORY,
    _JOB_STATES,
    JobExecutionRecord,
    JobMeta,
    JobState,
    get_job_history,
    get_job_state,
    is_cancellation_requested,
    mark_job_cancelled,
    mark_manual_run,
    request_job_cancellation,
    update_job_progress,
)


class TestJobMeta:
    """Tests for JobMeta dataclass."""

    def test_job_meta_creation(self) -> None:
        """Test creating JobMeta."""
        meta = JobMeta(
            id="test_job",
            name_key="jobs.names.test_job",
            fallback_name="Test Job",
        )

        assert meta.id == "test_job"
        assert meta.name_key == "jobs.names.test_job"
        assert meta.fallback_name == "Test Job"


class TestJobState:
    """Tests for JobState dataclass."""

    def test_job_state_creation(self) -> None:
        """Test creating JobState with defaults."""
        state = JobState(
            id="test_job",
            name_key="jobs.names.test_job",
            fallback_name="Test Job",
        )

        assert state.id == "test_job"
        assert state.status == "pending"
        assert state.last_run_time is None
        assert state.next_run_time is None
        assert state.running_since is None
        assert state.error is None
        assert state.files_total is None
        assert state.files_processed is None
        assert state.current_file is None
        assert state.cancellation_requested is False
        assert state.cancelled_at is None

    def test_job_state_to_dict(self) -> None:
        """Test converting JobState to dictionary."""
        now = datetime.now(UTC)
        state = JobState(
            id="test_job",
            name_key="jobs.names.test_job",
            fallback_name="Test Job",
            status="running",
            running_since=now,
            files_total=100,
            files_processed=50,
            current_file="/path/to/file.mp4",
        )

        result = state.to_dict()

        assert result["id"] == "test_job"
        assert result["name"] == "Test Job"
        assert result["name_key"] == "jobs.names.test_job"
        assert result["status"] == "running"
        assert result["running_since"] == now
        assert result["files_total"] == 100
        assert result["files_processed"] == 50
        assert result["current_file"] == "/path/to/file.mp4"


class TestJobExecutionRecord:
    """Tests for JobExecutionRecord dataclass."""

    def test_execution_record_creation(self) -> None:
        """Test creating JobExecutionRecord."""
        started_at = datetime.now(UTC)
        record = JobExecutionRecord(
            job_id="test_job",
            job_name="Test Job",
            job_type="scheduled",
            started_at=started_at,
        )

        assert record.job_id == "test_job"
        assert record.job_name == "Test Job"
        assert record.job_type == "scheduled"
        assert record.started_at == started_at
        assert record.completed_at is None
        assert record.duration_seconds is None
        assert record.status == "running"
        assert record.error is None

    def test_execution_record_to_dict(self) -> None:
        """Test converting JobExecutionRecord to dictionary."""
        started_at = datetime.now(UTC)
        record = JobExecutionRecord(
            job_id="test_job",
            job_name="Test Job",
            name_key="jobs.names.test_job",
            job_type="one-off",
            started_at=started_at,
            status="completed",
        )

        result = record.to_dict()

        assert result["job_id"] == "test_job"
        assert result["job_name"] == "Test Job"
        assert result["name_key"] == "jobs.names.test_job"
        assert result["job_type"] == "one-off"
        assert result["started_at"] == started_at
        assert result["status"] == "completed"


class TestJobProgress:
    """Tests for job progress tracking."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        # Create a test job state
        self.job_id = "progress_test_job"
        _JOB_STATES[self.job_id] = JobState(
            id=self.job_id,
            name_key="jobs.names.progress_test",
            fallback_name="Progress Test Job",
            status="running",
        )

    def teardown_method(self) -> None:
        """Clean up test fixtures."""
        if self.job_id in _JOB_STATES:
            del _JOB_STATES[self.job_id]

    def test_update_job_progress(self) -> None:
        """Test updating job progress."""
        update_job_progress(
            self.job_id,
            files_total=100,
            files_processed=25,
            current_file="/path/to/file.mp4",
        )

        state = _JOB_STATES[self.job_id]
        assert state.files_total == 100
        assert state.files_processed == 25
        assert state.current_file == "/path/to/file.mp4"

    def test_update_job_progress_partial(self) -> None:
        """Test partial progress update."""
        # First update
        update_job_progress(self.job_id, files_total=100)
        state = _JOB_STATES[self.job_id]
        assert state.files_total == 100

        # Partial update
        update_job_progress(self.job_id, files_processed=50)
        assert state.files_total == 100  # Should remain
        assert state.files_processed == 50

    def test_update_nonexistent_job(self) -> None:
        """Test updating progress for nonexistent job."""
        # Should not raise error
        update_job_progress(
            "nonexistent_job",
            files_total=100,
        )


class TestJobCancellation:
    """Tests for job cancellation functionality."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.job_id = "cancel_test_job"
        _JOB_STATES[self.job_id] = JobState(
            id=self.job_id,
            name_key="jobs.names.cancel_test",
            fallback_name="Cancel Test Job",
            status="running",
        )

    def teardown_method(self) -> None:
        """Clean up test fixtures."""
        if self.job_id in _JOB_STATES:
            del _JOB_STATES[self.job_id]

    def test_request_job_cancellation_running(self) -> None:
        """Test requesting cancellation of running job."""
        result = request_job_cancellation(self.job_id)

        assert result is True
        state = _JOB_STATES[self.job_id]
        assert state.cancellation_requested is True
        assert state.cancelled_at is not None

    def test_request_job_cancellation_not_running(self) -> None:
        """Test requesting cancellation of non-running job."""
        _JOB_STATES[self.job_id].status = "success"

        result = request_job_cancellation(self.job_id)

        assert result is False

    def test_request_job_cancellation_nonexistent(self) -> None:
        """Test requesting cancellation of nonexistent job."""
        result = request_job_cancellation("nonexistent_job")

        assert result is False

    def test_is_cancellation_requested_true(self) -> None:
        """Test checking cancellation request (true)."""
        _JOB_STATES[self.job_id].cancellation_requested = True

        result = is_cancellation_requested(self.job_id)

        assert result is True

    def test_is_cancellation_requested_false(self) -> None:
        """Test checking cancellation request (false)."""
        result = is_cancellation_requested(self.job_id)

        assert result is False

    def test_is_cancellation_requested_nonexistent(self) -> None:
        """Test checking cancellation for nonexistent job."""
        result = is_cancellation_requested("nonexistent_job")

        assert result is False

    def test_mark_job_cancelled(self) -> None:
        """Test marking job as cancelled."""
        mark_job_cancelled(self.job_id)

        state = _JOB_STATES[self.job_id]
        assert state.status == "cancelled"
        assert state.running_since is None
        assert state.cancellation_requested is False


class TestManualRun:
    """Tests for manual job run tracking."""

    def test_mark_manual_run_success(self) -> None:
        """Test marking a manual run as success."""
        job_id = "manual_test_job"

        state = mark_manual_run(job_id, "success")

        assert state.id == job_id
        assert state.status == "success"
        assert state.last_run_time is not None
        assert state.running_since is None

        # Clean up
        if job_id in _JOB_STATES:
            del _JOB_STATES[job_id]

    def test_mark_manual_run_failed(self) -> None:
        """Test marking a manual run as failed."""
        job_id = "manual_test_job_2"

        state = mark_manual_run(job_id, "failed")

        assert state.status == "failed"
        assert state.last_run_time is not None

        # Clean up
        if job_id in _JOB_STATES:
            del _JOB_STATES[job_id]


class TestJobHistory:
    """Tests for job execution history."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        # Clear history
        _JOB_EXECUTION_HISTORY.clear()

    def test_get_job_history_empty(self) -> None:
        """Test getting empty job history."""
        history = get_job_history()

        assert history == []

    def test_get_job_history_returns_reversed(self) -> None:
        """Test that job history is returned in reverse order (most recent first)."""
        # Add some records
        for i in range(3):
            record = JobExecutionRecord(
                job_id=f"job_{i}",
                job_name=f"Job {i}",
                job_type="scheduled",
                started_at=datetime.now(UTC),
            )
            _JOB_EXECUTION_HISTORY.append(record)

        history = get_job_history()

        # Most recent should be first
        assert history[0].job_id == "job_2"
        assert history[2].job_id == "job_0"


class TestGetJobState:
    """Tests for get_job_state function."""

    def test_get_job_state_existing(self) -> None:
        """Test getting existing job state."""
        job_id = "get_state_test"
        _JOB_STATES[job_id] = JobState(
            id=job_id,
            name_key="jobs.names.test",
            fallback_name="Test",
        )

        state = get_job_state(job_id)

        assert state is not None
        assert state.id == job_id

        # Clean up
        del _JOB_STATES[job_id]

    def test_get_job_state_nonexistent(self) -> None:
        """Test getting nonexistent job state."""
        state = get_job_state("nonexistent_job")

        assert state is None
