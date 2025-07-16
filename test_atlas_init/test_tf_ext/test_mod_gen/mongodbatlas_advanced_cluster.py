# codegen atlas-init-marker-start
import json
import sys
from dataclasses import asdict, dataclass
from typing import Optional, List, Dict, Any, Set, ClassVar


@dataclass
class AdvancedConfiguration:
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
class BiConnectorConfig:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
    enabled: Optional[bool] = None
    read_preference: Optional[str] = None


@dataclass
class Endpoint:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {"endpoint_id", "provider_name", "region"}
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
    expiration_date: Optional[str] = None
    version: Optional[str] = None


@dataclass
class Autoscaling:
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = set()
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = set()
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


def main():
    input_data = sys.stdin.read()
    # Parse the input as JSON
    params = json.loads(input_data)
    input_json = params["input_json"]
    resource = Resource(**json.loads(input_json))
    error_message = ""
    primitive_types = (str, float, bool, int)
    output = {
        key: value if value is None or isinstance(value, primitive_types) else json.dumps(value)
        for key, value in asdict(resource).items()
    }
    output["error_message"] = error_message
    json_str = json.dumps(output)
    from pathlib import Path

    logs_out = Path(__file__).parent / "logs.json"
    logs_out.write_text(json_str)
    print(json_str)


if __name__ == "__main__":
    main()

# codegen atlas-init-marker-end
