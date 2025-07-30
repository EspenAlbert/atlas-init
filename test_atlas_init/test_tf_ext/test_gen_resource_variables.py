from dataclasses import dataclass
from typing import ClassVar, List, Optional, Set

from atlas_init.tf_ext.gen_resource_main import format_tf_content
from atlas_init.tf_ext.gen_resource_variables import generate_resource_variables
from atlas_init.tf_ext.models_module import ResourceAbs, ResourceGenConfig


@dataclass
class AdvancedConfiguration(ResourceAbs):
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {"custom_openssl_cipher_config_tls12"}
    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = {"default_write_concern"}
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {"default_read_concern"}
    DEFAULTS_HCL_STRINGS: ClassVar[dict[str, str]] = {
        "custom_openssl_cipher_config_tls12": '["TLS1_2"]',
        "javascript_enabled": "false",
        "tls_cipher_config_mode": '"DEFAULT"',
    }
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
class Resource(ResourceAbs):
    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {
        "advanced_configuration",
    }
    advanced_configuration: Optional[AdvancedConfiguration] = None

    def __post_init__(self):
        if self.advanced_configuration is not None and not isinstance(
            self.advanced_configuration, AdvancedConfiguration
        ):
            assert isinstance(self.advanced_configuration, dict), (
                f"Expected advanced_configuration to be a AdvancedConfiguration or a dict, got {type(self.advanced_configuration)}"
            )
            self.advanced_configuration = AdvancedConfiguration(**self.advanced_configuration)


def test_generate_resource_variables(file_regression):
    variables_tf = generate_resource_variables(
        Resource,
        ResourceGenConfig(name="mongodbatlas_advanced_cluster", skip_variables_extra={"labels"}),
    )
    variables_tf = format_tf_content(variables_tf)
    assert "default_write_concern" in variables_tf
    assert "default_read_concern" not in variables_tf
    file_regression.check(variables_tf, extension=".tf", basename="advanced_configuration")
