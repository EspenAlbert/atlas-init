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
    path = crud_dir(settings) / "tf_errors.yaml"
    return parse_model(path, TFErrors) if path.exists() else TFErrors()


def store_or_update_tf_errors(settings: AtlasInitSettings, errors: list[GoTestError]):
    existing = read_tf_errors(settings)
    new_error_ids = {error.run.id for error in errors}
    existing_without_new = [error for error in existing.errors if error.run.id not in new_error_ids]
    all_errors = existing_without_new + errors
    yaml_dump = dump(TFErrors(errors=all_errors), "yaml")
    ensure_parents_write_text(crud_dir(settings) / "tf_errors.yaml", yaml_dump)


def read_tf_test_runs(settings: AtlasInitSettings) -> list[GoTestRun]:
    path = crud_dir(settings) / "tf_test_runs.yaml"
    return parse_model(path, list[GoTestRun]) if path.exists() else []


def store_tf_test_runs(settings: AtlasInitSettings, test_runs: list[GoTestRun], *, overwrite: bool) -> list[GoTestRun]:
    existing = read_tf_test_runs(settings)
    new_ids = {run.id for run in test_runs}
    existing_without_new = [run for run in existing if run.id not in new_ids]
    path = crud_dir(settings) / "tf_test_runs.yaml"
    all_runs = existing_without_new + test_runs
    yaml_dump = dump(all_runs, "yaml")
    ensure_parents_write_text(path, yaml_dump)


def read_tf_error_by_run(settings: AtlasInitSettings, run: GoTestRun) -> GoTestError | None:
    errors = read_tf_errors(settings)
    return next((error for error in errors.errors if error.run.id == run.id), None)
