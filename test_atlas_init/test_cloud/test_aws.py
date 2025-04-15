from logging import Logger
from pathlib import Path
from typing import Callable
from atlas_init.cloud.aws import download_from_s3
from atlas_init.settings.env_vars import FILENAME_ENV_MANUAL
from zero_3rdparty.file_utils import ensure_parents_write_text

def mocked_binary_command(callback: Callable[[str, Path], None]):
    def inner(
        binary_name: str, command: str, cwd: Path, logger: Logger, env: dict | None = None, *, dry_run: bool = False
    ) -> bool:
        assert binary_name == "aws"
        callback(command, cwd)
        return True
    return inner

_env_manual_example = """\
TF_CLI_CONFIG_FILE=/Users/user/atlas-init/tf/dev.tfrc
AWS_PROFILE=ai
AWS_REGION=us-east-1
MONGODB_ATLAS_ORG_ID=a8bcf6ce0f722a1507105aa5
"""

_env_manual_expected = """\
TF_CLI_CONFIG_FILE=/Users/user/atlas-init/tf/dev.tfrc
AWS_REGION=us-east-1
MONGODB_ATLAS_ORG_ID=a8bcf6ce0f722a1507105aa5
"""
_normal_file = "some file content"

def test_download_from_s3(monkeypatch, tmp_path):
    module_path = download_from_s3.__module__
    profile_path = tmp_path / "profiles/test"

    def run_assertions(command: str, cwd: Path):
        expected_prefix = "s3 sync s3://s3_bucket//profiles/test/ "
        assert command.startswith(expected_prefix)
        copy_dir = Path(command.removeprefix(expected_prefix))
        assert copy_dir.parent.exists()
        ensure_parents_write_text(copy_dir / FILENAME_ENV_MANUAL, _env_manual_example)
        ensure_parents_write_text(copy_dir / "normal.txt", _normal_file)

    monkeypatch.setattr(f"{module_path}.run_binary_command_is_ok", mocked_binary_command(run_assertions))
    download_from_s3(profile_path, "s3_bucket", "")
    files = list(profile_path.glob("*"))
    assert len(files) == 2
    assert (profile_path / FILENAME_ENV_MANUAL).read_text() == _env_manual_expected
    assert (profile_path / "normal.txt").read_text() == _normal_file
