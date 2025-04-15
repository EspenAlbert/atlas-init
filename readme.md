# Atlas Init - A CLI for developing integrations with MongoDB Atlas
<p align="center">
    <a href="https://pypi.org/project/atlas-init/" target="_blank">
        <img src="https://img.shields.io/pypi/v/atlas-init.svg">
    </a>
    <a href="https://pypi.org/project/atlas-init/" target="_blank">
        <img src="https://img.shields.io/pypi/pyversions/atlas-init.svg">
    </a>
    <a href="https://github.com/EspenAlbert/py-libs/blob/main/LICENSE" target="_blank">
            <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
    </a>
    <a href="https://codecov.io/github/EspenAlbert/atlas-init" target="_blank">
            <img src="https://codecov.io/github/EspenAlbert/atlas-init/graph/badge.svg?token=DR7FDJXNZY" alt="Coverage">
    </a>
</p>

Currently, used with
- <https://github.com/mongodb/terraform-provider-mongodbatlas>
- <https://github.com/mongodb/mongodb/mongodbatlas-cloudformation-resources>
- see [atlas_init#repo_aliases](atlas_init.yaml) for an up-to-date list

## Quickstart
Recommended as a tool with [uvx](https://docs.astral.sh/uv/guides/tools/#running-tools)
```shell
uvx atlas-init # help info
uvx atlas-init tf # help for tf specific commands
uvx atlas-init cfn # help for cfn specific commands
```

## Profile Configuration
1. [Create an organization](https://cloud-dev.mongodb.com/v2#/preferences/organizations)
2. Go to `access_manager` and click `Create Api Key`: <https://cloud-dev.mongodb.com/v2#/org/{ORG_ID_IN_URL_FROM_1}/access/apiKeys>
   - Tick all permissions
3. create directories and store a file in `profiles/default/.env-manual` (`ATLAS_INIT_PROFILES_PATH/{profile_name}/.env-manual`)

```env
AWS_PROFILE=REPLACE_ME # your AWS profile used to create resources or other env-vars supported by AWS TF provider
MONGODB_ATLAS_ORG_ID=REPLACE_ME # ORG_ID_IN_URL_FROM_1
MONGODB_ATLAS_PUBLIC_KEY=REPLACE_ME # with 2
MONGODB_ATLAS_PRIVATE_KEY=REPLACE_ME # with 2
ATLAS_INIT_PROJECT_NAME=YOUR_NAME # the name of the project
MONGODB_ATLAS_BASE_URL=https://cloud-dev.mongodb.com/ # replace with https://cloud.mongodb.com/ if you are not a MongoDB Employe

# optional
TF_VAR_federated_settings_id=REPLACE_ME # will need to add organization: <https://cloud-dev.mongodb.com/v2#/federation/{FEDERATION_SETTINGS_ID}/organizations> (see internal testing wiki)

# if you want to use your locally built MongoDB atlas provider
# see appendix for details on the content
TF_CLI_CONFIG_FILE=REPLACE_ME/dev.tfrc

# if you plan developing with cloudformation
ATLAS_INIT_CFN_PROFILE=YOUR_NAME
ATLAS_INIT_CFN_REGION=eu-south-2 # find a region with few other profiles
```

## Local development

```shell
git clone https://github.com/EspenAlbert/atlas-init
cd atlas-init
brew install pre-commit uv hatch
# https://github.com/astral-sh/uv <-- python packaging lightning fast
# https://hatch.pypa.io/latest/ <-- uv compatible build system for python

pre-commit install

# check that everything works
pre-commit run --all-files

# configure your virtualenv and validate the tests are working
cd py
hatch test
export VENV_DIR=$(hatch env find hatch-test | grep py3.12) # hatch venv path for env=hatch-test
export VENV_PYTHON=$VENV_DIR/bin/python
$VENV_PYTHON # ensure you are in shell with python3.12 (cmd+d to exit)
cd .. # back to repo root

# open in your IDE with virtualenv enabled
code .
# select venv path from $VENV_PYTHON output as python interpreter
# in vs code: use cmd+p and `Python: select interpreter` command

# to make it easy to invoke from any terminal (replace .zprofile with your terminal)
export pypath=$(git rev-parse --show-toplevel)/py
echo "alias atlas_init='export PYTHONPATH=$pypath && \"$VENV_PYTHON\" -m atlas_init'" >> ~/.zprofile

# test that it works
atlas_init # should show how to use the cli
```

### CI Installation Tests (`pip install` local wheel)
- `uv sync`
  - creates a local `.venv` builds the wheel from this repo and installs it
- use `export ATLAS_INIT_PROFILES_PATH=/somewhere/to/store/your/env-vars/and/tf/state`


## Appendix

### Configuring vscode to use your env vars
- add to your `settings.json`

```json
{
    "go.testEnvFile": "/{SOME_PREFIX}/atlas-init/profiles/default/.env-vscode",
}
```

### Content of `dev.tfrc`
usually, it will look something like this:

```hcl

provider_installation {
 
  dev_overrides {
 
    "mongodb/mongodbatlas" = "REPO_PATH_TF_PROVIDER/bin"
 
  }
 
  direct {}
 
}
```

### Re-generating the lock files

```shell
terraform providers lock \
    -platform=darwin_amd64 \
    -platform=linux_amd64 \
    -platform=darwin_arm64 \
    -platform=linux_arm64
    # -platform=windows_amd64 \
```