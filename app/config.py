from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"


@dataclass
class Config:
    pipeline_version: str = "1.0.0"
    rules_version: str = "1.0.0"
    dpi: int = 150
    max_bytes: int = 10_000_000
    max_pages: int = 10
    max_pixels: int = 50_000_000
    max_compression_ratio: int = 100
    max_zip_entries: int = 10000
    max_pdf_objects: int = 100000
    scan_enabled: bool = False
    scan_engine: str = "yara+cdr"
    scan_poll_interval: int = 5  # DEPRECATED: scanner runs synchronously in Stage 1
    scan_max_attempts: int = 5   # DEPRECATED: scanner runs synchronously in Stage 1
    cdr_dpi: int = 200
    cdr_reconstruct_pdf: bool = True
    cdr_reconstruct_docx: bool = True
    contrast_min: float = 1.5
    min_ink: float = 0.02
    ghost_diff_threshold: int = 40
    ocr_margin: int = 4
    iou_threshold: float = 0.30
    fuzzy_threshold: int = 85
    weights: dict = field(default_factory=dict)
    suspicious_score: float = 5.0
    review_threshold: float = 2.0
    quarantine_threshold: float = 5.0
    audit_rate: float = 0.05
    injection: dict = field(default_factory=dict)
    tiny_font_max_pt: float = field(default=6.0)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        p = Path(path) if path else DEFAULT_CONFIG_PATH
        data = {}
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        weights = data.get("weights", {})
        return cls(
            pipeline_version=str(data.get("pipeline_version", "1.0.0")),
            rules_version=str(data.get("rules_version", "1.0.0")),
            dpi=int(data.get("dpi", 150)),
            max_bytes=int(data.get("max_bytes", 10_000_000)),
            max_pages=int(data.get("max_pages", 10)),
            max_pixels=int(data.get("max_pixels", 50_000_000)),
            max_compression_ratio=int(data.get("max_compression_ratio", 100)),
            max_zip_entries=int(data.get("max_zip_entries", 10000)),
            max_pdf_objects=int(data.get("max_pdf_objects", 100000)),
            scan_enabled=bool(data.get("scan_enabled", False)),
            scan_engine=str(data.get("scan_engine", "yara+cdr")),
            scan_poll_interval=int(data.get("scan_poll_interval", 5)),  # DEPRECATED
            scan_max_attempts=int(data.get("scan_max_attempts", 5)),    # DEPRECATED
            cdr_dpi=int(data.get("cdr_dpi", 200)),
            cdr_reconstruct_pdf=bool(data.get("cdr_reconstruct_pdf", True)),
            cdr_reconstruct_docx=bool(data.get("cdr_reconstruct_docx", True)),
            contrast_min=float(data.get("contrast_min", 1.5)),
            min_ink=float(data.get("min_ink", 0.02)),
            ghost_diff_threshold=int(data.get("ghost_diff_threshold", 40)),
            ocr_margin=int(data.get("ocr_margin", 4)),
            iou_threshold=float(data.get("iou_threshold", 0.30)),
            fuzzy_threshold=int(data.get("fuzzy_threshold", 85)),
            weights=weights,
            suspicious_score=float(data.get("suspicious_score", 5.0)),
            review_threshold=float(data.get("review_threshold", 2.0)),
            quarantine_threshold=float(data.get("quarantine_threshold", 5.0)),
            audit_rate=float(data.get("audit_rate", 0.05)),
            injection=data.get("injection", {}),
            tiny_font_max_pt=float(data.get("tiny_font_max_pt", 6.0)),
        )

    def weight(self, rule_id: str) -> float:
        return float(self.weights.get(rule_id, 1.0))


config = Config.load()
