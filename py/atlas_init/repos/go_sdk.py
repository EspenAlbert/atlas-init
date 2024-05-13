from pathlib import Path


def go_sdk_breaking_changes(
    repo_path: Path, go_sdk_rel_path: str = "../atlas-sdk-go"
) -> Path:
    rel_path = "tools/releaser/breaking_changes"
    breaking_changes_dir = repo_path / go_sdk_rel_path / rel_path
    breaking_changes_dir = breaking_changes_dir.absolute()
    assert (
        breaking_changes_dir.exists()
    ), f"not found breaking_changes={breaking_changes_dir}"
    return breaking_changes_dir
