import logging
from dataclasses import dataclass, field
from pathlib import Path

from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.cli_tf.go_test_tf_error import ErrorDetails, GoTestError, GoTestErrorClass
from atlas_init.repos.path import TFResoure, terraform_resources
from atlas_init.settings.env_vars import AtlasInitSettings


logger = logging.getLogger(__name__)


@dataclass
class TFResources:
    resources: list[TFResoure] = field(default_factory=list)

    def find_test_resources(self, test: GoTestRun) -> list[str]:
        found_resources = []
        for resource in self.resources:
            url = test.package_url
            if url and url.endswith(resource.package_rel_path):
                found_resources.append(resource.name)
        return found_resources


def read_tf_resources(settings: AtlasInitSettings, repo_path: Path, branch: str) -> TFResources:
    return TFResources(resources=terraform_resources(repo_path))


def store_resource_tests(settings: AtlasInitSettings, tests: list[GoTestRun]):
    logger.warning(store_resource_tests.__name__ + " not supported yet")


@dataclass
class TFErrors:
    errors: list[GoTestError] = field(default_factory=list)

    def find_existing(self, details: ErrorDetails, test: GoTestRun) -> GoTestError | None:
        return None

    def classify(self, details: ErrorDetails, test: GoTestRun) -> GoTestErrorClass:
        return GoTestErrorClass.UNKNOWN


def read_tf_errors(settings: AtlasInitSettings, branch: str) -> TFErrors:
    logger.warning("error store not supported yet")
    return TFErrors()


def add_tf_error(test: GoTestRun, error: GoTestError):
    logger.warning(f"adding error to test {test.name}: {error}")


def increase_tf_error_count(test: GoTestRun, error: GoTestError):
    logger.warning(f"increasing error count for test {test.name}: {error}")
