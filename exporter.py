from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from config import SAMPLE_CSV, TARGET_CSV, TARGET_XLSX
from utils import stream_csv, stream_excel


class DataExporter:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def export(self, dataframe: pd.DataFrame) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stream_csv(TARGET_CSV, dataframe)
        stream_excel(TARGET_XLSX, dataframe)
        sample = dataframe.head(20)
        sample.to_csv(SAMPLE_CSV, index=False, encoding="utf-8-sig")

    def export_chunked(self, dataframe: pd.DataFrame) -> None:
        self.export(dataframe)
