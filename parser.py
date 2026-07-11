from __future__ import annotations

import json
from typing import Any

import pandas as pd

from utils import normalize_provider, normalize_text


class TableauParser:
    def __init__(self) -> None:
        self.columns: list[str] = []

    def parse_records(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        data = payload.get("data") or payload.get("response") or {}
        if isinstance(data, dict):
            for key in ("data", "rows", "values"):
                if key in data:
                    data = data[key]
                    break
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    records.append(item)
                elif isinstance(item, list):
                    records.append({str(i): value for i, value in enumerate(item)})
        return records

    def normalize_dataframe(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        cleaned = dataframe.copy()
        for column in cleaned.columns:
            cleaned[column] = cleaned[column].apply(lambda value: normalize_text(value))
        if "Fiber Provider(s)" in cleaned.columns:
            cleaned["Fiber Provider(s)"] = cleaned["Fiber Provider(s)"].apply(normalize_provider)
        cleaned = cleaned.replace({"": pd.NA})
        cleaned = cleaned.dropna(how="all")
        cleaned = cleaned.drop_duplicates(subset=[col for col in cleaned.columns if col], keep="first")
        return cleaned
