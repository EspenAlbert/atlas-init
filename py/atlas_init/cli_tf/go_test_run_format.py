from collections import Counter

from github.WorkflowJob import WorkflowJob
from zero_3rdparty import datetime_utils

from atlas_init.cli_tf.go_test_run import GoTestRun, GoTestStatus


def format_job(job: WorkflowJob) -> str:
    date = datetime_utils.date_filename(job.created_at)
    exec_time = "0s"
    if complete_ts := job.completed_at:
        exec_time = f"{(complete_ts - job.created_at).total_seconds()}s"
    return f"{date}_{job.workflow_name}_attempt{job.run_attempt}_ ({exec_time})"


def job_summary(runs: list[GoTestRun]) -> tuple[WorkflowJob, str]:
    status_counts: dict[GoTestStatus, int] = Counter()
    for run in runs:
        status_counts[run.status] += 1
    line = [f"{key}={status_counts[key]}" for key in sorted(status_counts.keys())]
    job = runs[0].job
    return job, f"{format_job(job)}:" + ",".join(line)


def fail_test_summary(runs: list[GoTestRun]) -> str:
    failed_runs = [r for r in runs if r.is_failure]
    failed_details: list[str] = [run.finish_summary() for run in failed_runs]
    return "\n".join(failed_details)
