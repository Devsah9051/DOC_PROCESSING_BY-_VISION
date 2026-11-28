from __future__ import annotations

from typing import List, Set, Tuple

import pymupdf

from app.config import config
from app.hash import block_hash, clean_hash
from app.schemas import PageReport, WordRecord, Flag
from stages.s2_verify.rules import cheap_rules, font_rules, scan_document_texts
from stages.s2_verify.render import render_page, make_text_erased, ghost_diff, contrast
from stages.s2_verify.ocr import ocr_region, OcrBox, _scale
from stages.s2_verify.verdict import classify_text_layer, compute_verdict, build_clean_text

MIN_TEXT_LAYER_WORDS = 3
IMAGE_HEAVY_RATIO = 0.5


def _word_id(page: int, bbox: Tuple[float, float, float, float], text: str, source: str) -> str:
    import hashlib

    s = f"{page}:{bbox[0]:.2f}:{bbox[1]:.2f}:{bbox[2]:.2f}:{bbox[3]:.2f}:{text}:{source}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def _image_area_ratio(page: pymupdf.Page) -> float:
    rect = page.rect
    area = rect.get_area()
    if area <= 0:
        return 0.0
    img_area = 0.0
    for img in page.get_images(full=True):
        try:
            for r in page.get_image_rects(img[0]):
                img_area += r.get_area()
        except Exception:
            continue
    return min(1.0, img_area / area)


def _extract_text_words(page: pymupdf.Page, pno: int, doc) -> List[dict]:
    """3.1 Text layer: spans with colour, size, opacity, render type, layer."""
    words: List[dict] = []
    d = page.get_text("dict")
    ocgs = doc.get_ocgs() or []
    ocg_off = {o.id for o in ocgs if not o.is_on}
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text:
                    continue
                bbox = tuple(span["bbox"])
                w = {
                    "word_id": _word_id(pno, bbox, text, "text_layer"),
                    "page": pno,
                    "bbox": list(bbox),
                    "text": text,
                    "source": "text_layer",
                    "visible": True,
                    "flags": [],
                    "size": span.get("size", 0),
                    "color": span.get("color", 0),
                    "alpha": span.get("alpha", 1.0),
                    "font": span.get("font", ""),
                    "hidden_layer": False,
                }
                if span.get("ocg") in ocg_off:
                    w["hidden_layer"] = True
                    w["flags"].append("HIDDEN_LAYER")
                    flags_append(w, "HIDDEN_LAYER", "text in hidden optional-content layer", "high")
                words.append(w)
    return words


def flags_append(w: dict, rule_id: str, evidence: str, severity: str):
    w["flags"].append(rule_id)


def _crop(image, bbox_pts, scale, margin):
    x0, y0, x1, y1 = [c * scale for c in bbox_pts]
    x0i = max(int(round(x0)) - margin, 0)
    y0i = max(int(round(y0)) - margin, 0)
    x1i = min(int(round(x1)) + margin, image.shape[1])
    y1i = min(int(round(y1)) + margin, image.shape[0])
    if x1i <= x0i or y1i <= y0i:
        return None
    return image[y0i:y1i, x0i:x1i]


def verify_pages(
    doc: pymupdf.Document, sha256: str, cfg=config
):
    """Run Stage 2 over every page.
    Returns (page_reports, flags, matched, ocr_only, clean_text, verdict)."""
    page_reports: List[PageReport] = []
    flags: List[tuple] = []
    text_words: List[dict] = []
    all_injection_texts: List[str] = []

    page_images = {}  # pno -> (orig, erased, needs_ocr)

    for page in doc:
        pno = page.number
        rect = page.rect
        try:
            words = _extract_text_words(page, pno, doc)
        except Exception:
            words = []
        has_text_layer = len(words) >= MIN_TEXT_LAYER_WORDS
        page_flags: List[Flag] = []

        # scan flag: big image area + few words
        try:
            img_ratio = _image_area_ratio(page)
        except Exception:
            img_ratio = 0.0
        if img_ratio > IMAGE_HEAVY_RATIO and len(words) < 5:
            ev = f"page {pno} image_ratio={img_ratio:.2f}"
            flags.append(("IMAGE_HEAVY_SCAN", ev, "low"))
            page_flags.append(Flag(rule_id="IMAGE_HEAVY_SCAN", evidence=ev, severity="low"))

        # 3.2 cheap rules + 3.3 font rules
        try:
            for w in words:
                for r in cheap_rules(w, rect, page):
                    flags.append((r.rule_id, r.evidence, r.severity))
                    w["flags"].append(r.rule_id)
                    page_flags.append(Flag(rule_id=r.rule_id, evidence=r.evidence, severity=r.severity))
                for r in font_rules(w):
                    flags.append((r.rule_id, r.evidence, r.severity))
                    w["flags"].append(r.rule_id)
                text_words.append(w)
                all_injection_texts.append(w["text"])
        except Exception:
            pass

        # 3.4 render pair (pages with text)
        orig = erased = None
        needs_ocr = False
        if words:
            try:
                orig = render_page(page, cfg.dpi)
                erased = make_text_erased(doc, pno, cfg.dpi).image
            except Exception:
                needs_ocr = True
                ev = f"page {pno} text erase failed"
                flags.append(("NEEDS_OCR", ev, "low"))
                page_flags.append(Flag(rule_id="NEEDS_OCR", evidence="erase failed", severity="low"))

        # 3.5 ghost diff + 3.6 contrast per word
        try:
            scale = _scale()
            margin = cfg.ocr_margin
            for w in words:
                try:
                    bbox = tuple(w["bbox"])
                    crop_o = _crop(orig, bbox, scale, margin) if orig is not None else None
                    crop_e = _crop(erased, bbox, scale, margin) if erased is not None else None
                    if crop_o is not None and crop_e is not None:
                        gd = ghost_diff(crop_o, crop_e)
                        w["visible"] = not gd.not_visible
                        w["ink"] = gd.ink
                        if gd.not_visible:
                            ev = f"word '{w['text']}' ink={gd.ink:.2f}"
                            flags.append(("NOT_VISIBLE", ev, "high"))
                            w["flags"].append("NOT_VISIBLE")
                            page_flags.append(Flag(rule_id="NOT_VISIBLE", evidence=ev, severity="high"))
                        else:
                            w["visible"] = True
                    else:
                        w["visible"] = True
                    if crop_e is not None:
                        cr = contrast(w.get("color", 0), crop_e)
                        w["contrast_ratio"] = cr.ratio
                        if cr.low_contrast:
                            ev = f"word '{w['text']}' ratio={cr.ratio:.2f}"
                            flags.append(("LOW_CONTRAST", ev, "low"))
                            w["flags"].append("LOW_CONTRAST")
                            page_flags.append(Flag(rule_id="LOW_CONTRAST", evidence=ev, severity="low"))
                except Exception:
                    pass
        except Exception:
            pass

        page_images[pno] = (orig, erased, needs_ocr)
        page_reports.append(
            PageReport(
                page=pno,
                has_text_layer=has_text_layer,
                needs_ocr=needs_ocr,
                words=[
                    WordRecord(
                        word_id=w["word_id"],
                        page=w["page"],
                        bbox=w["bbox"],
                        text=w["text"],
                        source=w["source"],
                        visible=w["visible"],
                        flags=list(w["flags"]),
                    )
                    for w in words
                ],
                flags=page_flags,
                ocr_used=False,
            )
        )
        page_flags: List[Flag] = []

    # 3.7 OCR gate
    ocr_boxes: List[OcrBox] = []
    full_images = {}
    for pno, (orig, erased, needs_ocr) in page_images.items():
        page = doc[pno]
        if orig is None:
            orig = render_page(page, cfg.dpi)
        full_images[pno] = orig

    audit_sample = _audit_sample(sha256, len(doc))

    for pno in range(len(doc)):
        page = doc[pno]
        words = [w for w in text_words if w["page"] == pno]
        has_text_layer = len(words) >= MIN_TEXT_LAYER_WORDS
        orig = full_images[pno]
        erased, needs_ocr = page_images[pno][1], page_images[pno][2]

        problem_words = []
        for w in words:
            rflags = cheap_rules(w, page.rect, page) + font_rules(w)
            if any(r.rule_id in ("FONT_ANOMALY", "GARBLED", "INVISIBLE_OPACITY", "INVISIBLE_RENDER_MODE") for r in rflags):
                problem_words.append(w)
            if w.get("visible") is False:
                problem_words.append(w)
            if w.get("contrast_ratio") is not None and w["contrast_ratio"] < cfg.contrast_min:
                problem_words.append(w)

        regions: List[tuple] = []
        if not has_text_layer:
            regions.append((list(page.rect), "full_page_no_text_layer"))
        elif needs_ocr:
            regions.append((list(page.rect), "full_page_erase_failed"))
        elif pno in audit_sample:
            regions.append((list(page.rect), "full_page_audit_sample"))
        elif problem_words:
            for w in problem_words:
                regions.append((list(w["bbox"]), f"flagged_word_{w['word_id']}"))
        else:
            # text layer + large image => image region only
            if _image_area_ratio(page) > IMAGE_HEAVY_RATIO:
                for img in page.get_images(full=True):
                    try:
                        for r in page.get_image_rects(img[0]):
                            regions.append((list(r), "image_region"))
                    except Exception:
                        continue

        page_had_ocr = False
        for bbox_pts, _label in regions:
            for ob in ocr_region(orig, bbox_pts, pno):
                ocr_boxes.append(ob)
                all_injection_texts.append(ob.text)
                page_had_ocr = True
        if page_had_ocr:
            page_reports[pno].ocr_used = True

    # 3.8 match
    matched, ocr_only = classify_text_layer(text_words, ocr_boxes)
    for w in matched:
        if w.classification == "MISMATCH":
            flags.append(("MISMATCH", f"page {w.page} text/OCR mismatch", "medium"))
        elif w.classification == "TEXT_ONLY":
            flags.append(("TEXT_ONLY", f"page {w.page} text-layer word not found by OCR", "high"))

    # 3.9 injection scan on every file (visible + hidden + metadata + annotations)
    strong = False
    weak = 0.0
    try:
        meta = doc.metadata or {}
        for v in meta.values():
            if isinstance(v, str):
                all_injection_texts.append(v)
    except Exception:
        pass
    for page in doc:
        try:
            for link in page.get_links() or []:
                for v in (link.get("uri"), link.get("text")):
                    if isinstance(v, str):
                        all_injection_texts.append(v)
        except Exception:
            continue
        try:
            for annot in page.annots() or []:
                try:
                    info = annot.info or {}
                    t = info.get("content", "")
                    if isinstance(t, str):
                        all_injection_texts.append(t)
                except Exception:
                    continue
        except Exception:
            continue
    strong, weak = scan_document_texts(all_injection_texts)
    if strong:
        flags.append(("INJECTION_STRONG", "strong injection pattern detected", "critical"))

    # 3.10 verdict
    verdict = compute_verdict(flags, strong, weak, cfg.weights)

    # 3.11 clean_text
    clean_text = build_clean_text(matched, ocr_only)

    # Build block records (Section 6.10) with real block hashes
    block_records = []
    block_hashes = []
    for w in matched:
        bh = block_hash({
            "block_id": w.word_id,
            "page": w.page,
            "bbox": list(w.bbox),
            "verdict": w.classification or "UNCORROBORATED_NOT_VISIBLE",
        })
        block_hashes.append(bh)
        block_records.append({
            "block_id": w.word_id,
            "block_hash": bh,
            "page": w.page,
            "frame_id": None,
            "bbox": list(w.bbox),
            "column_id": None,
            "reading_order": 0,
            "verdict": w.classification or "UNCORROBORATED_NOT_VISIBLE",
        })

    # clean_artifact_sha256: hash of all block hashes (Section 4.2 hash chain)
    clean_artifact_sha256 = clean_hash(block_hashes) if block_hashes else clean_hash([])

    # Parse status (Section 6.8)
    if verdict.status == "QUARANTINE":
        parse_status = "PARSE_FAILED"
    elif len(ocr_only) > 0:
        parse_status = "PARSED_WITH_WARNINGS"
    else:
        parse_status = "PARSED"

    return page_reports, flags, matched, ocr_only, clean_text, verdict, block_records, parse_status, clean_artifact_sha256


def _audit_sample(sha256: str, page_count: int) -> Set[int]:
    """3.7(d) deterministic audit sample from sha256."""
    import hashlib

    sample: Set[int] = set()
    if page_count == 0:
        return sample
    digest = hashlib.sha256(sha256.encode("utf-8")).hexdigest()
    rate = config.audit_rate
    n = max(1, int(round(page_count * rate)))
    for i in range(page_count):
        h = hashlib.sha256(f"{digest}:{i}".encode("utf-8")).hexdigest()
        if int(h, 16) % 100 < int(rate * 100):
            sample.add(i)
    while len(sample) < n and len(sample) < page_count:
        sample.add(len(sample) % page_count)
    return sample
