import dotenv

from atlas_init.settings.env_vars import (
    AtlasInitSettings,
    as_env_var_name,
    dump_manual_dotenv_from_env,
)
from atlas_init.settings.path import repo_path_rel_path


def test_default_settings(monkeypatch):
    monkeypatch.setenv(as_env_var_name("test_suites"), "suite1,suite2 suite3")
    settings = AtlasInitSettings.safe_settings()
    print(settings)
    print(f"repo_path,rel_path={repo_path_rel_path()}")
    assert settings.test_suites_parsed == ["suite1", "suite2", "suite3"]


def test_dumping_default_settings(monkeypatch, tmp_path):
    out_file = tmp_path / ".env"
    AtlasInitSettings.safe_settings()
    dump_manual_dotenv_from_env(out_file)
    loaded = dotenv.dotenv_values(out_file)
    assert sorted(loaded.keys()) == [
        "ATLAS_INIT_PROJECT_NAME",
        "AWS_PROFILE",
        "MONGODB_ATLAS_BASE_URL",
        "MONGODB_ATLAS_ORG_ID",
        "MONGODB_ATLAS_PRIVATE_KEY",
        "MONGODB_ATLAS_PUBLIC_KEY",
        "TF_CLI_CONFIG_FILE",
    ]
