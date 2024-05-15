# Atlas Init - A CLI for developing with MongoDB Atlas

Currently, used with
- <https://github.com/mongodb/terraform-provider-mongodbatlas>
- <https://github.com/mongodb/mongodb/mongodbatlas-cloudformation-resources>
- see [atlas_init#repo_aliases](atlas_init.yaml) for an up-to-date list

## Installation for development

```shell
brew install pre-commit
pre-commit install

# install asdf https://asdf-vm.com/guide/getting-started.html
asdf install # will ensure you have the right versions of python and terraform installed
# install python 3.11.8
brew install uv # https://github.com/astral-sh/uv <-- python packaging lightning fast
uv venv -p 3.11.8
source .venv/bin/activate
uv pip install -r requirements.txt
export pyexe=$(which python)
export pypath=$(pwd)/py
echo "alias atlas_init='export PYTHONPATH=$pypath && $pyexe -m atlas_init'" >> ~/.zprofile # replace with your shell profile
```

## Configuring env-vars

```shell
export AWS_PROFILE=REPLACE_ME # your AWS profile used to create resources
export MONGODB_ATLAS_ORG_ID=REPLACE_ME # your organization id
export MONGODB_ATLAS_PRIVATE_KEY=REPLACE_ME
export MONGODB_ATLAS_PUBLIC_KEY=REPLACE_ME
export ATLAS_INIT_PROJECT_NAME=YOUR_NAME
export MONGODB_ATLAS_BASE_URL=https://cloud-dev.mongodb.com/ # replace with https://cloud.mongodb.com/ if you are not a MongoDB Employe
export MONGODB_ATLAS_ENABLE_PREVIEW=true # if you might be using preview resources

# if you want to use your locally built MongoDB atlas provider
# see appendix for details on the content
export TF_CLI_CONFIG_FILE=REPLACE_ME/dev.tfrc

# if you plan developing with cloudformation
export ATLAS_INIT_CFN_PROFILE=YOUR_NAME
export ATLAS_INIT_CFN_REGION=eu-south-2 # find a region with few other profiles

atlas_init
# will store your variables in ./profiles/default/.env_manual
# and error if something is missing
```

## Commands

```shell
cd terraform/cfn/{YOUR_RESOURCE_PATH}
atlas_init # check your env-vars exist & `terraform init`
atals_init apply # `terraform apply`
# use cmd+v if you plan on using other tools
# see output on how to configure .vscode test env-vars
atals_init destroy # `terraform destroy`
```


## Appendix

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
