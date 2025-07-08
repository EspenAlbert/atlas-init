from pathlib import Path
from model_lib import StaticSettings


class TfDepSettings(StaticSettings):
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
