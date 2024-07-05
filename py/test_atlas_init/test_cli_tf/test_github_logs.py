from datetime import timedelta
import os
from pathlib import Path
import pytest
from zero_3rdparty.datetime_utils import utc_now
from atlas_init.cli_tf.github_logs import (
    GH_TOKEN_ENV_NAME,
    REQUIRED_GH_ENV_VARS,
    download_workflow_logs,
    print_log_failures,
    select_step_and_log_content,
    tf_repo,
)
from github.WorkflowJob import WorkflowJob
from atlas_init.cli_tf.github_logs import is_test_job
from test_atlas_init.test_cli_tf.conftest import mock_job


skip_condition = pytest.mark.skipif(
    any(os.environ.get(name, "") == "" for name in REQUIRED_GH_ENV_VARS),
    reason=f"needs env vars: {REQUIRED_GH_ENV_VARS}",
)


@skip_condition
def test_print_log_failures():
    print_log_failures(utc_now() - timedelta(days=10), max_downloads=5)


@skip_condition
def test_download_logs_single():
    repo = tf_repo()
    workflow = repo.get_workflow_run(9671377861)
    download_workflow_logs(workflow)


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
