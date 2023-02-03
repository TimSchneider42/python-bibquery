import logging
import traceback
from typing import Iterable

from .bibquery import BibQuery, BibQueryException

logger = logging.getLogger("BibQuery")


def query(url: str):
    with BibQuery() as bq:
        return bq.query(url)


def query_batch(urls: Iterable[str]):
    results = {}
    with BibQuery() as bq:
        for url in urls:
            try:
                results[url] = bq.query(url)
            except BibQueryException:
                logger.error(f"Encountered error when trying to obtain BibTeX entry of {url}:\n")
                traceback.print_exc()
    return results
