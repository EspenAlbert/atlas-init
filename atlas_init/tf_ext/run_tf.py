from ask_shell import new_task, run_and_wait
from pathlib import Path


def validate_tf_workspace(
    tf_workdir: Path, *, tf_cli_config_file: Path | None = None, env_extra: dict[str, str] | None = None
):
    terraform_commands = [
        "terraform init",
        "terraform fmt .",
        "terraform validate .",
    ]
    env_extra = env_extra or {}
    if tf_cli_config_file:
        env_extra["TF_CLI_CONFIG_FILE"] = str(tf_cli_config_file)
    with new_task("Terraform Module Validate Checks", total=len(terraform_commands)) as task:
        for command in terraform_commands:
            attempts = 3 if command == "terraform init" else 1  # terraform init can fail due to network issues
            run_and_wait(command, cwd=tf_workdir, env=env_extra, attempts=attempts)
            task.update(advance=1)
