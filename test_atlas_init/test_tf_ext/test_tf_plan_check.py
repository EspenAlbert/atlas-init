import pytest
from atlas_init.repos.path import GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS
from atlas_init.tf_ext.tf_ws import as_tfvars_env, update_dumped_vars


def test_update_dumped_vars(tmp_path, monkeypatch: pytest.MonkeyPatch):
    vars_path = tmp_path / "variables_plan.yaml"
    extra_env_vars = {
        key: f"{key}_value"
        for key in [
            "AWS_REGION",
            "MONGODB_ATLAS_BASE_URL",
            "MONGODB_ATLAS_ORG_ID",
            "MONGODB_ATLAS_PRIVATE_KEY",
            "MONGODB_ATLAS_PROJECT_ID",
            "MONGODB_ATLAS_PUBLIC_KEY",
        ]
    }
    # sourcery skip: no-loop-in-tests
    for key, value in extra_env_vars.items():
        monkeypatch.setenv(key, value)
    from atlas_init.tf_ext.tf_ws import owner_project_name

    monkeypatch.setattr(
        f"{update_dumped_vars.__module__}.{owner_project_name.__name__}",
        lambda _: GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS,
    )
    monkeypatch.setenv("AWS_PROFILE", "DUMMY")
    variables = update_dumped_vars(vars_path, "")
    assert vars_path.exists()
    star_pattern = variables.paths["*"]
    variables_tf = tmp_path / "variables.tf"
    variables_tf.write_text("""
variable "project_name" {
    type = string
}
variable "atlas_private_key" {
    type = string
}
    """)
    tfvars_files, resolved_vars = variables.resolve_vars(tmp_path, variables_tf.parent, "variables.tf")
    assert not tfvars_files
    assert len(resolved_vars) == 2
    project_var = next(var for var in star_pattern if "project*" in var.var_matches)
    priv_key_var = next(var for var in star_pattern if getattr(var, "name", "") == "MONGODB_ATLAS_PRIVATE_KEY")
    assert resolved_vars["project_name"] == project_var
    assert resolved_vars["atlas_private_key"] == priv_key_var
    resolved_tf_vars, resolved_env_vars = as_tfvars_env(resolved_vars)
    assert resolved_tf_vars == {
        "project_name": project_var.value,
    }
    assert resolved_env_vars == {
        "MONGODB_ATLAS_PRIVATE_KEY": "MONGODB_ATLAS_PRIVATE_KEY_value",
    }
