import logging
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Callable, TypeVar

from zero_3rdparty.object_name import as_name

from atlas_init.cli_args import REGIONS

logger = logging.getLogger(__name__)

T = TypeVar("T")


def run_in_regions(call: Callable[[str], T], regions: list[str] | None = None) -> dict[str, T]:  # type: ignore
    futures = {}
    name = as_name(call)
    regions: list[str] = regions or REGIONS  # type: ignore
    with ThreadPoolExecutor(max_workers=10) as pool:
        for region in regions:
            future = pool.submit(call, region)
            futures[future] = region
        done, not_done = wait(futures.keys(), timeout=300)
        for f in not_done:
            logger.warning(f"timeout for {name} in region = {futures[f]}")
    region_responses: dict[str, T] = {}
    for f in done:
        region: str = futures[f]
        try:
            response = f.result()
            region_responses[region] = response
        except Exception as e:
            logger.exception(e)
            logger.exception(f"failed to call {name} in region = {region}, error 👆")
    return region_responses
