import os
from pathlib import Path
import pytest


@pytest.fixture()
@pytest.mark.skipif(os.environ.get("TF_VARIABLES_PATH", "") == "", reason="needs os.environ[TF_VARIABLES_PATH]")
def tf_variables_path():
    return Path(os.environ["TF_VARIABLES_PATH"])
