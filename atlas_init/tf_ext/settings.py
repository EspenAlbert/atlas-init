from pathlib import Path
from model_lib import StaticSettings


class TfDepSettings(StaticSettings):
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
