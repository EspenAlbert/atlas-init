from __future__ import annotations

from functools import cached_property
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorCollection
from model_lib import Entity, dump, parse_model
from pydantic import model_validator
from zero_3rdparty.file_utils import ensure_parents_write_text

from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.cli_tf.go_test_tf_error import (
    GoTestError,
    GoTestErrorClass,
)
from atlas_init.crud.mongo_client import get_collection
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

    @model_validator(mode="after")
    def sort_errors(self) -> TFErrors:
        self.errors.sort()
        return self

    def look_for_existing_classifications(self, error: GoTestError) -> tuple[GoTestErrorClass, GoTestErrorClass] | None:
        for candidate in self.errors:
            if error.match(candidate) and (classifications := candidate.classifications):
                logger.info(f"found existing classification for {error.run.name}: {classifications}")
                return classifications

    def classified_errors(self) -> list[GoTestError]:
        return [error for error in self.errors if error.classifications is not None]


def read_tf_errors(settings: AtlasInitSettings) -> TFErrors:
    path = crud_dir(settings) / "tf_errors.yaml"
    return parse_model(path, TFErrors) if path.exists() else TFErrors()


def read_tf_errors_for_day(settings: AtlasInitSettings, branch: str, date: datetime) -> list[GoTestError]:
    raise NotImplementedError


def store_or_update_tf_errors(settings: AtlasInitSettings, errors: list[GoTestError]) -> None:
    existing = read_tf_errors(settings)
    new_error_ids = {error.run.id for error in errors}
    existing_without_new = [error for error in existing.errors if error.run.id not in new_error_ids]
    all_errors = existing_without_new + errors
    yaml_dump = dump(TFErrors(errors=all_errors), "yaml")
    ensure_parents_write_text(crud_dir(settings) / "tf_errors.yaml", yaml_dump)


def read_tf_error_by_run(settings: AtlasInitSettings, run: GoTestRun) -> GoTestError | None:
    errors = read_tf_errors(settings)
    return next((error for error in errors.errors if error.run.id == run.id), None)


class TFTestRuns(Entity):
    test_runs: list[GoTestRun] = field(default_factory=list)

    @model_validator(mode="after")
    def sort_test_runs(self) -> TFTestRuns:
        self.test_runs.sort()
        return self


def read_tf_test_runs(settings: AtlasInitSettings) -> list[GoTestRun]:
    path = crud_dir(settings) / "tf_test_runs.yaml"
    return parse_model(path, TFTestRuns).test_runs if path.exists() else []


def store_tf_test_runs(settings: AtlasInitSettings, test_runs: list[GoTestRun], *, overwrite: bool) -> list[GoTestRun]:
    existing = read_tf_test_runs(settings)
    new_ids = {run.id for run in test_runs}
    if overwrite:
        existing_without_new = [run for run in existing if run.id not in new_ids]
        all_runs = existing_without_new + test_runs
    else:
        existing_ids = {run.id for run in existing}
        new_only = [run for run in test_runs if run.id not in existing_ids]
        all_runs = existing + new_only
    path = crud_dir(settings) / "tf_test_runs.yaml"
    yaml_dump = dump(TFTestRuns(test_runs=all_runs), "yaml")
    ensure_parents_write_text(path, yaml_dump)
    return sorted([run for run in all_runs if run.id in new_ids])


def read_tf_tests_for_day(settings: AtlasInitSettings, branch: str, date: datetime) -> list[GoTestRun]:
    start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    return read_tf_tests(settings, branch, start_date, end_date)


def read_tf_tests(
    settings: AtlasInitSettings, branch: str, start_date: datetime, end_date: datetime | None = None
) -> list[GoTestRun]:
    raise NotImplementedError


@dataclass
class GoTestRunDao:
    settings: AtlasInitSettings

    @cached_property
    def collection(self) -> AsyncIOMotorCollection:
        return get_collection(GoTestRun)
