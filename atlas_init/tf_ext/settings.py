import logging
from pathlib import Path
import re
from typing import ClassVar, Self

from model_lib import Entity, StaticSettings
from pydantic import model_validator
from zero_3rdparty.file_utils import ensure_parents_write_text
from zero_3rdparty.str_utils import ensure_suffix

from atlas_init.tf_ext.args import ENV_NAME_REPO_PATH_ATLAS_PROVIDER, TF_CLI_CONFIG_FILE_ENV_NAME

logger = logging.getLogger(__name__)

_atlas_provider_installation = re.compile(r'"mongodb/mongodbatlas"\s*=\s*"(?P<repo_path>[^"]+)/bin"')


def parse_atlas_path_from_tf_cli_config_file(tf_cli_config_file: Path | None) -> Path | None:
    assert tf_cli_config_file, "tf_cli_config_file is required to parse atlas path"
    text = tf_cli_config_file.read_text()
    if match := _atlas_provider_installation.search(text):
        return Path(match.group("repo_path"))
    return None


_tfrc_template = """\
provider_installation {
  dev_overrides {
    "mongodb/mongodbatlas" = "REPO_PATH_TF_PROVIDER"
  }
  direct {}
}
"""


def tf_cli_config_file_content(repo_path_atlas: Path | None) -> str:
    assert repo_path_atlas, "repo_path_atlas is required to export tf_cli_config_file"
    return _tfrc_template.replace("REPO_PATH_TF_PROVIDER", ensure_suffix(str(repo_path_atlas), "/bin"))


def resource_type_name_no_provider(provider_name: str, resource_type: str) -> str:
    return resource_type.removeprefix(provider_name).strip("_")


class RepoOut(Entity):
    base: Path

    @property
    def resource_modules(self) -> Path:
        return self.base / "resource_modules"

    def resource_modules_provider_path(self, provider_name: str) -> Path:
        return self.resource_modules / provider_name

    def resource_module_path(self, provider_name: str, resource_type: str) -> Path:
        return self.resource_modules_provider_path(provider_name) / resource_type_name_no_provider(
            provider_name, resource_type
        )

    def dataclass_path(self, provider_name: str, resource_type: str) -> Path:
        return self.py_provider_module(provider_name) / f"{resource_type}.py"

    @property
    def py_modules(self) -> Path:
        return self.base / "py_modules"

    @property
    def config_path(self) -> Path:
        return self.base / "config"

    def py_provider_module(self, provider: str) -> Path:
        return self.py_modules / f"tf_{provider}"

    def provider_settings_path(self, provider: str) -> Path:
        return self.config_path / f"{provider}.yaml"


class TfExtSettings(StaticSettings):
    ENV_NAME_REPO_PATH_ATLAS_PROVIDER: ClassVar[str] = ENV_NAME_REPO_PATH_ATLAS_PROVIDER
    ENV_NAME_TF_CLI_CONFIG_FILE: ClassVar[str] = TF_CLI_CONFIG_FILE_ENV_NAME

    repo_path_atlas_provider: Path | None = None
    tf_cli_config_file: Path | None = None
    repo_out_path: Path | None = None

    @model_validator(mode="after")
    def infer_repo_path_atlas(self) -> Self:
        if self.repo_path_atlas_provider is None and self.tf_cli_config_file is None:
            raise ValueError("repo_path_atlas or tf_cli_config_file must be set")
        if self.repo_path_atlas_provider is None:
            self.repo_path_atlas_provider = parse_atlas_path_from_tf_cli_config_file(self.tf_cli_config_file)
        if self.tf_cli_config_file is None:
            cli_config_file_content = tf_cli_config_file_content(self.repo_path_atlas_provider)
            self.tf_cli_config_file = self.static_root / "dev.tfrc"
            ensure_parents_write_text(self.tf_cli_config_file, cli_config_file_content)
        if self.tf_cli_config_file:
            tf_cli_repo_path = parse_atlas_path_from_tf_cli_config_file(self.tf_cli_config_file)
            assert tf_cli_repo_path == self.repo_path_atlas_provider, (
                f"tf_cli_config_file does not match repo_path_atlas_provider {tf_cli_repo_path} != {self.repo_path_atlas_provider}"
            )
        return self

    @property
    def repo_out(self) -> RepoOut:
        assert self.repo_out_path, "repo_out_path is required"
        return RepoOut(base=self.repo_out_path)

    @property
    def atlas_graph_path(self) -> Path:
        return self.static_root / "atlas_graph.yaml"

    @property
    def vars_file_path(self) -> Path:
        return self.static_root / "tf_vars.yaml"

    @property
    def vars_external_file_path(self) -> Path:
        return self.static_root / "tf_vars_external.yaml"

    @property
    def resource_types_file_path(self) -> Path:
        return self.static_root / "tf_resource_types.yaml"

    @property
    def resource_types_external_file_path(self) -> Path:
        return self.static_root / "tf_resource_types_external.yaml"

    @property
    def schema_resource_types_path(self) -> Path:
        return self.static_root / "tf_schema_resource_types.yaml"

    @property
    def schema_resource_types_deprecated_path(self) -> Path:
        return self.static_root / "tf_schema_resource_types_deprecated.yaml"

    @property
    def api_calls_path(self) -> Path:
        return self.static_root / "tf_api_calls.yaml"

    def pagination_output_path(self, query_string: str) -> Path:
        return self.static_root / "pagination_output" / f"query_is_{query_string or 'empty'}.md"

    @property
    def new_res_path(self) -> Path:
        return self.static_root / "newres"

    @property
    def modules_out_path(self) -> Path:
        return self.static_root / "modules"

    @property
    def attribute_description_file_path(self) -> Path:
        return self.static_root / "attribute_description.yaml"

    @property
    def attribute_description_manual_file_path(self) -> Path:
        return self.static_root / "attribute_description_manual.yaml"

    @property
    def attribute_resource_descriptions_file_path(self) -> Path:
        return self.static_root / "attribute_resource_descriptions.yaml"

    @property
    def attribute_resource_descriptions_manual_file_path(self) -> Path:
        return self.static_root / "attribute_resource_descriptions_manual.yaml"

    @property
    def output_plan_dumps(self) -> Path:
        return self.static_root / "output_plan_dumps"

    @property
    def plan_diff_output_path(self) -> Path:
        return self.static_root / "plan_diff_output"

    def provider_cache_dir(self, provider_name: str) -> Path:
        return self.cache_root / "provider_cache" / provider_name

    @property
    def variable_plan_resolvers_file_path(self) -> Path:
        return self.static_root / "variable_plan_resolvers.yaml"

    @property
    def variable_plan_resolvers_dumped_file_path(self) -> Path:
        return self.static_root / "variable_plan_resolvers_dumped.yaml"


def init_tf_ext_settings(*, allow_empty_out_path: bool = False) -> TfExtSettings:
    settings = TfExtSettings.from_env()
    assert settings
    logger.info("env-vars ready: ✅")
    logger.info(f"repo_path_atlas: {settings.repo_path_atlas_provider}")
    logger.info(f"tf_cli_config_file: {settings.tf_cli_config_file}")
    if not allow_empty_out_path:
        assert settings.repo_out
    logger.info(f"Repo out path is: {settings.repo_out_path}")
    return settings
