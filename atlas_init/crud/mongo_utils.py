import logging
import re
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Any, AsyncIterable, Iterable, List, Optional, Type, TypeVar

from model_lib import dump_as_dict
from motor.core import AgnosticCollection
from pydantic import BaseModel
from pymongo import ASCENDING, DESCENDING, IndexModel, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.results import DeleteResult
from zero_3rdparty.enum_utils import StrEnum

logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


class MongoUpdateOperation(StrEnum):
    """
    References:
        https://docs.mongodb.com/manual/reference/operator/update-array/
    """

    slice = "$slice"
    pop = "$pop"
    pull = "$pull"
    unset = "$unset"
    push = "$push"
    each = "$each"
    set = "$set"
    set_on_insert = "$setOnInsert"
    inc = "$inc"


UPDATE_OPERATIONS = set(MongoUpdateOperation)


def ensure_mongo_operation(updates: dict):
    """
    >>> ensure_mongo_operation({"field1": 2})
    {'$set': {'field1': 2}}
    >>> ensure_mongo_operation({MongoUpdateOperation.set: {"field1": 2}})
    {'$set': {'field1': 2}}
    >>> ensure_mongo_operation({MongoUpdateOperation.push: {"field1": 2}})
    {'$push': {'field1': 2}}
    """
    if updates.keys() - UPDATE_OPERATIONS == set():
        return updates
    return {MongoUpdateOperation.set: updates}


class MongoQueryOperation(StrEnum):
    # must be used when checking if a boolean field is false
    eq = "$eq"
    # https://stackoverflow.com/questions/18837486/query-for-boolean-field-as-not-true-e-g-either-false-or-non-existent
    ne = "$ne"
    in_ = "$in"
    # https://www.mongodb.com/docs/manual/reference/operator/query/nin/#mongodb-query-op.-nin
    nin = "$nin"
    gt = "$gt"
    gte = "$gte"
    lt = "$lt"
    lte = "$lte"
    slice = "$slice"

    @classmethod
    def boolean_or_none(cls, bool_value: bool | None) -> dict | None:
        if bool_value is None:
            return None
        return {cls.eq: True} if bool_value else {cls.ne: True}

    @classmethod
    def in_or_none(cls, options: Iterable[Any] | None) -> dict | None:
        return None if options is None else {cls.in_: list(options)}

    @classmethod
    def nin_or_none(cls, options: Iterable[Any] | None) -> dict | None:
        return None if options is None else {cls.nin: list(options)}


duplicate_key_regex = re.compile(
    r".*error collection:"
    r"\s(?P<collection_path>[-\w\d\\.]+)"
    r"\sindex:\s"
    r"(?P<index_name>[\w_\\.\d]+)"
    r"\sdup key.*?"
    r'(?P<dup_key_value>("?[\\.\w_\d]+"?)|(null))'
)


@dataclass
class MongoConstraintDetails:
    collection_path: str
    index_name: str
    dup_key_value: Optional[str]

    def __post_init__(self):
        if self.dup_key_value:
            self.dup_key_value = self.dup_key_value.strip('"')
        if self.dup_key_value == "null":
            self.dup_key_value = None


def parse_error(error: PyMongoError) -> Optional[MongoConstraintDetails]:
    """
    >>> raw = 'E11000 duplicate key error collection: dev_situation.Robot index: _id_ dup key: { : "mw_wheel_id" }'
    >>> parse_error(raw)
    MongoConstraintDetails(collection_path='dev_situation.Robot', index_name='_id_', dup_key_value='mw_wheel_id')
    ''
    """
    error_str = str(error)
    for m in duplicate_key_regex.finditer(error_str):
        constraints = MongoConstraintDetails(**m.groupdict())
        if isinstance(error, DuplicateKeyError):
            _, constraints.dup_key_value = error.details["keyValue"].popitem()  # type: ignore
        return constraints
    logger.warning(f"unknown pymongo error:{error}")


class MongoConstraintError(Exception):
    def __init__(self, details: MongoConstraintDetails):
        self.details: MongoConstraintDetails = details


T = TypeVar("T")

ConstraintSubT = TypeVar("ConstraintSubT", bound=MongoConstraintError)


def raise_mongo_constraint_error(f: T = None, *, cls: Type[ConstraintSubT] = MongoConstraintError) -> T:
    def decorator(f: T):
        @wraps(f)  # type: ignore
        async def inner(*args, **kwargs):
            try:
                return await f(*args, **kwargs)  # type: ignore
            except PyMongoError as e:
                if details := parse_error(e):
                    raise cls(details) from e
                raise e

        return inner

    return decorator(f) if f else decorator  # type: ignore


def dump_with_id(
    model: BaseModel,
    id: str = "",
    dt_keys: Optional[List[str]] = None,
    property_keys: Optional[List[str]] = None,
    exclude: Optional[set[str]] = None,
) -> dict:
    """
    Warning:
        If you want to index on datetime, you have to set them afterwards
        As they will be dumped as strings
    """
    raw = dump_as_dict(model) if exclude is None else dump_as_dict(model.model_dump(exclude=exclude))
    if id:
        raw["_id"] = id
    if dt_keys:
        for key in dt_keys:
            raw[key] = getattr(model, key)
    if property_keys:
        for key in property_keys:
            raw[key] = getattr(model, key)
    return raw


async def create_or_replace(collection: AgnosticCollection, raw: dict) -> bool:
    """
    Returns:
        is_new: bool
    """
    result = await collection.replace_one({"_id": raw["_id"]}, raw, upsert=True)
    return bool(result.upserted_id)


async def find_one_and_update(
    collection: AgnosticCollection,
    id: str,
    updates: dict,
    return_raw_after: bool = True,
    upsert: bool = False,
    **query,
) -> Optional[dict]:
    """
    Warning:
        pops the "_id" from serialize_lib
    """
    return_doc = ReturnDocument.AFTER if return_raw_after else ReturnDocument.BEFORE
    updates = ensure_mongo_operation(updates)
    raw = await collection.find_one_and_update({"_id": id, **query}, updates, return_document=return_doc, upsert=upsert)
    if raw:
        raw.pop("_id", None)
        return raw


def microsecond_compare(mongo_dt: datetime, dt: datetime) -> bool:
    """Mongo only stores milliseconds since epoch
    https://stackoverflow.com/questions/39963143/why-is-there-a-difference-
    between-the-stored-and-queried-time-in-mongo-database."""
    with_microseconds = mongo_dt.replace(microsecond=dt.microsecond)
    return with_microseconds == dt and (mongo_dt - dt).total_seconds() < 0.001


def safe_key(key: str) -> str:
    return key.replace(".", "_DOT_")


def replace_dot_keys(values: dict) -> dict:
    """avoid InvalidDocument("key 'dev.amironenko' must not contain '.'")"""
    return {safe_key(key): value for key, value in values.items()}


def decode_delete_count(result: DeleteResult) -> int:
    return result.deleted_count


def push_and_limit_length_update(field_name: str, new_value: Any, max_size: int) -> dict:
    return {
        MongoUpdateOperation.push: {
            field_name: {
                MongoUpdateOperation.each: [new_value],
                MongoUpdateOperation.slice: -max_size,
            }
        }
    }


def index_dec(column: str) -> IndexModel:
    return IndexModel([(column, DESCENDING)])


def query_and_sort(collection: AgnosticCollection, query: dict, sort_col: str, desc: bool) -> AsyncIterable[dict]:
    sort_order = DESCENDING if desc else ASCENDING
    return collection.find(query).sort(sort_col, sort_order)
