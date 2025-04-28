import logging
from dataclasses import dataclass, field
from pathlib import Path

from model_lib import Entity, dump, parse_model
from zero_3rdparty.file_utils import ensure_parents_write_text

from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.cli_tf.go_test_tf_error import (
    GoTestError,
    GoTestErrorClass,
)
from atlas_init.repos.path import TFResoure, terraform_resources
from atlas_init.settings.env_vars import AtlasInitSettings

logger = logging.getLogger(__name__)


def crud_dir(settings: AtlasInitSettings) -> Path:
    return settings.static_root / "crud"


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


class TFErrors(Entity):
    errors: list[GoTestError] = field(default_factory=list)

    def look_for_existing_classifications(self, error: GoTestError) -> tuple[GoTestErrorClass, GoTestErrorClass] | None:
        for candidate in self.errors:
            if error.match(candidate):
                return candidate.classifications

    def classified_errors(self) -> list[GoTestError]:
        return [error for error in self.errors if error.human_error_class is not None]


def read_tf_errors(settings: AtlasInitSettings) -> TFErrors:
    return parse_model(crud_dir(settings) / "tf_errors.yaml", TFErrors)


def store_or_update_tf_errors(settings: AtlasInitSettings, errors: list[GoTestError]):
    yaml_dump = dump(TFErrors(errors=errors), "yaml")
    ensure_parents_write_text(crud_dir(settings) / "tf_errors.yaml", yaml_dump)
