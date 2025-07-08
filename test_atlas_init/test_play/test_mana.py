import logging
import os
from pathlib import Path
import pytest
from model_lib import parse_list

logger = logging.getLogger(__name__)


@pytest.mark.skipif(os.environ.get("GUILD_FILE_PATH", "") == "", reason="needs os.environ[GUILD_FILE_PATH]")
def test_parsing_guild_names():
    path = os.environ["GUILD_FILE_PATH"]
    path2 = os.environ["GUILD_FILE_PATH2"]
    payload = parse_list(Path(path))
    payload2 = parse_list(Path(path2))
    names = {name for guild_dict in payload if (name := guild_dict.get("guild_name"))}
    names2 = {name for guild_dict in payload2 if (name := guild_dict.get("guild_name"))}
    extra_in2 = names2 - names
    logger.info(f"extra_in2: {'\n'.join(extra_in2)}")
    extra_in1 = names - names2
    logger.info(f"extra_in1: {'\n'.join(extra_in1)}")
