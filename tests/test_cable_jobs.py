from dataclasses import replace

from assembly_recovery.cable_jobs import CableJob, CableJobLimits, CableSample


def sample(t, **kwargs):
    base = CableSample(t, 0.1, 0, 0, 0, 0, 1, 1, 1, 0, 0, True, True, True)
    return replace(base, **kwargs)


def test_force_abort_overrides_simultaneous_dwell():
    job = CableJob(CableJobLimits(dwell_s=0.1))
    assert job.update(sample(0.1, wrist_force_n=21)) == "failed"
    assert job.failure_reason == "force_abort"


def test_seating_requires_continuous_physical_engagement():
    job = CableJob(CableJobLimits(dwell_s=0.2))
    job.update(sample(0.1))
    job.update(sample(0.2, engagement_valid=False))
    assert job.update(sample(0.3)) == "active"
    assert job.update(sample(0.4)) == "completed"


def test_posthoc_seating_cannot_rescue_clip_loss():
    job = CableJob()
    job.update(sample(0.1, clip_retained=False))
    assert job.update(sample(0.2)) == "failed"
    assert job.failure_reason == "lost_required_clip"


def test_missing_native_samples_fail_closed():
    job = CableJob()
    assert job.update(sample(0.2)) == "failed"
    assert job.failure_reason == "missing_or_repeated_native_sample"


def test_free_space_failure_is_not_contact_recovery():
    job = CableJob()
    for i in range(1, 9):
        job.update(sample(i * 0.1, engagement_valid=False, seating_error_m=0.01, commanded_depth_m=i * 0.001))
    assert job.first_witness_s is None


def test_stall_requires_command_without_new_depth_and_contact():
    job = CableJob()
    for i in range(1, 9):
        job.update(
            sample(
                i * 0.1,
                engagement_valid=False,
                seating_error_m=0.01,
                commanded_depth_m=i * 0.001,
                connector_contact_n=1,
            )
        )
    assert job.first_witness_s is not None
    assert job.witness_type == "connector_contact_stall"


def test_progress_prevents_false_stall_even_with_contact():
    job = CableJob()
    for i in range(1, 9):
        job.update(
            sample(
                i * 0.1,
                engagement_valid=False,
                seating_error_m=0.01,
                commanded_depth_m=i * 0.001,
                insertion_depth_m=i * 0.0005,
                connector_contact_n=1,
            )
        )
    assert job.first_witness_s is None


def test_pose_write_ends_job():
    job = CableJob()
    job.update(sample(0.1, forbidden_events=1))
    assert job.failure_reason == "forbidden_state_change"
