from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR = BASE_DIR / "logs"

URL = "https://public.tableau.com/views/_17255232362800/sheet11?:showVizHome=no"
TARGET_CSV = OUTPUT_DIR / "fiber_data.csv"
TARGET_XLSX = OUTPUT_DIR / "fiber_data.xlsx"
SAMPLE_CSV = OUTPUT_DIR / "sample.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

RETRY_DELAYS = [1, 3, 5, 10]
MAX_RETRIES = 5

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
