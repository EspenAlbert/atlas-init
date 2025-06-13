import asyncio
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

import pytest
import pytest_asyncio
from model_lib import parse_model
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from zero_3rdparty.datetime_utils import date_filename_with_seconds, utc_now

from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.cli_tf.go_test_tf_error import (
    CheckError,
    ErrorDetailsT,
    GoTestAPIError,
    GoTestDefaultError,
    GoTestErrorClass,
    GoTestErrorClassification,
    ErrorClassAuthor,
    GoTestResourceCheckError,
)
from atlas_init.crud.mongo_client import CollectionConfig, get_collection, init_mongo
from atlas_init.crud.mongo_utils import create_or_replace, dump_with_id
from atlas_init.crud.mongo_dao import MongoDao

logger = logging.getLogger(__name__)


class MyModel(BaseModel):
    name: str
    value: int


class MongoInfo(NamedTuple):
    mongo_url: str
    mongo_database: str


@pytest.fixture(scope="session", autouse=True)
@pytest.mark.skipif(os.environ.get("MONGO_URL", "") == "", reason="needs os.environ[MONGO_URL]")
def cleanup_databases(request):
    yield
    client = AsyncIOMotorClient(os.environ.get("MONGO_URL", ""))

    async def drop_databases():
        dbs = await client.list_database_names()
        for db_name in dbs:
            if db_name.startswith("pytest-"):
                logger.info(f"Cleaning up database: {db_name}")
                await client.drop_database(db_name)

    session = request.session
    skip_cleanup = getattr(session, "testsfailed", 0) > 0
    skip_cleanup = skip_cleanup or os.environ.get("SKIP_MONGODB_CLEANUP", "") in {"1", "true", "yes"}
    if skip_cleanup:
        logger.warning("Skipping MongoDB cleanup due to test failures or environment variable.")
        return
    asyncio.run(drop_databases())


@pytest.fixture()
def db_name_test(request) -> str:
    func_name = request.function.__name__
    return f"pytest-{func_name}-{date_filename_with_seconds()}"


@pytest_asyncio.fixture
@pytest.mark.skipif(os.environ.get("MONGO_URL", "") == "", reason="needs os.environ[MONGO_URL]")
async def mongo_dao(settings, db_name_test) -> MongoDao:
    settings.mongo_database = db_name_test
    logger.info(f"mongo url: {settings.mongo_url} db: {settings.mongo_database}")
    return await MongoDao(settings=settings).connect()


_example_logs = """\
2025-06-05T00:30:13.8309411Z === RUN   TestAccProjectAPI_basic
2025-06-05T00:30:13.8310388Z === CONT  TestAccProjectAPI_basic
2025-06-05T00:30:13.8319161Z     resource_test.go:22: Step 1/3 error: Check failed: Check 4/4 error: project(6840e511161ca93c1f053d1a) does not exist
2025-06-05T00:30:13.8320050Z --- FAIL: TestAccProjectAPI_basic (3.15s)"""


def _dummy_log_path(group_name: str) -> Path:
    return Path(f"40216340925_tests-1.11.x-latest_tests-1.11.x-latest-false_{group_name}.txt")


def dummy_run(
    logs_str: str, name: str, ts: datetime | None = None, branch: str | None = None, group_name: str | None = None
):
    ts = ts or utc_now()
    run = GoTestRun(name=name, output_lines=logs_str.splitlines(), ts=ts)
    run.branch = branch or "test_branch"
    if group_name:
        run.log_path = _dummy_log_path(group_name)
    return run


def dummy_classification(
    run_id: str,
    error_class: GoTestErrorClass = GoTestErrorClass.UNCLASSIFIED,
    ts: datetime | None = None,
    logs_str: str = _example_logs,
    details: ErrorDetailsT | None = None,
    test_name: str = "TestAccExample",
) -> GoTestErrorClassification:
    ts = ts or utc_now()
    details = details or GoTestDefaultError(error_str=logs_str)
    return GoTestErrorClassification(
        author=ErrorClassAuthor.AUTO,
        error_class=error_class,
        ts=ts,
        run_id=run_id,
        test_output=logs_str,
        details=details,
        test_name=test_name,
    )


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("MONGO_URL", "") == "", reason="needs os.environ[MONGO_URL]")
async def test_init_mongo2(db_name_test):
    url = os.environ["MONGO_URL"]
    db = db_name_test
    logger.info(f"(test) mongo url: {url} db: {db}")
    await init_mongo(
        mongo_url=url,
        db_name=db,
        document_models={MyModel: CollectionConfig()},
    )
    col = get_collection(MyModel)
    assert col.name == MyModel.__name__
    assert await col.count_documents({}) == 0
    model = MyModel(name="test", value=42)
    instance = dump_with_id(model, id="test_id")
    assert instance["_id"] == "test_id"
    is_new = await create_or_replace(col, instance)
    assert is_new
    is_new2 = await create_or_replace(col, instance)
    assert not is_new2
    raw = await col.find_one({"_id": "test_id"})
    assert raw is not None
    assert parse_model(raw, t=MyModel) == model
    assert await col.count_documents({}) == 1
    logger.info("Test completed successfully")


@pytest.mark.asyncio()
async def test_classification_crud(mongo_dao, subtests):
    now = utc_now()
    now_plus1 = now + timedelta(seconds=1)
    c1_id = "r1"
    c1 = dummy_classification(c1_id, ts=now)
    c2_id = "r2"
    c2 = dummy_classification(c2_id, ts=now_plus1)
    with subtests.test("create"):
        assert await mongo_dao.add_classification(c1)
        assert await mongo_dao.add_classification(c2)
    with subtests.test("list"):
        ids = [c1_id, c2_id]
        # list_result = await mongo_dao.read_error_classifications(run_ids=ids)
        list_result = await mongo_dao.read_error_classifications(run_ids=ids)
        assert len(list_result) == 2
        assert set(ids) == set(list_result)
    with subtests.test("read"):
        read_c1 = await mongo_dao.read_error_classifications(run_ids=[c1_id])
        assert len(read_c1) == 1
        assert c1_id in read_c1


@pytest.mark.asyncio()
async def test_classification_read_similar(mongo_dao: MongoDao, subtests):
    api_error_details = GoTestAPIError(
        type="api_error",
        api_error_code_str="UNEXPECTED_ERROR",
        api_path="/api/atlas/v2/groups/680ecbbe1ad7050ec5b1ebe3/backupCompliancePolicy",
        api_method="DELETE",
        api_response_code=500,
        tf_resource_name="",
        tf_resource_type="",
        step_nr=-1,
    )
    api_error_details.api_path_normalized = api_error_details.api_path.replace("680ecbbe1ad7050ec5b1ebe3", "groupId")
    c1_api = dummy_classification("r1")
    c1_api.details = api_error_details
    c2_check_details = dummy_classification("r2")
    check_details = GoTestResourceCheckError(
        type="check_error",
        tf_resource_name="tenant",
        tf_resource_type="cluster",
        step_nr=2,
        check_errors=[CheckError(attribute="", expected="", got="", check_nr=4)],
        test_name=c2_check_details.test_name,
    )
    c2_check_details.details = check_details
    await mongo_dao.add_classification(c1_api)
    await mongo_dao.add_classification(c2_check_details)
    with subtests.test("read similar error classification API error"):
        similars1 = await mongo_dao.read_similar_error_classifications(details=api_error_details)
        assert len(similars1) == 1
        _, c1_found = similars1.popitem()
        assert c1_api == c1_found
    with subtests.test("read similar check details"):
        similars2 = await mongo_dao.read_similar_error_classifications(check_details)
        assert len(similars2) == 1
        _, c2_found = similars2.popitem()
        assert c2_check_details == c2_found


@pytest.mark.asyncio()
async def test_runs(mongo_dao: MongoDao, subtests):
    now = utc_now()
    now_plus1 = now + timedelta(seconds=1)
    r1 = dummy_run("test run 1", name="test_run_1", ts=now)
    r2 = dummy_run("test run 2", name="test_run_2", ts=now_plus1)
    with subtests.test("create"):
        runs = await mongo_dao.store_tf_test_runs([r1, r2])
        assert len(runs) == 2
    with subtests.test("read for day"):
        branch = r1.branch
        assert branch
        runs = await mongo_dao.read_tf_tests_for_day(branch=branch, date=now)
        assert len(runs) == 2
    with subtests.test("read single"):
        r1_back = await mongo_dao.read_tf_test_run(r1.id)
        assert r1_back == r1
        r2_back = await mongo_dao.read_tf_test_run(r2.id)
        assert r2_back == r2


@pytest.mark.asyncio()
async def test_read_run_history(mongo_dao: MongoDao, subtests):
    start = utc_now()
    start_plus1 = start + timedelta(days=1)
    start_plus2 = start + timedelta(days=2)
    test_name = "test_run_history"
    r1 = dummy_run("test run 1", name=test_name, ts=start, branch="b1")
    r2 = dummy_run("test run 2", name=test_name, ts=start_plus1, branch="b2", group_name="test_group")
    r3 = dummy_run("test run 3", name=test_name, ts=start_plus2, branch="b3")
    with subtests.test("create runs"):
        runs = await mongo_dao.store_tf_test_runs([r1, r2, r3])
        assert len(runs) == 3
    with subtests.test("read history for test name"):
        history = await mongo_dao.read_run_history(test_name=test_name)
        assert len(history) == 3
    with subtests.test("read history for test name with date range"):
        history = await mongo_dao.read_run_history(test_name=test_name, start_date=start, end_date=start_plus1)
        assert len(history) == 2
        assert {run.id for run in history} == {r1.id, r2.id}
    with subtests.test("read history for test name with branch"):
        history = await mongo_dao.read_run_history(test_name=test_name, branches=["b1", "b3"])
        assert len(history) == 2
        assert {run.id for run in history} == {r1.id, r3.id}
    with subtests.test("read history for a group_name"):
        history = await mongo_dao.read_run_history(test_name=test_name, group_name="test_group")
        assert len(history) == 1
        assert history[0].id == r2.id
