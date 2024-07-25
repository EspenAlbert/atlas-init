from pathlib import Path
from github.WorkflowJob import WorkflowJob


from unittest.mock import MagicMock

from github.WorkflowStep import WorkflowStep
import pytest


def as_step(name: str) -> WorkflowStep:
    step = MagicMock(spec=WorkflowStep)
    step.name = name
    return step


@pytest.fixture()
def mock_job() -> WorkflowJob:
    return MagicMock(
        spec=WorkflowJob,
        steps=[
            as_step(name="checkout"),
            as_step(name="setup-go"),
            as_step(name="setup-terraform"),
            as_step(name="Acceptance Tests"),
        ],
        html_url="https://github.com/mongodb/terraform-provider-mongodbatlas/actions/runs/9671377861/job/26681936440",
    )

@pytest.fixture()
def tf_test_data_dir() -> Path:
    return Path(__file__).parent / "test_data"