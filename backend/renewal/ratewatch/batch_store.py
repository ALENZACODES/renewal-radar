"""Durable Ratewatch CSV batch store: active pointer, last-good, quarantine.

Layout under ``RATEWATCH_DATA/csv_batches`` (default ``data/ratewatch/csv_batches``)::

    pointer.json          atomic active pointer {sha256, imported_at, row_count, status}
    last_good.json        last successfully activated batch (never truncated on quarantine)
    batches/<sha>.csv     accepted batch body (immutable)
    batches/<sha>.meta.json
    quarantine/<sha>.csv  rejected body retained for audit
    quarantine/<sha>.json reasons + compared_to

No SQL migration required. Readers call :meth:`BatchStore.active_rows` only.
Same SHA-256 as active is a no-op.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .csv_batch import (
    HEADERS,
    ParseResult,
    RateRow,
    parse_rate_csv,
    sanity_vs_last_good,
)
from .paths import DATA

STORE_DIRNAME = 'csv_batches'
_LOCK = threading.RLock()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class BatchStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else (DATA / STORE_DIRNAME)
        self.batches = self.root / 'batches'
        self.quarantine = self.root / 'quarantine'
        self.pointer_path = self.root / 'pointer.json'
        self.last_good_path = self.root / 'last_good.json'
        self.root.mkdir(parents=True, exist_ok=True)
        self.batches.mkdir(parents=True, exist_ok=True)
        self.quarantine.mkdir(parents=True, exist_ok=True)

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return None

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        os.replace(tmp, path)

    def _atomic_write_bytes(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def pointer(self) -> dict[str, Any] | None:
        return self._read_json(self.pointer_path)

    def last_good(self) -> dict[str, Any] | None:
        return self._read_json(self.last_good_path)

    def _load_rows_for_sha(self, sha: str, *, from_quarantine: bool = False) -> list[RateRow]:
        base = self.quarantine if from_quarantine else self.batches
        path = base / f'{sha}.csv'
        if not path.is_file():
            return []
        parsed = parse_rate_csv(path.read_bytes())
        return list(parsed.rows) if parsed.ok else []

    def active_rows(self) -> list[RateRow]:
        """Readers only see the active (pointer) batch."""
        with _LOCK:
            ptr = self.pointer()
            if not ptr or ptr.get('status') != 'active':
                return []
            sha = ptr.get('sha256') or ''
            return self._load_rows_for_sha(sha)

    def last_good_rows(self) -> list[RateRow]:
        with _LOCK:
            meta = self.last_good()
            if not meta:
                return []
            return self._load_rows_for_sha(str(meta.get('sha256') or ''))

    def import_csv(self, data: bytes, *, source: str = 'upload') -> dict[str, Any]:
        """Validate, sanity-check, quarantine or atomically activate. Same SHA no-op."""
        with _LOCK:
            parsed = parse_rate_csv(data)
            sha = parsed.sha256
            ptr = self.pointer() or {}
            if ptr.get('sha256') == sha and ptr.get('status') == 'active':
                return {
                    'status': 'noop',
                    'sha256': sha,
                    'message': 'identical to active batch',
                    'row_count': ptr.get('row_count'),
                }

            reasons = list(parsed.errors)
            if parsed.ok:
                reasons.extend(sanity_vs_last_good(parsed.rows, self.last_good_rows() or None))

            if reasons or not parsed.ok:
                return self._quarantine(data, sha, reasons, source=source, parsed=parsed)

            return self._activate(data, sha, parsed, source=source)

    def _quarantine(
        self,
        data: bytes,
        sha: str,
        reasons: list[str],
        *,
        source: str,
        parsed: ParseResult,
    ) -> dict[str, Any]:
        last = self.last_good()
        meta = {
            'sha256': sha,
            'status': 'quarantined',
            'imported_at': _utcnow(),
            'source': source,
            'byte_size': len(data),
            'row_count': len(parsed.rows),
            'reasons': reasons,
            'headers': list(HEADERS),
            'compared_to_last_good': (last or {}).get('sha256'),
            # last-good pointer is intentionally NOT modified
            'last_good_preserved': True,
        }
        self._atomic_write_bytes(self.quarantine / f'{sha}.csv', data)
        self._atomic_write_json(self.quarantine / f'{sha}.json', meta)
        # Active pointer unchanged; last_good unchanged.
        return {
            'status': 'quarantined',
            'sha256': sha,
            'reasons': reasons,
            'row_count': len(parsed.rows),
            'active_sha256': (self.pointer() or {}).get('sha256'),
            'last_good_sha256': (last or {}).get('sha256'),
        }

    def _activate(
        self,
        data: bytes,
        sha: str,
        parsed: ParseResult,
        *,
        source: str,
    ) -> dict[str, Any]:
        meta = {
            'sha256': sha,
            'status': 'active',
            'imported_at': _utcnow(),
            'source': source,
            'byte_size': len(data),
            'row_count': len(parsed.rows),
            'lenders': sorted({r.lender for r in parsed.rows}),
            'headers': list(HEADERS),
        }
        # Persist batch body first, then flip pointers atomically via replace.
        self._atomic_write_bytes(self.batches / f'{sha}.csv', data)
        self._atomic_write_json(self.batches / f'{sha}.meta.json', meta)
        self._atomic_write_json(self.pointer_path, meta)
        self._atomic_write_json(self.last_good_path, meta)
        return {
            'status': 'active',
            'sha256': sha,
            'row_count': len(parsed.rows),
            'lenders': meta['lenders'],
            'imported_at': meta['imported_at'],
        }

    def list_quarantine(self, limit: int = 25) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.quarantine.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            meta = self._read_json(path)
            if meta:
                items.append(meta)
            if len(items) >= limit:
                break
        return items


# Process-default store (tests may construct BatchStore(tmp_path)).
default_store = BatchStore()
