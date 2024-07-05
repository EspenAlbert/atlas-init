from datetime import timedelta
import os
from pathlib import Path
from textwrap import indent
import pytest
from zero_3rdparty.datetime_utils import utc_now
from atlas_init.cli_tf.github_logs import (
    REQUIRED_GH_ENV_VARS,
    find_test_runs,
    include_test_jobs,
    select_step_and_log_content,
    tf_repo,
)
from atlas_init.cli_tf.github_logs import is_test_job
from atlas_init.cli_tf.go_test_run_format import fail_test_summary, job_summary
from test_atlas_init.test_cli_tf.conftest import mock_job


skip_condition = pytest.mark.skipif(
    any(os.environ.get(name, "") == "" for name in REQUIRED_GH_ENV_VARS),
    reason=f"needs env vars: {REQUIRED_GH_ENV_VARS}",
)


@skip_condition
def test_find_test_failures():
    job_runs = find_test_runs(
        utc_now() - timedelta(days=8),
        include_job=include_test_jobs("cluster_outage_simulation"),
    )
    for job_id in sorted(job_runs.keys(), reverse=True):
        runs = job_runs[job_id]
        summary = job_summary(runs)
        print(summary)
        if fail_summary := fail_test_summary(runs):
            print(indent(fail_summary, "  "))

    assert job_runs


def test_include_test_jobs():
    job = mock_job()
    job.name = "tests-1.8.x-latest / tests-1.8.x-latest-dev / cluster_outage_simulation"  # type: ignore
    assert include_test_jobs("cluster_outage_simulation")(job)
    job.name = "tests-1.8.x-latest / tests-1.8.x-latest-dev / cluster"  # type: ignore
    assert not include_test_jobs("cluster_outage_simulation")(job)


@skip_condition
def test_workflow_with_multiple_runs():
    workflow_id = 9671377861
    repo = tf_repo()
    workflow = repo.get_workflow_run(workflow_id)
    paginated_jobs = workflow.jobs("all")
    print(f"total count: {paginated_jobs.totalCount}")
    for job in paginated_jobs:
        if not is_test_job(job.name):
            print(
                f"non test job: {job.name}, attempt {job.run_attempt}, {job.created_at}"
            )
            continue
        print(
            f"found test job: {job.name}, attempt {job.run_attempt}, {job.created_at}, url: {job.html_url}"
        )


def test_is_test_job():
    assert is_test_job("tests-1.8.x-latest / tests-1.8.x-latest-dev / config")
    assert not is_test_job(
        "tests-1.8.x-latest / tests-1.8.x-latest-dev / get-provider-version"
    )
    assert not is_test_job("clean-after / cleanup-test-env-general")
    assert not is_test_job("clean-before / cleanup-test-env-qa")


@pytest.mark.skipif(
    os.environ.get("JOB_LOGS_PATH", "") == "", reason="needs os.environ[JOB_LOGS_PATH]"
)
def test_select_step_and_log_content():
    # https://github.com/mongodb/terraform-provider-mongodbatlas/actions/runs/9671377861/job/26687675666#step:5:66
    job_logs_path = Path(os.environ["JOB_LOGS_PATH"])
    step, content = select_step_and_log_content(mock_job(), job_logs_path)
    assert step == 4
    assert "##[group]Run make testacc" in content[0]
