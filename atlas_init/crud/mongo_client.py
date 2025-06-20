from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import TypeAlias

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from pymongo import IndexModel
from pymongo.errors import DuplicateKeyError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.cli_tf.go_test_tf_error import GoTestErrorClassification
from atlas_init.crud.mongo_utils import index_dec


logger = logging.getLogger(__name__)


@dataclass
class CollectionConfig:
    name: str = ""  # uses the class name by default
    indexes: list[IndexModel] = field(default_factory=list)


CollectionConfigsT: TypeAlias = dict[type, CollectionConfig]


def default_document_models() -> CollectionConfigsT:
    return {
        GoTestErrorClassification: CollectionConfig(
            indexes=[index_dec("ts"), IndexModel(["error_class"]), IndexModel(["test_name"])]
        ),
        GoTestRun: CollectionConfig(indexes=[index_dec("ts"), IndexModel(["branch"]), IndexModel(["status"])]),
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
    db = get_db(mongo_url, db_name)
    document_models = document_models or default_document_models()
    for model, cfg in document_models.items():
        name = cfg.name or model.__name__
        col = await ensure_collection_exist(db, name, cfg.indexes, clean_collections)
        _collections[model] = col

    if clean_collections:
        logger.info(f"MongoDB collections in '{db_name}' have been cleaned.")


async def ensure_collection_exist(
    db: AsyncIOMotorDatabase,
    name: str,
    indexes: list[IndexModel] | None = None,
    clean_collection: bool = False,
) -> AsyncIOMotorCollection:
    existing = await db.list_collection_names()
    if clean_collection and name in existing:
        await db.drop_collection(name)
        existing.remove(name)

    if name not in existing:
        await db.create_collection(name)

    if indexes:
        # always (re-)create indexes after new creation or drop
        await db[name].create_indexes(indexes)

    logger.debug(f"mongo collection {name!r} is ready")
    return db[name]


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
