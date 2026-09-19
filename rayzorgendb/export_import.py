"""
RayzorgenDB Export / Import

Export collection ke CSV atau JSON.
Import dari CSV atau JSON.
"""

import csv
import json
import os
from typing import Any, Dict, List, Optional


class Exporter:
    """Export collection data."""

    def __init__(self, collection):
        self.collection = collection

    def to_json(self, path: str = None,
                indent: int = 2) -> str:
        """Export to JSON. Return JSON string."""
        records = []
        for r in self.collection.all():
            rec = {
                "id": r.id,
                "data": r.data,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
                "version": r.version,
            }
            records.append(rec)

        text = json.dumps(
            records, indent=indent,
            ensure_ascii=False, default=str,
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        return text

    def to_csv(self, path: str = None,
               fields: List[str] = None) -> str:
        """Export to CSV. Return CSV string."""
        records = self.collection.all()

        if not records:
            return ""

        # Auto-detect fields
        if fields is None:
            seen = set()
            fields = []
            for r in records:
                for k in r.data.keys():
                    if k not in seen:
                        seen.add(k)
                        fields.append(k)

        # Build rows
        rows = []
        for r in records:
            row = {"id": r.id}
            for f in fields:
                row[f] = r.data.get(f, "")
            rows.append(row)

        columns = ["id"] + fields

        # Write to string
        import io
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

        text = buf.getvalue()
        if path:
            with open(path, "w", encoding="utf-8",
                      newline="") as f:
                f.write(text)
        return text


class Importer:
    """Import data ke collection."""

    def __init__(self, collection):
        self.collection = collection

    def from_json(self, source: str) -> int:
        """
        Import dari JSON file atau string.
        Source bisa path atau JSON string.
        """
        if os.path.exists(source):
            with open(source, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = json.loads(source)

        if not isinstance(data, list):
            raise ValueError(
                "JSON harus berupa list of records"
            )

        count = 0
        for item in data:
            # Support dua format:
            # 1. {"id": ..., "data": {...}}
            # 2. {...} langsung
            if isinstance(item, dict) and "data" in item:
                payload = item["data"]
            else:
                payload = item
            self.collection.insert(payload)
            count += 1

        return count

    def from_csv(self, source: str,
                 skip_id: bool = True) -> int:
        """Import dari CSV file."""
        if os.path.exists(source):
            with open(source, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        else:
            import io
            reader = csv.DictReader(io.StringIO(source))
            rows = list(reader)

        count = 0
        for row in rows:
            data = {}
            for k, v in row.items():
                if skip_id and k == "id":
                    continue
                # Auto-convert
                data[k] = self._convert(v)
            self.collection.insert(data)
            count += 1

        return count

    @staticmethod
    def _convert(v: str) -> Any:
        """Convert string to number/bool jika bisa."""
        if v is None:
            return None
        s = str(v).strip()
        if s == "":
            return None
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
        if s.lower() in ("true", "false"):
            return s.lower() == "true"
        return v


__all__ = ["Exporter", "Importer"]
