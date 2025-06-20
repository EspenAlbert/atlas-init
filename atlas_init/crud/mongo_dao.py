from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import ClassVar, Self

from model_lib import Entity, dump, field_names, parse_model
from motor.motor_asyncio import AsyncIOMotorCollection
from pydantic import model_validator
from zero_3rdparty.file_utils import ensure_parents_write_text
from zero_3rdparty.iter_utils import ignore_falsy

from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.cli_tf.go_test_tf_error import (
    ErrorClassAuthor,
    ErrorDetailsT,
    GoTestAPIError,
    GoTestError,
    GoTestErrorClass,
    GoTestErrorClassification,
    GoTestResourceCheckError,
)
from atlas_init.crud.mongo_client import get_collection, init_mongo
from atlas_init.crud.mongo_utils import MongoQueryOperation, create_or_replace, dump_with_id
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


def read_tf_tests_for_day(settings: AtlasInitSettings, branch: str, date: datetime) -> list[GoTestRun]:
    start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    return read_tf_tests(settings, branch, start_date, end_date)


def read_tf_tests(
    settings: AtlasInitSettings, branch: str, start_date: datetime, end_date: datetime | None = None
) -> list[GoTestRun]:
    raise NotImplementedError


async def init_mongo_dao(settings: AtlasInitSettings) -> MongoDao:
    dao = MongoDao(settings=settings)
    return await dao.connect()


class GoTestRunNotFound(Exception):
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(run_id)


@dataclass
class MongoDao:
    settings: AtlasInitSettings
    property_keys_run: ClassVar[list[str]] = ["group_name"]

    @cached_property
    def runs(self) -> AsyncIOMotorCollection:
        return get_collection(GoTestRun)

    @cached_property
    def classifications(self) -> AsyncIOMotorCollection:
        return get_collection(GoTestErrorClassification)

    @cached_property
    def _field_names_runs(self) -> set[str]:
        return set(field_names(GoTestRun)) | set(self.property_keys_run)

    async def connect(self) -> Self:
        await init_mongo(
            mongo_url=self.settings.mongo_url,
            db_name=self.settings.mongo_database,
        )
        return self

    async def store_tf_test_runs(self, test_runs: list[GoTestRun]) -> list[GoTestRun]:
        if not test_runs:
            return []
        col = self.runs
        tasks = []
        loop = asyncio.get_event_loop()
        for run in test_runs:
            dumped = dump_with_id(run, id=run.id, dt_keys=["ts", "finish_ts"], property_keys=self.property_keys_run)
            tasks.append(loop.create_task(create_or_replace(col, dumped)))
        await asyncio.gather(*tasks)
        return test_runs

    async def read_tf_tests_for_day(self, branch: str, date: datetime) -> list[GoTestRun]:
        start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        query = {
            "branch": branch,
            "ts": {MongoQueryOperation.gte: start_date, MongoQueryOperation.lte: end_date},
        }
        return await self._find_runs(query)

    async def _find_runs(self, query: dict) -> list[GoTestRun]:
        runs = []
        async for raw_run in self.runs.find(query):
            runs.append(self._parse_run(raw_run))
        return runs

    async def read_error_classifications(
        self, run_ids: list[str] | None = None
    ) -> dict[str, GoTestErrorClassification]:
        run_ids = run_ids or []
        if not run_ids:
            return {}
        query = {"_id": {MongoQueryOperation.in_: run_ids}}
        return await self._find_classifications(query)

    async def _find_classifications(self, query: dict) -> dict[str, GoTestErrorClassification]:
        classifications: dict[str, GoTestErrorClassification] = {}
        async for raw_error in self.classifications.find(query):
            run_id = raw_error.pop("_id", None)
            classification = parse_model(raw_error, t=GoTestErrorClassification)
            classifications[run_id] = classification
        return classifications

    async def read_similar_error_classifications(
        self, details: ErrorDetailsT, *, author_filter: ErrorClassAuthor | None = None
    ) -> dict[str, GoTestErrorClassification]:
        query = {}
        if author_filter:
            query["author"] = {MongoQueryOperation.eq: author_filter}
        match details:
            case GoTestAPIError(
                api_error_code_str=api_error_code_str,
                api_method=api_method,
                api_response_code=api_response_code,
                api_path_normalized=api_path_normalized,
            ) if api_path_normalized:
                query |= {
                    "details.api_error_code_str": {MongoQueryOperation.eq: api_error_code_str},
                    "details.api_method": {MongoQueryOperation.eq: api_method},
                    "details.api_response_code": {MongoQueryOperation.eq: api_response_code},
                    "details.api_path_normalized": {MongoQueryOperation.eq: api_path_normalized},
                }
            case GoTestResourceCheckError(
                tf_resource_name=tf_resource_name,
                tf_resource_type=tf_resource_type,
                step_nr=step_nr,
                check_errors=check_errors,
                test_name=test_name,
            ):
                query |= {
                    "details.tf_resource_name": {MongoQueryOperation.eq: tf_resource_name},
                    "details.tf_resource_type": {MongoQueryOperation.eq: tf_resource_type},
                    "details.step_nr": {MongoQueryOperation.eq: step_nr},
                    "test_name": {MongoQueryOperation.eq: test_name},
                }
                classifications = await self._find_classifications(query)
                return {
                    run_id: classification
                    for run_id, classification in classifications.items()
                    if isinstance(classification.details, GoTestResourceCheckError)
                    and classification.details.check_errors_match(check_errors)
                }
            case _:
                return {}  # todo: vector search to match on error output
        return await self._find_classifications(query)

    async def add_classification(self, classification: GoTestErrorClassification) -> bool:
        """Returns is_new"""
        raw = dump_with_id(classification, id=classification.run_id, dt_keys=["ts"])
        return await create_or_replace(self.classifications, raw)

    async def read_tf_test_run(self, run_id: str) -> GoTestRun:
        raw = await self.runs.find_one({"_id": run_id})
        if raw is None:
            raise GoTestRunNotFound(run_id)
        return self._parse_run(raw)

    def _parse_run(self, raw: dict) -> GoTestRun:
        raw.pop("_id")
        for key in self.property_keys_run:
            raw.pop(key, None)  # Remove properties that are not part of the model
        return parse_model(raw, t=GoTestRun)

    async def read_run_history(
        self,
        test_name: str,
        branches: list[str] | None = None,
        package_url: str | None = None,
        group_name: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        envs: list[str] | None = None,
    ) -> list[GoTestRun]:
        eq = MongoQueryOperation.eq
        query = {
            "name": {eq: test_name},
        }
        eq_parts = {
            "package_url": {eq: package_url} if package_url else None,
            "group_name": {eq: group_name} if group_name else None,
        }
        in_op = MongoQueryOperation.in_
        in_parts = {
            "branch": {in_op: branches} if branches else None,
            "env": {in_op: envs} if envs else None,
        }
        date_parts = {
            "ts": ignore_falsy(
                **{
                    MongoQueryOperation.lte: end_date or None,
                    MongoQueryOperation.gte: start_date or None,
                }
            )
        }
        query |= ignore_falsy(**eq_parts, **in_parts, **date_parts)
        if invalid_fields := set(query) - self._field_names_runs:
            raise ValueError(f"Invalid fields in query: {invalid_fields}")
        return await self._find_runs(query)
