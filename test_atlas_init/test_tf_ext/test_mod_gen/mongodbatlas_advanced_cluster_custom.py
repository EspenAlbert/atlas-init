# codegen atlas-init-marker-start
import json
import sys
from dataclasses import asdict, dataclass
from typing import Optional, List, Dict, Any, Set, ClassVar
from dataclasses import field
from typing import Iterable


@dataclass
class Resource_Advanced_configuration:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"custom_openssl_cipher_config_tls12"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
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
class Resource_Bi_connector_config:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    enabled: Optional[bool] = None
    read_preference: Optional[str] = None


@dataclass
class Resource_Connection_strings_Private_endpoint_Endpoints:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {"endpoint_id", "provider_name", "region"}
    endpoint_id: Optional[str] = None
    provider_name: Optional[str] = None
    region: Optional[str] = None


@dataclass
class Resource_Connection_strings_Private_endpoint:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"endpoints"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {
        "connection_string",
        "endpoints",
        "srv_connection_string",
        "srv_shard_optimized_connection_string",
        "type",
    }
    connection_string: Optional[str] = None
    endpoints: Optional[List[Resource_Connection_strings_Private_endpoint_Endpoints]] = None
    srv_connection_string: Optional[str] = None
    srv_shard_optimized_connection_string: Optional[str] = None
    type: Optional[str] = None

    def __post_init__(self):
        if self.endpoints is not None:
            self.endpoints = [
                Resource_Connection_strings_Private_endpoint_Endpoints(**x)
                if not isinstance(x, Resource_Connection_strings_Private_endpoint_Endpoints)
                else x
                for x in self.endpoints
            ]


@dataclass
class Resource_Connection_strings:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"private_endpoint"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {
        "private",
        "private_endpoint",
        "private_srv",
        "standard",
        "standard_srv",
    }
    private: Optional[str] = None
    private_endpoint: Optional[List[Resource_Connection_strings_Private_endpoint]] = None
    private_srv: Optional[str] = None
    standard: Optional[str] = None
    standard_srv: Optional[str] = None

    def __post_init__(self):
        if self.private_endpoint is not None:
            self.private_endpoint = [
                Resource_Connection_strings_Private_endpoint(**x)
                if not isinstance(x, Resource_Connection_strings_Private_endpoint)
                else x
                for x in self.private_endpoint
            ]


@dataclass
class Resource_Pinned_fcv:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = {"expiration_date"}
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {"version"}
    expiration_date: Optional[str] = None
    version: Optional[str] = None


@dataclass
class Resource_Replication_specs_Region_configs_Analytics_auto_scaling:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    compute_enabled: Optional[bool] = None
    compute_max_instance_size: Optional[str] = None
    compute_min_instance_size: Optional[str] = None
    compute_scale_down_enabled: Optional[bool] = None
    disk_gb_enabled: Optional[bool] = None


@dataclass
class Resource_Replication_specs_Region_configs_Analytics_specs:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    disk_iops: Optional[float] = None
    disk_size_gb: Optional[float] = None
    ebs_volume_type: Optional[str] = None
    instance_size: Optional[str] = None
    node_count: Optional[float] = None


@dataclass
class Resource_Replication_specs_Region_configs_Auto_scaling:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    compute_enabled: Optional[bool] = None
    compute_max_instance_size: Optional[str] = None
    compute_min_instance_size: Optional[str] = None
    compute_scale_down_enabled: Optional[bool] = None
    disk_gb_enabled: Optional[bool] = None


@dataclass
class Resource_Replication_specs_Region_configs_Electable_specs:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    disk_iops: Optional[float] = None
    disk_size_gb: Optional[float] = None
    ebs_volume_type: Optional[str] = None
    instance_size: Optional[str] = None
    node_count: Optional[float] = None


@dataclass
class Resource_Replication_specs_Region_configs_Read_only_specs:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    disk_iops: Optional[float] = None
    disk_size_gb: Optional[float] = None
    ebs_volume_type: Optional[str] = None
    instance_size: Optional[str] = None
    node_count: Optional[float] = None


@dataclass
class Resource_Replication_specs_Region_configs:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {
        "analytics_auto_scaling",
        "analytics_specs",
        "auto_scaling",
        "electable_specs",
        "read_only_specs",
    }
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = {"priority", "provider_name", "region_name"}
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    priority: Optional[float] = None
    provider_name: Optional[str] = None
    region_name: Optional[str] = None
    analytics_auto_scaling: Optional[Resource_Replication_specs_Region_configs_Analytics_auto_scaling] = None
    analytics_specs: Optional[Resource_Replication_specs_Region_configs_Analytics_specs] = None
    auto_scaling: Optional[Resource_Replication_specs_Region_configs_Auto_scaling] = None
    backing_provider_name: Optional[str] = None
    electable_specs: Optional[Resource_Replication_specs_Region_configs_Electable_specs] = None
    read_only_specs: Optional[Resource_Replication_specs_Region_configs_Read_only_specs] = None

    def __post_init__(self):
        if self.analytics_auto_scaling is not None and not isinstance(
            self.analytics_auto_scaling, Resource_Replication_specs_Region_configs_Analytics_auto_scaling
        ):
            self.analytics_auto_scaling = Resource_Replication_specs_Region_configs_Analytics_auto_scaling(
                **self.analytics_auto_scaling
            )
        if self.analytics_specs is not None and not isinstance(
            self.analytics_specs, Resource_Replication_specs_Region_configs_Analytics_specs
        ):
            self.analytics_specs = Resource_Replication_specs_Region_configs_Analytics_specs(**self.analytics_specs)
        if self.auto_scaling is not None and not isinstance(
            self.auto_scaling, Resource_Replication_specs_Region_configs_Auto_scaling
        ):
            self.auto_scaling = Resource_Replication_specs_Region_configs_Auto_scaling(**self.auto_scaling)
        if self.electable_specs is not None and not isinstance(
            self.electable_specs, Resource_Replication_specs_Region_configs_Electable_specs
        ):
            self.electable_specs = Resource_Replication_specs_Region_configs_Electable_specs(**self.electable_specs)
        if self.read_only_specs is not None and not isinstance(
            self.read_only_specs, Resource_Replication_specs_Region_configs_Read_only_specs
        ):
            self.read_only_specs = Resource_Replication_specs_Region_configs_Read_only_specs(**self.read_only_specs)


@dataclass
class Resource_Replication_specs:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"container_id", "region_configs"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = {"region_configs"}
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {"container_id", "external_id", "id", "zone_id"}
    region_configs: Optional[List[Resource_Replication_specs_Region_configs]] = None
    container_id: Optional[Dict[str, Any]] = None
    external_id: Optional[str] = None
    id: Optional[str] = None
    num_shards: Optional[float] = None
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None

    def __post_init__(self):
        if self.region_configs is not None:
            self.region_configs = [
                Resource_Replication_specs_Region_configs(**x)
                if not isinstance(x, Resource_Replication_specs_Region_configs)
                else x
                for x in self.region_configs
            ]


@dataclass
class Resource_Timeouts:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
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
    cluster_type: Optional[str] = None
    name: Optional[str] = None
    project_id: Optional[str] = None
    replication_specs: Optional[List[Resource_Replication_specs]] = None
    accept_data_risks_and_force_replica_set_reconfig: Optional[str] = None
    advanced_configuration: Optional[Resource_Advanced_configuration] = None
    backup_enabled: Optional[bool] = None
    bi_connector_config: Optional[Resource_Bi_connector_config] = None
    cluster_id: Optional[str] = None
    config_server_management_mode: Optional[str] = None
    config_server_type: Optional[str] = None
    connection_strings: Optional[Resource_Connection_strings] = None
    create_date: Optional[str] = None
    delete_on_create_timeout: Optional[bool] = None
    disk_size_gb: Optional[float] = None
    encryption_at_rest_provider: Optional[str] = None
    global_cluster_self_managed_sharding: Optional[bool] = None
    labels: Optional[Dict[str, Any]] = None
    mongo_db_major_version: Optional[str] = None
    mongo_db_version: Optional[str] = None
    paused: Optional[bool] = None
    pinned_fcv: Optional[Resource_Pinned_fcv] = None
    pit_enabled: Optional[bool] = None
    redact_client_log_data: Optional[bool] = None
    replica_set_scaling_strategy: Optional[str] = None
    retain_backups_enabled: Optional[bool] = None
    root_cert_type: Optional[str] = None
    state_name: Optional[str] = None
    tags: Optional[Dict[str, Any]] = None
    termination_protection_enabled: Optional[bool] = None
    timeouts: Optional[Resource_Timeouts] = None
    version_release_system: Optional[str] = None

    def __post_init__(self):
        if self.advanced_configuration is not None and not isinstance(
            self.advanced_configuration, Resource_Advanced_configuration
        ):
            self.advanced_configuration = Resource_Advanced_configuration(**self.advanced_configuration)
        if self.bi_connector_config is not None and not isinstance(
            self.bi_connector_config, Resource_Bi_connector_config
        ):
            self.bi_connector_config = Resource_Bi_connector_config(**self.bi_connector_config)
        if self.connection_strings is not None and not isinstance(self.connection_strings, Resource_Connection_strings):
            self.connection_strings = Resource_Connection_strings(**self.connection_strings)
        if self.pinned_fcv is not None and not isinstance(self.pinned_fcv, Resource_Pinned_fcv):
            self.pinned_fcv = Resource_Pinned_fcv(**self.pinned_fcv)
        if self.replication_specs is not None:
            self.replication_specs = [
                Resource_Replication_specs(**x) if not isinstance(x, Resource_Replication_specs) else x
                for x in self.replication_specs
            ]
        if self.timeouts is not None and not isinstance(self.timeouts, Resource_Timeouts):
            self.timeouts = Resource_Timeouts(**self.timeouts)


def main():
    input_data = sys.stdin.read()
    # Parse the input as JSON
    params = json.loads(input_data)
    input_json = params["input_json"]
    resource = Resource(**json.loads(input_json))
    primitive_types = (str, float, bool, int)

    output = {
        key: value if value is None or isinstance(value, primitive_types) else json.dumps(value)
        for key, value in asdict(resource).items()
    }
    output["error_message"] = "\n".join(errors(resource))
    json_str = json.dumps(output)
    from pathlib import Path

    logs_out = Path(__file__).parent / "logs.json"
    logs_out.write_text(json_str)
    print(json_str)


if __name__ == "__main__":
    main()

# codegen atlas-init-marker-end


@dataclass
class SpecRegion:
    cloud_provider: str
    name: str
    node_count: int


@dataclass
class Spec:
    disk_size_gb: float = 50
    regions: list[SpecRegion] = field(default_factory=list)


@dataclass
class AutoScalingCompute:
    min_size: str
    max_size: str


@dataclass
class ResourceExt(Resource):
    electable: Optional[Spec] = None
    auto_scaling_compute: Optional[AutoScalingCompute] = None
    default_instance_size: Optional[str] = None

    DEFAULT_INSTANCE_SIZE: ClassVar[str] = "M10"
    MUTUALLY_EXCLUSIVE: ClassVar[dict[str, list[str]]] = {
        "electable": ["replication_specs"],
        "auto_scaling_compute": ["replication_specs"],
    }
    REQUIRES_OTHER: ClassVar[dict[str, list[str]]] = {"auto_scaling_compute": ["electable"]}

    @property
    def can_generate_replication_spec(self) -> bool:
        return self.electable is not None

    @property
    def instance_size_unset(self) -> bool:
        return self.default_instance_size == "UNSET"

    def get_default_instance_size(self):
        if not self.instance_size_unset:
            return self.default_instance_size
        if self.auto_scaling_compute:
            return self.auto_scaling_compute.min_size
        return "M10"


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


def default_region_configs(spec: Spec) -> list[Resource_Replication_specs_Region_configs]:
    return [
        Resource_Replication_specs_Region_configs(
            priority=8 - i,
            provider_name=region.cloud_provider,
            region_name=region.name,
        )
        for i, region in enumerate(spec.regions)
    ]


def generate_replication_specs(resource: ResourceExt) -> list[Resource_Replication_specs]:
    specs = [Resource_Replication_specs()]
    electable = resource.electable
    assert electable

    for spec in specs:
        spec.region_configs = default_region_configs(electable)
        for region_config, region_electable in zip(spec.region_configs, electable.regions):
            region_config.electable_specs = Resource_Replication_specs_Region_configs_Electable_specs(
                disk_size_gb=electable.disk_size_gb,
                instance_size=resource.get_default_instance_size(),
                node_count=region_electable.node_count,
            )
        auto_scaling_compute = resource.auto_scaling_compute
        if auto_scaling_compute:
            for region_config in spec.region_configs:
                region_config.auto_scaling = Resource_Replication_specs_Region_configs_Auto_scaling(
                    compute_enabled=True,
                    compute_max_instance_size=auto_scaling_compute.max_size,
                    compute_min_instance_size=auto_scaling_compute.min_size,
                )
    return specs


def modify_out(resource: ResourceExt) -> Resource:
    if resource.can_generate_replication_spec:
        resource.replication_specs = generate_replication_specs(resource)
    return resource
