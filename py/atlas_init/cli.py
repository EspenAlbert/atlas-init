import logging
from atlas_init.env_vars import AtlasInitSettings
from rich.logging import RichHandler


def run():
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )
    settings = AtlasInitSettings.safe_settings()
    config = settings.config
    

