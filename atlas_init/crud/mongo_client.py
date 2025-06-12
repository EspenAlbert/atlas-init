from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import TypeAlias

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from pymongo import IndexModel
from pymongo.errors import DuplicateKeyError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.cli_tf.go_test_tf_error import GoTestError, GoTestErrorClassification


logger = logging.getLogger(__name__)


@dataclass
class CollectionConfig:
    name: str = ""  # uses the class name by default
    indexes: list[IndexModel] = field(default_factory=list)


CollectionConfigsT: TypeAlias = dict[type, CollectionConfig]


def default_document_models() -> CollectionConfigsT:
    return {
        GoTestErrorClassification: CollectionConfig(),
        GoTestError: CollectionConfig(),
        GoTestRun: CollectionConfig(),
    }


_collections = {}


def get_collection(model: type) -> AsyncIOMotorCollection:
    col = _collections.get(model)
    if col is not None:
        return col
    raise ValueError(f"Collection for model {model.__name__} is not initialized. Call init_mongo first.")


def get_db(mongo_url: str, db_name: str) -> AsyncIOMotorDatabase:
    client = AsyncIOMotorClient(mongo_url)
    return client.get_database(db_name)


async def init_mongo(
    mongo_url: str, db_name: str, clean_collections: bool = False, document_models: CollectionConfigsT | None = None
) -> None:
    db: AsyncIOMotorDatabase = get_db(mongo_url, db_name)
    document_models = document_models or default_document_models()
    for t, config in document_models.items():
        name = config.name or t.__name__
        col = await ensure_collection_exist(db, name, config.indexes, clean_collection=clean_collections)
        _collections[t] = col
    if clean_collections:
        await _empty_collections()
        logger.info(f"MongoDB collections in database '{db_name}' have been cleaned.")


async def ensure_collection_exist(
    db: AsyncIOMotorDatabase,
    name: str,
    indexes: list[IndexModel] | None = None,
    clean_collection: bool = False,
) -> AsyncIOMotorCollection:
    try:
        collection = await db.create_collection(name)
    except Exception as e:
        if "already exists" not in str(e):
            raise e
        collection = db[name]
        if clean_collection:
            await collection.drop()
        collection = db[name]
    else:
        if indexes:
            await collection.create_indexes(indexes)
    logger.info(f"mongo collection {name} is ready")
    return collection


def duplicate_key_pattern(error: DuplicateKeyError) -> str | None:
    details: dict = error.details  # type: ignore
    name_violator = details.get("keyPattern", {})
    if not name_violator:
        return None
    name, _ = name_violator.popitem()
    return name


class CollectionNotEmptyError(Exception):
    def __init__(self, collection_name: str):
        super().__init__(f"Collection '{collection_name}' is not empty.")
        self.collection_name = collection_name


@retry(
    stop=stop_after_attempt(10),
    wait=wait_fixed(0.5),
    retry=retry_if_exception_type(CollectionNotEmptyError),
    reraise=True,
)
async def _empty_collections() -> None:
    col: AsyncIOMotorCollection
    for col in _collections.values():
        count = await col.count_documents({})
        if count > 0:
            raise CollectionNotEmptyError(col.name)
