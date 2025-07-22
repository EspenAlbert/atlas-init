# codegen atlas-init-marker-start
import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Optional, List, Dict, Any, Set, ClassVar, Union, Iterable


@dataclass
class AdvancedConfiguration:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"custom_openssl_cipher_config_tls12"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    change_stream_options_pre_and_post_images_expire_after_seconds: Optional[float] = None
    custom_openssl_cipher_config_tls12: Optional[List[str]] = None
    default_max_time_ms: Optional[float] = None
    default_read_concern: Optional[str] = None
    default_write_concern: Optional[str] = None
    fail_index_key_too_long: Optional[bool] = None
    javascript_enabled: Optional[bool] = None
    minimum_enabled_tls_protocol: Optional[str] = None
    no_table_scan: Optional[bool] = None
    oplog_min_retention_hours: Optional[float] = None
    oplog_size_mb: Optional[float] = None
    sample_refresh_interval_bi_connector: Optional[float] = None
    sample_size_bi_connector: Optional[float] = None
    tls_cipher_config_mode: Optional[str] = None
    transaction_lifetime_limit_seconds: Optional[float] = None


@dataclass
class BiConnectorConfig:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    enabled: Optional[bool] = None
    read_preference: Optional[str] = None


@dataclass
class Endpoint:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {"endpoint_id", "provider_name", "region"}
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    endpoint_id: Optional[str] = None
    provider_name: Optional[str] = None
    region: Optional[str] = None


@dataclass
class PrivateEndpoint:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"endpoints"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {
        "connection_string",
        "endpoints",
        "srv_connection_string",
        "srv_shard_optimized_connection_string",
        "type",
    }
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    connection_string: Optional[str] = None
    endpoints: Optional[List[Endpoint]] = None
    srv_connection_string: Optional[str] = None
    srv_shard_optimized_connection_string: Optional[str] = None
    type: Optional[str] = None

    def __post_init__(self):
        if self.endpoints is not None:
            self.endpoints = [x if isinstance(x, Endpoint) else Endpoint(**x) for x in self.endpoints]


@dataclass
class ConnectionString:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"private_endpoint"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {
        "private",
        "private_endpoint",
        "private_srv",
        "standard",
        "standard_srv",
    }
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    private: Optional[str] = None
    private_endpoint: Optional[List[PrivateEndpoint]] = None
    private_srv: Optional[str] = None
    standard: Optional[str] = None
    standard_srv: Optional[str] = None

    def __post_init__(self):
        if self.private_endpoint is not None:
            self.private_endpoint = [
                x if isinstance(x, PrivateEndpoint) else PrivateEndpoint(**x) for x in self.private_endpoint
            ]


@dataclass
class PinnedFcv:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = {"expiration_date"}
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {"version"}
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    expiration_date: Optional[str] = None
    version: Optional[str] = None


@dataclass
class Autoscaling:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    compute_enabled: Optional[bool] = None
    compute_max_instance_size: Optional[str] = None
    compute_min_instance_size: Optional[str] = None
    compute_scale_down_enabled: Optional[bool] = None
    disk_gb_enabled: Optional[bool] = None


@dataclass
class Spec:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    disk_iops: Optional[float] = None
    disk_size_gb: Optional[float] = None
    ebs_volume_type: Optional[str] = None
    instance_size: Optional[str] = None
    node_count: Optional[float] = None


@dataclass
class RegionConfig:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {
        "analytics_auto_scaling",
        "analytics_specs",
        "auto_scaling",
        "electable_specs",
        "read_only_specs",
    }
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = {"priority", "provider_name", "region_name"}
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    analytics_auto_scaling: Optional[Autoscaling] = None
    analytics_specs: Optional[Spec] = None
    auto_scaling: Optional[Autoscaling] = None
    backing_provider_name: Optional[str] = None
    electable_specs: Optional[Spec] = None
    priority: Optional[float] = None
    provider_name: Optional[str] = None
    read_only_specs: Optional[Spec] = None
    region_name: Optional[str] = None

    def __post_init__(self):
        if self.analytics_auto_scaling is not None and not isinstance(self.analytics_auto_scaling, Autoscaling):
            assert isinstance(self.analytics_auto_scaling, dict), (
                f"Expected analytics_auto_scaling to be a Autoscaling or a dict, got {type(self.analytics_auto_scaling)}"
            )
            self.analytics_auto_scaling = Autoscaling(**self.analytics_auto_scaling)
        if self.analytics_specs is not None and not isinstance(self.analytics_specs, Spec):
            assert isinstance(self.analytics_specs, dict), (
                f"Expected analytics_specs to be a Spec or a dict, got {type(self.analytics_specs)}"
            )
            self.analytics_specs = Spec(**self.analytics_specs)
        if self.auto_scaling is not None and not isinstance(self.auto_scaling, Autoscaling):
            assert isinstance(self.auto_scaling, dict), (
                f"Expected auto_scaling to be a Autoscaling or a dict, got {type(self.auto_scaling)}"
            )
            self.auto_scaling = Autoscaling(**self.auto_scaling)
        if self.electable_specs is not None and not isinstance(self.electable_specs, Spec):
            assert isinstance(self.electable_specs, dict), (
                f"Expected electable_specs to be a Spec or a dict, got {type(self.electable_specs)}"
            )
            self.electable_specs = Spec(**self.electable_specs)
        if self.read_only_specs is not None and not isinstance(self.read_only_specs, Spec):
            assert isinstance(self.read_only_specs, dict), (
                f"Expected read_only_specs to be a Spec or a dict, got {type(self.read_only_specs)}"
            )
            self.read_only_specs = Spec(**self.read_only_specs)


@dataclass
class ReplicationSpec:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"container_id", "region_configs"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = {"region_configs"}
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {"container_id", "external_id", "id", "zone_id"}
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    container_id: Optional[Dict[str, Any]] = None
    external_id: Optional[str] = None
    id: Optional[str] = None
    num_shards: Optional[float] = None
    region_configs: Optional[List[RegionConfig]] = None
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None

    def __post_init__(self):
        if self.region_configs is not None:
            self.region_configs = [x if isinstance(x, RegionConfig) else RegionConfig(**x) for x in self.region_configs]


@dataclass
class Timeout:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    create: Optional[str] = None
    delete: Optional[str] = None
    update: Optional[str] = None


@dataclass
class Resource:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {
        "advanced_configuration",
        "bi_connector_config",
        "connection_strings",
        "labels",
        "pinned_fcv",
        "replication_specs",
        "tags",
        "timeouts",
    }
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = {"cluster_type", "name", "project_id", "replication_specs"}
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {
        "cluster_id",
        "config_server_type",
        "connection_strings",
        "create_date",
        "mongo_db_version",
        "state_name",
    }
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {}
    accept_data_risks_and_force_replica_set_reconfig: Optional[str] = None
    advanced_configuration: Optional[AdvancedConfiguration] = None
    backup_enabled: Optional[bool] = None
    bi_connector_config: Optional[BiConnectorConfig] = None
    cluster_id: Optional[str] = None
    cluster_type: Optional[str] = None
    config_server_management_mode: Optional[str] = None
    config_server_type: Optional[str] = None
    connection_strings: Optional[ConnectionString] = None
    create_date: Optional[str] = None
    delete_on_create_timeout: Optional[bool] = None
    disk_size_gb: Optional[float] = None
    encryption_at_rest_provider: Optional[str] = None
    global_cluster_self_managed_sharding: Optional[bool] = None
    labels: Optional[Dict[str, Any]] = None
    mongo_db_major_version: Optional[str] = None
    mongo_db_version: Optional[str] = None
    name: Optional[str] = None
    paused: Optional[bool] = None
    pinned_fcv: Optional[PinnedFcv] = None
    pit_enabled: Optional[bool] = None
    project_id: Optional[str] = None
    redact_client_log_data: Optional[bool] = None
    replica_set_scaling_strategy: Optional[str] = None
    replication_specs: Optional[List[ReplicationSpec]] = None
    retain_backups_enabled: Optional[bool] = None
    root_cert_type: Optional[str] = None
    state_name: Optional[str] = None
    tags: Optional[Dict[str, Any]] = None
    termination_protection_enabled: Optional[bool] = None
    timeouts: Optional[Timeout] = None
    version_release_system: Optional[str] = None

    def __post_init__(self):
        if self.advanced_configuration is not None and not isinstance(
            self.advanced_configuration, AdvancedConfiguration
        ):
            assert isinstance(self.advanced_configuration, dict), (
                f"Expected advanced_configuration to be a AdvancedConfiguration or a dict, got {type(self.advanced_configuration)}"
            )
            self.advanced_configuration = AdvancedConfiguration(**self.advanced_configuration)
        if self.bi_connector_config is not None and not isinstance(self.bi_connector_config, BiConnectorConfig):
            assert isinstance(self.bi_connector_config, dict), (
                f"Expected bi_connector_config to be a BiConnectorConfig or a dict, got {type(self.bi_connector_config)}"
            )
            self.bi_connector_config = BiConnectorConfig(**self.bi_connector_config)
        if self.connection_strings is not None and not isinstance(self.connection_strings, ConnectionString):
            assert isinstance(self.connection_strings, dict), (
                f"Expected connection_strings to be a ConnectionString or a dict, got {type(self.connection_strings)}"
            )
            self.connection_strings = ConnectionString(**self.connection_strings)
        if self.pinned_fcv is not None and not isinstance(self.pinned_fcv, PinnedFcv):
            assert isinstance(self.pinned_fcv, dict), (
                f"Expected pinned_fcv to be a PinnedFcv or a dict, got {type(self.pinned_fcv)}"
            )
            self.pinned_fcv = PinnedFcv(**self.pinned_fcv)
        if self.replication_specs is not None:
            self.replication_specs = [
                x if isinstance(x, ReplicationSpec) else ReplicationSpec(**x) for x in self.replication_specs
            ]
        if self.timeouts is not None and not isinstance(self.timeouts, Timeout):
            assert isinstance(self.timeouts, dict), (
                f"Expected timeouts to be a Timeout or a dict, got {type(self.timeouts)}"
            )
            self.timeouts = Timeout(**self.timeouts)


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
    resource = ResourceExt(**json.loads(input_json))
    error_message = "\n".join(errors(resource))
    primitive_types = (str, float, bool, int)
    resource = modify_out(resource)
    output = {
        key: format_primitive(value) if value is None or isinstance(value, primitive_types) else json.dumps(value)
        for key, value in asdict(resource).items()
    }
    output["error_message"] = error_message
    json_str = json.dumps(output)
    print(json_str)


# codegen atlas-init-marker-end


@dataclass
class ResourceExt(Resource):
    aws_regions: Optional[Dict[str, int]] = None
    azure_regions: Optional[Dict[str, int]] = None
    instance_size: Optional[str] = None
    cloud_order: List[str] = field(default_factory=lambda: ["aws", "azure"])
    num_shards: Optional[int] = None
    old_cluster: Optional[Resource] = None
    auto_scaling: Optional[Autoscaling] = None

    DEFAULT_INSTANCE_SIZE: ClassVar[str] = "M10"
    MUTUALLY_EXCLUSIVE: ClassVar[dict[str, list[str]]] = {
        "aws_regions": ["replication_specs"],
        "azure_regions": ["replication_specs"],
        "auto_scaling": ["instance_size"],
    }
    REQUIRES_OTHER: ClassVar[dict[str, list[str]]] = {
        "instance_size": ["can_generate_replication_spec"],
        "num_shards": ["can_generate_replication_spec"],
        "auto_scaling": ["can_generate_replication_spec"],
    }
    SKIP_VARIABLES: ClassVar[set[str]] = {"old_cluster"}

    def __post_init__(self):
        super().__post_init__()
        if self.old_cluster is not None and not isinstance(self.old_cluster, Resource):
            assert isinstance(self.old_cluster, dict), (
                f"Expected old_cluster to be a Resource or a dict, got {type(self.old_cluster)}"
            )
            self.old_cluster = Resource(
                **{k: v for k, v in self.old_cluster.items() if k not in {"use_replication_spec_per_shard"}}
            )
        if self.auto_scaling is not None and not isinstance(self.auto_scaling, Autoscaling):
            assert isinstance(self.auto_scaling, dict), (
                f"Expected auto_scaling to be an Autoscaling or a dict, got {type(self.auto_scaling)}"
            )
            self.auto_scaling = Autoscaling(**self.auto_scaling)

    @property
    def can_generate_replication_spec(self) -> bool:
        return bool(self.aws_regions or self.azure_regions)

    def infer_cluster_type(self) -> str:
        if self.cluster_type:
            return self.cluster_type
        return "SHARDED" if self.num_shards and self.num_shards > 1 else "REPLICASET"

    def regions(self, cloud_name: str) -> dict[str, int]:
        if cloud_name == "aws":
            return self.aws_regions or {}
        elif cloud_name == "azure":
            return self.azure_regions or {}
        else:
            raise ValueError(f"Unknown cloud name: {cloud_name}")

    def get_instance_size(self, shard_index: int, region_config_index: int, spec_type: str = "electable") -> str:
        if self.instance_size is not None:
            return self.instance_size
        if self.auto_scaling is not None:
            default_min_size = self.auto_scaling.compute_min_instance_size
            assert default_min_size is not None, (
                f"{self.auto_scaling.compute_min_instance_size} is not a valid instance size"
            )
            if self.old_cluster is not None:
                return self.current_instance_size(shard_index, region_config_index, spec_type) or default_min_size
            else:
                return default_min_size
        return self.DEFAULT_INSTANCE_SIZE

    def current_instance_size(self, shard_index: int, region_config_index: int, spec_type: str = "electable") -> str:
        old_cluster = self.old_cluster
        assert old_cluster is not None
        specs = old_cluster.replication_specs
        if not specs or len(specs) <= shard_index:
            return ""
        shard = specs[shard_index]
        region_configs = shard.region_configs
        if not region_configs or len(region_configs) <= region_config_index:
            return ""
        region_config = region_configs[region_config_index]
        if spec_type == "electable":
            return region_config.electable_specs.instance_size
        if spec_type == "analytics":
            return region_config.analytics_specs.instance_size
        if spec_type == "read_only":
            return region_config.read_only_specs.instance_size
        return ""


def errors(resource: ResourceExt) -> Iterable[str]:
    for var, mutually_exclusive_fields in resource.MUTUALLY_EXCLUSIVE.items():
        if not getattr(resource, var):
            continue
        for incompatible in mutually_exclusive_fields:
            if getattr(resource, incompatible):
                yield f"Cannot use var.{var} and var.{incompatible} together"
    for var, required_vars in resource.REQUIRES_OTHER.items():
        if not getattr(resource, var):
            continue
        missing_required = [required for required in required_vars if not getattr(resource, required)]
        if missing_required:
            yield f"Cannot use {var} without {','.join(sorted(missing_required))}"


def generate_replication_specs(resource: ResourceExt) -> list[ReplicationSpec]:
    specs = []
    auto_scaling = resource.auto_scaling
    for shard_index in range(resource.num_shards or 1):
        region_configs: list[RegionConfig] = []
        spec = ReplicationSpec()
        specs.append(spec)
        current_priority = 7
        for cloud_name in resource.cloud_order:
            for region_index, (region_name, node_count) in enumerate(resource.regions(cloud_name).items()):
                region = RegionConfig(
                    provider_name=cloud_name.upper(),
                    region_name=region_name,
                    priority=current_priority,
                    electable_specs=Spec(
                        disk_size_gb=resource.disk_size_gb,
                        instance_size=resource.get_instance_size(shard_index, region_index, spec_type="electable"),
                        node_count=node_count,
                    ),
                    auto_scaling=auto_scaling,
                )
                current_priority -= 1
                region_configs.append(region)
        spec.region_configs = region_configs
    return specs


def modify_out(resource: ResourceExt) -> ResourceExt:
    if resource.can_generate_replication_spec:
        resource.replication_specs = generate_replication_specs(resource)
        resource.cluster_type = resource.infer_cluster_type()
    return resource


if __name__ == "__main__":
    main()
