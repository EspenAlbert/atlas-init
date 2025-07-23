from pathlib import Path
from atlas_init.tf_ext.provider_schema import get_providers_tf
from zero_3rdparty.file_utils import ensure_parents_write_text


def dump_versions_tf(module_path: Path, skip_python: bool = False) -> Path:
    provider_path = module_path / "versions.tf"
    if not provider_path.exists():
        ensure_parents_write_text(provider_path, get_providers_tf(skip_python=skip_python))
    return provider_path
