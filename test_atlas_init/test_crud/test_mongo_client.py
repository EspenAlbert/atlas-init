import logging
import os
from typing import NamedTuple
from model_lib import parse_model
from pydantic import BaseModel
import pytest
import pytest_asyncio
from zero_3rdparty.datetime_utils import date_filename_with_seconds, utc_now

from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.crud.mongo_client import CollectionConfig, get_collection, init_mongo
from atlas_init.crud.mongo_utils import create_or_replace, dump_with_id

logger = logging.getLogger(__name__)


class MyModel(BaseModel):
    name: str
    value: int


class MongoInfo(NamedTuple):
    mongo_url: str
    mongo_database: str


@pytest_asyncio.fixture
async def clean_mongo(settings, request) -> MongoInfo:
    func_name = request.function.__name__
    settings.mongo_database = f"pytest-{func_name}-{date_filename_with_seconds()}"
    logger.info(f"mongo url: {settings.mongo_url} db: {settings.mongo_database}")
    await init_mongo(settings.mongo_url, db_name=settings.mongo_database)
    return MongoInfo(settings.mongo_url, settings.mongo_database)


_example_logs = """\
2025-06-05T00:30:13.8309411Z === RUN   TestAccProjectAPI_basic
2025-06-05T00:30:13.8310388Z === CONT  TestAccProjectAPI_basic
2025-06-05T00:30:13.8319161Z     resource_test.go:22: Step 1/3 error: Check failed: Check 4/4 error: project(6840e511161ca93c1f053d1a) does not exist
2025-06-05T00:30:13.8320050Z --- FAIL: TestAccProjectAPI_basic (3.15s)"""


def dummy_run(logs_str: str, name: str):
    return GoTestRun(name=name, output_lines=logs_str.splitlines(), ts=utc_now())


@pytest.mark.skipif(os.environ.get("MONGO_URL", "") == "", reason="needs os.environ[MONGO_URL]")
@pytest.mark.asyncio
async def test_init_mongo2(clean_mongo):
    url, db = clean_mongo
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
