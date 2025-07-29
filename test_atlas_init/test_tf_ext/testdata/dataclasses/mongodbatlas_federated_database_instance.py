# codegen atlas-init-marker-start
import json
import sys
from dataclasses import asdict, dataclass
from typing import Optional, List, Set, ClassVar, Union


@dataclass
class Aws:
    BLOCK_ATTRIBUTES: ClassVar[Set[str]] = set()
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = {"role_id", "test_s3_bucket"}
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {"external_id", "iam_assumed_role_arn", "iam_user_arn"}
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    external_id: Optional[str] = None
    iam_assumed_role_arn: Optional[str] = None
    iam_user_arn: Optional[str] = None
    role_id: Optional[str] = None
    test_s3_bucket: Optional[str] = None


@dataclass
class Azure:
    BLOCK_ATTRIBUTES: ClassVar[Set[str]] = set()
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = {"role_id"}
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {"atlas_app_id", "service_principal_id", "tenant_id"}
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    atlas_app_id: Optional[str] = None
    role_id: Optional[str] = None
    service_principal_id: Optional[str] = None
    tenant_id: Optional[str] = None


@dataclass
class CloudProviderConfig:
    BLOCK_ATTRIBUTES: ClassVar[Set[str]] = {"aws", "azure"}
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"aws", "azure"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    aws: Optional[Aws] = None
    azure: Optional[Azure] = None

    def __post_init__(self):
        if self.aws is not None and not isinstance(self.aws, Aws):
            assert isinstance(self.aws, dict), f"Expected aws to be a Aws or a dict, got {type(self.aws)}"
            self.aws = Aws(**self.aws)
        if self.azure is not None and not isinstance(self.azure, Azure):
            assert isinstance(self.azure, dict), f"Expected azure to be a Azure or a dict, got {type(self.azure)}"
            self.azure = Azure(**self.azure)


@dataclass
class DataProcessRegion:
    BLOCK_ATTRIBUTES: ClassVar[Set[str]] = set()
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = {"cloud_provider", "region"}
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    cloud_provider: Optional[str] = None
    region: Optional[str] = None


@dataclass
class DataSource:
    BLOCK_ATTRIBUTES: ClassVar[Set[str]] = set()
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"urls"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    allow_insecure: Optional[bool] = None
    collection: Optional[str] = None
    collection_regex: Optional[str] = None
    database: Optional[str] = None
    database_regex: Optional[str] = None
    dataset_name: Optional[str] = None
    default_format: Optional[str] = None
    path: Optional[str] = None
    provenance_field_name: Optional[str] = None
    store_name: Optional[str] = None
    urls: Optional[List[str]] = None


@dataclass
class Collection:
    BLOCK_ATTRIBUTES: ClassVar[Set[str]] = {"data_sources"}
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"data_sources"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    name: Optional[str] = None
    data_sources: Optional[DataSource] = None

    def __post_init__(self):
        if self.data_sources is not None and not isinstance(self.data_sources, DataSource):
            assert isinstance(self.data_sources, dict), (
                f"Expected data_sources to be a DataSource or a dict, got {type(self.data_sources)}"
            )
            self.data_sources = DataSource(**self.data_sources)


@dataclass
class View:
    BLOCK_ATTRIBUTES: ClassVar[Set[str]] = set()
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {"name", "pipeline", "source"}
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    name: Optional[str] = None
    pipeline: Optional[str] = None
    source: Optional[str] = None


@dataclass
class StorageDatabase:
    BLOCK_ATTRIBUTES: ClassVar[Set[str]] = {"collections", "views"}
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"collections", "views"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {"max_wildcard_collections"}
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    max_wildcard_collections: Optional[float] = None
    name: Optional[str] = None
    collections: Optional[Collection] = None
    views: Optional[View] = None

    def __post_init__(self):
        if self.collections is not None and not isinstance(self.collections, Collection):
            assert isinstance(self.collections, dict), (
                f"Expected collections to be a Collection or a dict, got {type(self.collections)}"
            )
            self.collections = Collection(**self.collections)
        if self.views is not None and not isinstance(self.views, View):
            assert isinstance(self.views, dict), f"Expected views to be a View or a dict, got {type(self.views)}"
            self.views = View(**self.views)


@dataclass
class Tag:
    BLOCK_ATTRIBUTES: ClassVar[Set[str]] = set()
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    name: Optional[str] = None
    value: Optional[str] = None


@dataclass
class TagSet:
    BLOCK_ATTRIBUTES: ClassVar[Set[str]] = {"tags"}
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"tags"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = {"tags"}
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    tags: Optional[Tag] = None

    def __post_init__(self):
        if self.tags is not None and not isinstance(self.tags, Tag):
            assert isinstance(self.tags, dict), f"Expected tags to be a Tag or a dict, got {type(self.tags)}"
            self.tags = Tag(**self.tags)


@dataclass
class ReadPreference:
    BLOCK_ATTRIBUTES: ClassVar[Set[str]] = {"tag_sets"}
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"tag_sets"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    max_staleness_seconds: Optional[float] = None
    mode: Optional[str] = None
    tag_sets: Optional[TagSet] = None

    def __post_init__(self):
        if self.tag_sets is not None and not isinstance(self.tag_sets, TagSet):
            assert isinstance(self.tag_sets, dict), (
                f"Expected tag_sets to be a TagSet or a dict, got {type(self.tag_sets)}"
            )
            self.tag_sets = TagSet(**self.tag_sets)


@dataclass
class StorageStore:
    BLOCK_ATTRIBUTES: ClassVar[Set[str]] = {"read_preference"}
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"additional_storage_classes", "urls", "read_preference"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    additional_storage_classes: Optional[List[str]] = None
    allow_insecure: Optional[bool] = None
    bucket: Optional[str] = None
    cluster_name: Optional[str] = None
    default_format: Optional[str] = None
    delimiter: Optional[str] = None
    include_tags: Optional[bool] = None
    name: Optional[str] = None
    prefix: Optional[str] = None
    project_id: Optional[str] = None
    provider: Optional[str] = None
    public: Optional[str] = None
    region: Optional[str] = None
    urls: Optional[List[str]] = None
    read_preference: Optional[ReadPreference] = None

    def __post_init__(self):
        if self.read_preference is not None and not isinstance(self.read_preference, ReadPreference):
            assert isinstance(self.read_preference, dict), (
                f"Expected read_preference to be a ReadPreference or a dict, got {type(self.read_preference)}"
            )
            self.read_preference = ReadPreference(**self.read_preference)


@dataclass
class Resource:
    BLOCK_ATTRIBUTES: ClassVar[Set[str]] = {
        "cloud_provider_config",
        "data_process_region",
        "storage_databases",
        "storage_stores",
    }
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {
        "hostnames",
        "cloud_provider_config",
        "data_process_region",
        "storage_databases",
        "storage_stores",
    }
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = {"name", "project_id"}
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {"hostnames", "state"}
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    hostnames: Optional[List[str]] = None
    id: Optional[str] = None
    name: Optional[str] = None
    project_id: Optional[str] = None
    state: Optional[str] = None
    cloud_provider_config: Optional[CloudProviderConfig] = None
    data_process_region: Optional[DataProcessRegion] = None
    storage_databases: Optional[StorageDatabase] = None
    storage_stores: Optional[StorageStore] = None

    def __post_init__(self):
        if self.cloud_provider_config is not None and not isinstance(self.cloud_provider_config, CloudProviderConfig):
            assert isinstance(self.cloud_provider_config, dict), (
                f"Expected cloud_provider_config to be a CloudProviderConfig or a dict, got {type(self.cloud_provider_config)}"
            )
            self.cloud_provider_config = CloudProviderConfig(**self.cloud_provider_config)
        if self.data_process_region is not None and not isinstance(self.data_process_region, DataProcessRegion):
            assert isinstance(self.data_process_region, dict), (
                f"Expected data_process_region to be a DataProcessRegion or a dict, got {type(self.data_process_region)}"
            )
            self.data_process_region = DataProcessRegion(**self.data_process_region)
        if self.storage_databases is not None and not isinstance(self.storage_databases, StorageDatabase):
            assert isinstance(self.storage_databases, dict), (
                f"Expected storage_databases to be a StorageDatabase or a dict, got {type(self.storage_databases)}"
            )
            self.storage_databases = StorageDatabase(**self.storage_databases)
        if self.storage_stores is not None and not isinstance(self.storage_stores, StorageStore):
            assert isinstance(self.storage_stores, dict), (
                f"Expected storage_stores to be a StorageStore or a dict, got {type(self.storage_stores)}"
            )
            self.storage_stores = StorageStore(**self.storage_stores)


def format_primitive(value: Union[str, float, bool, int, None]):
    if value is None:
        return None
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def main():
    input_data = sys.stdin.read()
    # Parse the input as JSON
    params = json.loads(input_data)
    input_json = params["input_json"]
    resource = Resource(**json.loads(input_json))
    error_message = ""
    primitive_types = (str, float, bool, int)
    output = {
        key: format_primitive(value) if value is None or isinstance(value, primitive_types) else json.dumps(value)
        for key, value in asdict(resource).items()
    }
    output["error_message"] = error_message
    json_str = json.dumps(output)
    print(json_str)


if __name__ == "__main__":
    main()


# codegen atlas-init-marker-end
