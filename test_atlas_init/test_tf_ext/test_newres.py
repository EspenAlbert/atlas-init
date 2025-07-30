import os
from ask_shell import run_and_wait
from ask_shell.models import _resolve_binary
import pytest
from zero_3rdparty.file_utils import clean_dir
from atlas_init.tf_ext.newres import prepare_newres


@pytest.mark.skipif(os.environ.get("MANUAL", "") == "", reason="needs os.environ[MANUAL]")
def test_prepare_newres(tf_ext_settings_repo_path):
    new_res = tf_ext_settings_repo_path.new_res_path
    prepare_newres(new_res)
    resource_out_paths = {
        "mongodbatlas_organization": new_res / "out_org",
        "mongodbatlas_project": new_res / "out_project",
        "mongodbatlas_advanced_cluster": new_res / "out_advanced_cluster",
    }
    terraform_binary_path = _resolve_binary("terraform", cwd=new_res)
    old_path = os.environ.get("PATH", "")
    env_with_tf = {"PATH": f"{old_path}:{terraform_binary_path.parent}"}
    for resource, out_path in resource_out_paths.items():
        clean_dir(out_path, recreate=True)
        # Terraform is required as it uses TerraformExec
        run_and_wait(f"go run main.go -dir {out_path} -r {resource}", cwd=new_res, env=env_with_tf)
        assert (out_path / "main.tf").exists()
