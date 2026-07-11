from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from requests import Response
from tqdm import tqdm

from config import LOGS_DIR, RETRY_DELAYS, MAX_RETRIES


logger = logging.getLogger("tableau_scraper")


def setup_logging(log_file: str = "scraper.log") -> None:
    log_path = LOGS_DIR / log_file
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def normalize_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, str):
        text = value.strip()
        text = re.sub(r"\s+", " ", text)
        return text
    return str(value)


def normalize_provider(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    text = re.sub(r"\s*,\s*", ", ", text)
    text = text.replace(";", ",")
    return text


def retry_request(method: str, url: str, **kwargs: Any) -> Response:
    last_error: Exception | None = None
    session = kwargs.pop("session", None)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if session is not None:
                response = session.request(method, url, timeout=60, **kwargs)
            else:
                response = requests.request(method, url, timeout=60, **kwargs)
            if response.status_code in {429, 403, 500, 502, 503, 504}:
                raise requests.HTTPError(f"status={response.status_code}")
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("Retry %s/%s for %s due to %s", attempt, MAX_RETRIES, url, exc)
            if attempt >= MAX_RETRIES:
                raise
            time.sleep(RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)])
    raise RuntimeError(f"Request failed: {last_error}")


def stream_csv(output_path: Path, dataframe: pd.DataFrame) -> None:
    dataframe.to_csv(output_path, index=False, encoding="utf-8-sig")


def stream_excel(output_path: Path, dataframe: pd.DataFrame) -> None:
    dataframe.to_excel(output_path, index=False, engine="openpyxl")


def iter_chunks(records: list[dict[str, Any]], chunk_size: int = 10000):
    for index in range(0, len(records), chunk_size):
        yield records[index:index + chunk_size]


def progress_bar(total: int) -> tqdm:
    return tqdm(total=total, unit="rows", desc="Extracting")
