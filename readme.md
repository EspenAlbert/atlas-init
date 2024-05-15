# Atlas Init - A CLI for developing with MongoDB Atlas

Currently, used with
- <https://github.com/mongodb/terraform-provider-mongodbatlas>
- <https://github.com/mongodb/mongodb/mongodbatlas-cloudformation-resources>
- see [atlas_init#repo_aliases](atlas_init.yaml) for an up-to-date list

## Requirements
1. [Create an organization](https://cloud-dev.mongodb.com/v2#/preferences/organizations)
2. Go to `access_manager` and click `Create Api Key`: <https://cloud-dev.mongodb.com/v2#/org/{ORG_ID_IN_URL_FROM_1}/access/apiKeys>
   - Tick all permissions
3. create directories and store a file in `profiles/default/.env-manual` (`ATLAS_INIT_PROFILES_PATH/{profile_name}/.env-manual`)

```env
export AWS_PROFILE=REPLACE_ME # your AWS profile used to create resources or other env-vars supported by AWS TF provider
export MONGODB_ATLAS_ORG_ID=REPLACE_ME # ORG_ID_IN_URL_FROM_1
export MONGODB_ATLAS_PUBLIC_KEY=REPLACE_ME # with 2
export MONGODB_ATLAS_PRIVATE_KEY=REPLACE_ME # with 2
export ATLAS_INIT_PROJECT_NAME=YOUR_NAME # the name of the project
export MONGODB_ATLAS_BASE_URL=https://cloud-dev.mongodb.com/ # replace with https://cloud.mongodb.com/ if you are not a MongoDB Employe

# optional
TF_VAR_federated_settings_id=REPLACE_ME # will need to add organization: <https://cloud-dev.mongodb.com/v2#/federation/{FEDERATION_SETTINGS_ID}/organizations> (see internal testing wiki)

# if you want to use your locally built MongoDB atlas provider
# see appendix for details on the content
export TF_CLI_CONFIG_FILE=REPLACE_ME/dev.tfrc

# if you plan developing with cloudformation
export ATLAS_INIT_CFN_PROFILE=YOUR_NAME
export ATLAS_INIT_CFN_REGION=eu-south-2 # find a region with few other profiles
```

## Two modes of running

### 1. `pip install` normal user
```shell
source .venv/bin/activate # ensure you are in your preferred python env
(uv) pip install atlas-init
# use export ATLAS_INIT_PROFILES_PATH=/somewhere/to/store/your/env-vars/and/tf/state
```

### 2. Local development, run from github repo

```shell
brew install pre-commit uv hatch
# https://github.com/astral-sh/uv <-- python packaging lightning fast
# https://hatch.pypa.io/latest/ <-- uv compatible build system for python

pre-commit install

# check that everything works
pre-commit run --all-files
cd py
hatch test
VENV_PATH=$(hatch env find hatch-test) # your venv path
cd ..

# open in your IDE
code .
# select venv path from $VENV_PATH output

# to make it easy to invoke from any terminal
export pyexe=$(which python) # VENV_PATH above
export pypath=$(pwd)/py
echo "alias atlas_init='export PYTHONPATH=$pypath && \"$pyexe\" -m atlas_init'" >> ~/.zprofile # replace with your shell profile
```

### 3. `pip install` local wheel
- will be used by the CI in other repos
- [atlasci_local_install](atlasci_local_install.sh)
  - creates a local `.venv` builds the wheel from this repo and installs it
- use `export ATLAS_INIT_PROFILES_PATH=/somewhere/to/store/your/env-vars/and/tf/state`

## Commands

```shell
cd terraform/cfn/{YOUR_RESOURCE_PATH}
# if you used `pip install` replace `atlas_init` with `atlasci`
atlas_init # help info
atlas_init # initialize the terraform providers
atlas_init tf # help for tf specific commands
atlas_init cfn # help for cfn specific commands
atals_init apply # `terraform apply`
# use cmd+v if you plan on using other tools, e.g., cfn make commands
# see appendix on how to configure .vscode test env-vars
atals_init destroy # `terraform destroy`
```


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
