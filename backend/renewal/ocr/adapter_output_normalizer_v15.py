"""V15 normalizers for optional OCR/document-intelligence adapter outputs.

The V14 adapter plan describes how Docling, Unstructured, PaddleOCR, Surya,
Marker and olmOCR can fit into Renewal Radar. V15 adds the next local layer:
small, dependency-free normalizers that accept outputs shaped like those tools
and convert them into one stable Renewal Radar packet.

No external package is imported here. The code accepts plain dictionaries and
lists so adapters can be added later without changing the mortgage intelligence
layer.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any

from .fields import redact_sensitive_text


MAX_TEXT_CHARS = 25000
MAX_SPANS = 500
MAX_TABLES = 80
MAX_ISSUES = 120
DEFAULT_PAGE_NUMBER = 1


class AdapterNormalizationError(ValueError):
    """Adapter output could not be normalized safely."""


@dataclass(frozen=True)
class NormalizedSpan:
    id: str
    page_number: int
    text: str
    kind: str
    source: str
    confidence: float | None
    bbox: tuple[float, float, float, float] | None = None
    metadata: dict[str, Any] | None = None

    def public(self) -> dict:
        data = asdict(self)
        data["bbox"] = list(self.bbox) if self.bbox else None
        data["metadata"] = self.metadata or {}
        return data


@dataclass(frozen=True)
class NormalizedTable:
    id: str
    page_number: int
    source: str
    rows: tuple[tuple[str, ...], ...]
    caption: str | None = None
    confidence: float | None = None

    def public(self) -> dict:
        data = asdict(self)
        data["rows"] = [list(row) for row in self.rows]
        return data


@dataclass(frozen=True)
class NormalizationIssue:
    id: str
    severity: str
    message: str
    source: str
    evidence: tuple[str, ...] = ()

    def public(self) -> dict:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data


def _stable_id(prefix: str, *parts: Any) -> str:
    material = "|".join(str(part) for part in parts)
    digest = hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]
    readable = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-")[:32]
    return f"{readable}-{digest}"


def _clean_text(value: Any, *, max_chars: int = MAX_TEXT_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    return redact_sensitive_text(text[:max_chars])


def _page(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_NUMBER
    return max(1, min(number, 1000))


def _confidence(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence > 1:
        confidence = confidence / 100.0
    return max(0.0, min(confidence, 1.0))


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)):
        return None
    flattened: list[float] = []
    for item in value:
        if isinstance(item, (list, tuple)):
            for child in item:
                try:
                    flattened.append(float(child))
                except (TypeError, ValueError):
                    return None
        else:
            try:
                flattened.append(float(item))
            except (TypeError, ValueError):
                return None
    if len(flattened) < 4:
        return None
    xs = flattened[0::2] if len(flattened) > 4 else [flattened[0], flattened[2]]
    ys = flattened[1::2] if len(flattened) > 4 else [flattened[1], flattened[3]]
    return (min(xs), min(ys), max(xs), max(ys))


def _span(source: str, page_number: Any, text: Any, kind: str,
          confidence: Any = None, bbox: Any = None,
          metadata: dict[str, Any] | None = None) -> NormalizedSpan | None:
    cleaned = _clean_text(text)
    if not cleaned:
        return None
    page = _page(page_number)
    return NormalizedSpan(
        id=_stable_id(f"{source}-{kind}", page, cleaned[:80], confidence),
        page_number=page,
        text=cleaned,
        kind=kind,
        source=source,
        confidence=_confidence(confidence),
        bbox=_bbox(bbox),
        metadata=metadata or {},
    )


def _issue(source: str, severity: str, message: str,
           evidence: tuple[str, ...] = ()) -> NormalizationIssue:
    return NormalizationIssue(
        id=_stable_id(f"{source}-{severity}", message, evidence),
        severity=severity,
        message=message,
        source=source,
        evidence=evidence,
    )


def _rows(value: Any) -> tuple[tuple[str, ...], ...]:
    if value is None:
        return ()
    rows = value
    if isinstance(value, dict):
        rows = value.get("data") or value.get("rows") or value.get("cells") or []
    normalized = []
    if isinstance(rows, str):
        for line in rows.splitlines():
            cells = tuple(_clean_text(cell, max_chars=500) for cell in re.split(r"\s*\|\s*|\t", line) if _clean_text(cell))
            if cells:
                normalized.append(cells)
    elif isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                values = row.get("cells") or row.get("values") or list(row.values())
            else:
                values = row
            if not isinstance(values, (list, tuple)):
                values = [values]
            cells = tuple(_clean_text(cell, max_chars=500) for cell in values if _clean_text(cell))
            if cells:
                normalized.append(cells)
    return tuple(normalized[:200])


def _table(source: str, page_number: Any, rows: Any, caption: Any = None,
           confidence: Any = None) -> NormalizedTable | None:
    normalized_rows = _rows(rows)
    if not normalized_rows:
        return None
    page = _page(page_number)
    clean_caption = _clean_text(caption, max_chars=500) or None
    return NormalizedTable(
        id=_stable_id(f"{source}-table", page, normalized_rows[:3], clean_caption),
        page_number=page,
        source=source,
        rows=normalized_rows,
        caption=clean_caption,
        confidence=_confidence(confidence),
    )


def _extend_limited(target: list, items: list, limit: int) -> None:
    remaining = limit - len(target)
    if remaining <= 0:
        return
    target.extend(items[:remaining])


def normalize_docling_output(payload: dict[str, Any]) -> tuple[list[NormalizedSpan], list[NormalizedTable], list[NormalizationIssue]]:
    spans: list[NormalizedSpan] = []
    tables: list[NormalizedTable] = []
    issues: list[NormalizationIssue] = []
    doc = payload.get("document") if isinstance(payload.get("document"), dict) else payload
    pages = doc.get("pages") if isinstance(doc, dict) else None

    if isinstance(pages, list):
        for page_index, page in enumerate(pages, 1):
            page_no = page.get("page_no") or page.get("page_number") or page.get("number") or page_index
            for item in page.get("texts", []) or page.get("text_spans", []) or []:
                span = _span(
                    "docling",
                    page_no,
                    item.get("text") if isinstance(item, dict) else item,
                    "text",
                    item.get("confidence") if isinstance(item, dict) else None,
                    item.get("bbox") if isinstance(item, dict) else None,
                    {"label": item.get("label")} if isinstance(item, dict) else {},
                )
                if span:
                    spans.append(span)
            for table in page.get("tables", []) or []:
                normalized = _table(
                    "docling",
                    page_no,
                    table.get("data") or table.get("rows") if isinstance(table, dict) else table,
                    table.get("caption") if isinstance(table, dict) else None,
                    table.get("confidence") if isinstance(table, dict) else None,
                )
                if normalized:
                    tables.append(normalized)
    else:
        text = doc.get("text") or doc.get("markdown") if isinstance(doc, dict) else None
        span = _span("docling", DEFAULT_PAGE_NUMBER, text, "text")
        if span:
            spans.append(span)
        else:
            issues.append(_issue("docling", "medium", "Docling-like payload did not expose pages or text."))

    for item in doc.get("texts", []) if isinstance(doc, dict) else []:
        span = _span(
            "docling",
            item.get("prov", [{}])[0].get("page_no") if isinstance(item, dict) and item.get("prov") else DEFAULT_PAGE_NUMBER,
            item.get("text") if isinstance(item, dict) else item,
            item.get("label", "text") if isinstance(item, dict) else "text",
            item.get("confidence") if isinstance(item, dict) else None,
            item.get("bbox") if isinstance(item, dict) else None,
        )
        if span:
            spans.append(span)
    for item in doc.get("tables", []) if isinstance(doc, dict) else []:
        page_no = DEFAULT_PAGE_NUMBER
        if isinstance(item, dict) and item.get("prov"):
            page_no = item["prov"][0].get("page_no", DEFAULT_PAGE_NUMBER)
        normalized = _table(
            "docling",
            page_no,
            item.get("data") or item.get("rows") if isinstance(item, dict) else item,
            item.get("caption") if isinstance(item, dict) else None,
            item.get("confidence") if isinstance(item, dict) else None,
        )
        if normalized:
            tables.append(normalized)
    return spans[:MAX_SPANS], tables[:MAX_TABLES], issues[:MAX_ISSUES]


def normalize_unstructured_output(payload: Any) -> tuple[list[NormalizedSpan], list[NormalizedTable], list[NormalizationIssue]]:
    elements = payload
    if isinstance(payload, dict):
        elements = payload.get("elements") or payload.get("chunks") or payload.get("documents") or []
    spans: list[NormalizedSpan] = []
    tables: list[NormalizedTable] = []
    issues: list[NormalizationIssue] = []
    if not isinstance(elements, list):
        issues.append(_issue("unstructured", "medium", "Unstructured-like payload did not expose an element list."))
        return spans, tables, issues
    for index, element in enumerate(elements, 1):
        if not isinstance(element, dict):
            span = _span("unstructured", DEFAULT_PAGE_NUMBER, element, "text", metadata={"index": index})
            if span:
                spans.append(span)
            continue
        metadata = element.get("metadata") or {}
        page_no = metadata.get("page_number") or element.get("page_number") or DEFAULT_PAGE_NUMBER
        category = element.get("type") or element.get("category") or "text"
        text = element.get("text") or element.get("content")
        if str(category).lower() == "table":
            table = _table("unstructured", page_no, element.get("table") or element.get("text_as_html") or text,
                           element.get("caption"), element.get("confidence"))
            if table:
                tables.append(table)
        span = _span(
            "unstructured",
            page_no,
            text,
            str(category).lower(),
            element.get("detection_class_prob") or element.get("confidence"),
            metadata.get("coordinates") or element.get("bbox"),
            {"element_id": element.get("element_id"), "category": category},
        )
        if span:
            spans.append(span)
    return spans[:MAX_SPANS], tables[:MAX_TABLES], issues[:MAX_ISSUES]


def normalize_paddleocr_output(payload: Any) -> tuple[list[NormalizedSpan], list[NormalizedTable], list[NormalizationIssue]]:
    spans: list[NormalizedSpan] = []
    tables: list[NormalizedTable] = []
    issues: list[NormalizationIssue] = []
    items = payload
    if isinstance(payload, dict):
        items = (
            payload.get("rec_texts")
            or payload.get("ocr_result")
            or payload.get("results")
            or payload.get("pages")
            or payload.get("text_lines")
            or []
        )
    if isinstance(items, dict):
        items = [items]
    if isinstance(payload, dict) and payload.get("tables"):
        for table in payload.get("tables", []):
            normalized = _table(
                "paddleocr",
                table.get("page_number", DEFAULT_PAGE_NUMBER) if isinstance(table, dict) else DEFAULT_PAGE_NUMBER,
                table.get("rows") or table.get("html") if isinstance(table, dict) else table,
                table.get("caption") if isinstance(table, dict) else None,
                table.get("confidence") if isinstance(table, dict) else None,
            )
            if normalized:
                tables.append(normalized)
    if not isinstance(items, list):
        issues.append(_issue("paddleocr", "medium", "PaddleOCR-like payload did not expose OCR result lines."))
        return spans, tables, issues
    for index, item in enumerate(items, 1):
        if isinstance(item, str):
            span = _span("paddleocr", DEFAULT_PAGE_NUMBER, item, "line", metadata={"index": index})
        elif isinstance(item, dict):
            page_no = item.get("page_number") or item.get("page_id") or DEFAULT_PAGE_NUMBER
            text = item.get("text") or item.get("rec_text") or item.get("content")
            confidence = item.get("confidence") or item.get("score") or item.get("rec_score")
            span = _span("paddleocr", page_no, text, "line", confidence, item.get("bbox") or item.get("dt_polys"),
                         {"index": index})
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            bbox = item[0]
            content = item[1]
            if isinstance(content, (list, tuple)):
                text = content[0] if content else ""
                confidence = content[1] if len(content) > 1 else None
            else:
                text = content
                confidence = None
            span = _span("paddleocr", DEFAULT_PAGE_NUMBER, text, "line", confidence, bbox, {"index": index})
        else:
            span = None
        if span:
            spans.append(span)
    return spans[:MAX_SPANS], tables[:MAX_TABLES], issues[:MAX_ISSUES]


def normalize_surya_output(payload: dict[str, Any]) -> tuple[list[NormalizedSpan], list[NormalizedTable], list[NormalizationIssue]]:
    spans: list[NormalizedSpan] = []
    tables: list[NormalizedTable] = []
    issues: list[NormalizationIssue] = []
    pages = payload.get("pages") if isinstance(payload, dict) else None
    if pages is None:
        pages = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(pages, list):
        pages = [payload] if isinstance(payload, dict) else []
    for page_index, page in enumerate(pages, 1):
        if not isinstance(page, dict):
            continue
        page_no = page.get("page") or page.get("page_number") or page_index
        lines = page.get("text_lines") or page.get("lines") or page.get("ocr") or []
        for index, line in enumerate(lines, 1):
            if isinstance(line, dict):
                span = _span(
                    "surya",
                    page_no,
                    line.get("text"),
                    line.get("type", "line"),
                    line.get("confidence") or line.get("score"),
                    line.get("bbox") or line.get("polygon"),
                    {"index": index, "block_id": line.get("block_id")},
                )
            else:
                span = _span("surya", page_no, line, "line", metadata={"index": index})
            if span:
                spans.append(span)
        for block in page.get("layout") or page.get("layout_blocks") or []:
            if not isinstance(block, dict):
                continue
            span = _span(
                "surya",
                page_no,
                block.get("text") or block.get("label"),
                block.get("type", "layout"),
                block.get("confidence"),
                block.get("bbox") or block.get("polygon"),
                {"block": True},
            )
            if span:
                spans.append(span)
        for table in page.get("tables") or []:
            normalized = _table("surya", page_no, table.get("rows") if isinstance(table, dict) else table,
                                table.get("caption") if isinstance(table, dict) else None,
                                table.get("confidence") if isinstance(table, dict) else None)
            if normalized:
                tables.append(normalized)
    if not spans and not tables:
        issues.append(_issue("surya", "medium", "Surya-like payload did not expose lines, layout blocks or tables."))
    return spans[:MAX_SPANS], tables[:MAX_TABLES], issues[:MAX_ISSUES]


def normalize_marker_output(payload: dict[str, Any]) -> tuple[list[NormalizedSpan], list[NormalizedTable], list[NormalizationIssue]]:
    spans: list[NormalizedSpan] = []
    tables: list[NormalizedTable] = []
    issues: list[NormalizationIssue] = []
    markdown = payload.get("markdown") or payload.get("text") if isinstance(payload, dict) else None
    if markdown:
        for index, block in enumerate(re.split(r"\n\s*\n", str(markdown)), 1):
            span = _span("marker", DEFAULT_PAGE_NUMBER, block, "markdown_block", metadata={"index": index})
            if span:
                spans.append(span)
    chunks = payload.get("chunks") if isinstance(payload, dict) else None
    if isinstance(chunks, list):
        for index, chunk in enumerate(chunks, 1):
            if isinstance(chunk, dict):
                page_no = chunk.get("page") or chunk.get("page_number") or DEFAULT_PAGE_NUMBER
                text = chunk.get("text") or chunk.get("content") or chunk.get("markdown")
                kind = chunk.get("type") or "chunk"
            else:
                page_no = DEFAULT_PAGE_NUMBER
                text = chunk
                kind = "chunk"
            span = _span("marker", page_no, text, str(kind), metadata={"index": index})
            if span:
                spans.append(span)
    blocks = payload.get("blocks") if isinstance(payload, dict) else None
    if isinstance(blocks, list):
        for index, block in enumerate(blocks, 1):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "table":
                table = _table("marker", block.get("page", DEFAULT_PAGE_NUMBER), block.get("rows") or block.get("html"),
                               block.get("caption"), block.get("confidence"))
                if table:
                    tables.append(table)
            span = _span("marker", block.get("page", DEFAULT_PAGE_NUMBER), block.get("text") or block.get("html"),
                         block.get("type", "block"), block.get("confidence"), block.get("bbox"), {"index": index})
            if span:
                spans.append(span)
    if not spans and not tables:
        issues.append(_issue("marker", "medium", "Marker-like payload did not expose markdown, chunks or blocks."))
    return spans[:MAX_SPANS], tables[:MAX_TABLES], issues[:MAX_ISSUES]


def normalize_olmocr_output(payload: dict[str, Any]) -> tuple[list[NormalizedSpan], list[NormalizedTable], list[NormalizationIssue]]:
    spans: list[NormalizedSpan] = []
    issues: list[NormalizationIssue] = []
    text = payload.get("text") or payload.get("linearized_text") or payload.get("markdown") if isinstance(payload, dict) else None
    if text:
        for index, block in enumerate(re.split(r"\n\s*\n", str(text)), 1):
            span = _span("olmocr", DEFAULT_PAGE_NUMBER, block, "linearized_block", metadata={"index": index})
            if span:
                spans.append(span)
    pages = payload.get("pages") if isinstance(payload, dict) else None
    if isinstance(pages, list):
        for index, page in enumerate(pages, 1):
            if isinstance(page, dict):
                span = _span("olmocr", page.get("page_number", index),
                             page.get("text") or page.get("linearized_text"),
                             "page_text", page.get("confidence"), metadata={"index": index})
            else:
                span = _span("olmocr", index, page, "page_text", metadata={"index": index})
            if span:
                spans.append(span)
    quality = payload.get("quality_flags") if isinstance(payload, dict) else None
    if isinstance(quality, list):
        for flag in quality:
            issues.append(_issue("olmocr", "low", _clean_text(flag, max_chars=300)))
    if not spans:
        issues.append(_issue("olmocr", "medium", "olmOCR-like payload did not expose linearized text."))
    return spans[:MAX_SPANS], [], issues[:MAX_ISSUES]


def detect_payload_kind(payload: Any) -> str:
    if isinstance(payload, dict):
        provider = str(payload.get("provider") or payload.get("source") or payload.get("adapter") or "").lower()
        if provider in {"docling", "unstructured", "paddleocr", "surya", "marker", "olmocr"}:
            return provider
        keys = set(payload)
        if {"document", "texts", "tables"} & keys and ("docling" in provider or "document" in keys):
            return "docling"
        if {"elements", "category", "metadata"} & keys:
            return "unstructured"
        if {"rec_texts", "ocr_result", "dt_polys"} & keys:
            return "paddleocr"
        if {"text_lines", "layout_blocks", "layout"} & keys:
            return "surya"
        if {"markdown", "chunks", "blocks"} & keys:
            return "marker"
        if {"linearized_text", "quality_flags"} & keys:
            return "olmocr"
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict) and (
            "category" in first
            or "element_id" in first
            or ("type" in first and "metadata" in first)
        ):
            return "unstructured"
        if isinstance(first, (list, tuple)):
            return "paddleocr"
    return "unknown"


NORMALIZERS = {
    "docling": normalize_docling_output,
    "unstructured": normalize_unstructured_output,
    "paddleocr": normalize_paddleocr_output,
    "surya": normalize_surya_output,
    "marker": normalize_marker_output,
    "olmocr": normalize_olmocr_output,
}


def normalize_adapter_payload(payload: Any, adapter: str | None = None) -> dict:
    kind = (adapter or detect_payload_kind(payload)).lower()
    if kind not in NORMALIZERS:
        raise AdapterNormalizationError("Unsupported adapter payload")
    spans, tables, issues = NORMALIZERS[kind](payload)
    packet = {
        "provider": "adapter-output-normalizer-v15",
        "adapter": kind,
        "span_count": len(spans),
        "table_count": len(tables),
        "issue_count": len(issues),
        "spans": [span.public() for span in spans],
        "tables": [table.public() for table in tables],
        "issues": [issue.public() for issue in issues],
        "quality": quality_signals(spans, tables, issues),
        "ocr_pages": pages_from_spans(spans),
        "notice": "Normalized adapter output is a review input, not a lender-certified source.",
    }
    return packet


def pages_from_spans(spans: list[NormalizedSpan]) -> list[dict]:
    by_page: dict[int, list[NormalizedSpan]] = {}
    for span in spans:
        by_page.setdefault(span.page_number, []).append(span)
    pages = []
    for page_number in sorted(by_page):
        text = "\n".join(span.text for span in by_page[page_number])[:MAX_TEXT_CHARS]
        confidences = [span.confidence for span in by_page[page_number] if span.confidence is not None]
        mean_confidence = round(sum(confidences) / len(confidences), 4) if confidences else None
        pages.append(
            {
                "page_number": page_number,
                "text": text,
                "mean_confidence": mean_confidence,
                "source_span_count": len(by_page[page_number]),
            }
        )
    return pages


def quality_signals(spans: list[NormalizedSpan], tables: list[NormalizedTable],
                    issues: list[NormalizationIssue]) -> dict:
    low_confidence = [span.id for span in spans if span.confidence is not None and span.confidence < 0.55]
    has_money = any(re.search(r"\$\s*\d|CAD|\b\d{3},\d{3}\b", span.text, flags=re.I) for span in spans)
    has_rate = any(re.search(r"\b\d+(?:\.\d+)?\s*%", span.text) for span in spans)
    has_date = any(re.search(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", span.text) for span in spans)
    has_penalty = any(re.search(r"\bIRD\b|interest rate differential|three months? interest|penalt", span.text, flags=re.I) for span in spans)
    sources = sorted({span.source for span in spans} | {table.source for table in tables})
    return {
        "has_money": has_money,
        "has_rate": has_rate,
        "has_date": has_date,
        "has_penalty_language": has_penalty,
        "has_tables": bool(tables),
        "low_confidence_span_ids": low_confidence[:40],
        "source_count": len(sources),
        "sources": sources,
        "review_required": bool(low_confidence or issues) or not (has_money and has_rate),
    }


def validate_normalized_packet(packet: dict) -> dict:
    issues = list(packet.get("issues", []))
    quality = packet.get("quality", {})
    if packet.get("span_count", 0) == 0:
        issues.append(_issue(packet.get("adapter", "adapter"), "high", "No text spans were normalized.").public())
    if not quality.get("has_money"):
        issues.append(_issue(packet.get("adapter", "adapter"), "medium", "No money amount was detected in normalized spans.").public())
    if not quality.get("has_rate"):
        issues.append(_issue(packet.get("adapter", "adapter"), "medium", "No interest-rate percentage was detected in normalized spans.").public())
    if packet.get("span_count", 0) >= MAX_SPANS:
        issues.append(_issue(packet.get("adapter", "adapter"), "low", "Span count hit normalization cap; source may need chunking.").public())
    return {
        "provider": "normalized-packet-validator-v15",
        "valid_for_contract_review": not any(issue.get("severity") == "high" for issue in issues),
        "issue_count": len(issues),
        "issues": issues[:MAX_ISSUES],
        "quality": quality,
    }


def preview_adapter_payload(payload: Any, adapter: str | None = None) -> dict:
    packet = normalize_adapter_payload(payload, adapter)
    validation = validate_normalized_packet(packet)
    return {
        "provider": "adapter-payload-preview-v15",
        "adapter": packet["adapter"],
        "ocr_pages": packet["ocr_pages"],
        "quality": packet["quality"],
        "validation": validation,
        "summary": {
            "span_count": packet["span_count"],
            "table_count": packet["table_count"],
            "issue_count": validation["issue_count"],
            "valid_for_contract_review": validation["valid_for_contract_review"],
        },
        "notice": "Send ocr_pages into existing V10-V14 OCR and contract intelligence endpoints.",
    }
