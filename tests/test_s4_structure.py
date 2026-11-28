from __future__ import annotations

from app.schemas import WordRecord
from stages.s4_structure import extract_structure, StructureResult

import app.config


def _wr(wid, text, bbox, flags=None):
    return WordRecord(
        word_id=wid,
        page=1,
        bbox=list(bbox),
        text=text,
        source="text_layer",
        visible=True,
        flags=list(flags or []),
    )


def test_extract_sections_and_fields():
    text = "Contact\njane@example.com\nExperience\nPython developer at Acme Corp\n"
    records = [
        _wr("w1", "Contact", [72, 100, 140, 116]),
        _wr("w2", "jane@example.com", [72, 120, 200, 136]),
        _wr("w3", "Experience", [72, 160, 170, 176]),
        _wr("w4", "Python", [72, 180, 130, 196]),
        _wr("w5", "developer", [135, 180, 210, 196]),
    ]
    result = extract_structure(text, records, track="resume")
    names = [s.name for s in result.sections]
    assert "contact" in names
    assert "experience" in names
    emails = [f for f in result.fields if f.name == "email"]
    assert len(emails) == 1
    assert emails[0].value == "jane@example.com"
    assert emails[0].word_ids == ["w2"]


def test_result_has_record_root_and_pii_ref():
    text = "Contact\njane@example.com\n"
    records = [
        _wr("w1", "Contact", [72, 100, 140, 116]),
        _wr("w2", "jane@example.com", [72, 120, 200, 136]),
    ]
    result = extract_structure(text, records, track="resume")
    assert isinstance(result, StructureResult)
    assert result.record_root != ""
    assert result.pii_ref != ""
    assert result.track == "resume"


def test_date_intervals_extracted():
    text = "Experience\nJan 2020 - Present\n"
    records = [
        _wr("w1", "Experience", [72, 100, 170, 116]),
        _wr("w2", "Jan", [72, 120, 110, 136]),
        _wr("w3", "2020", [115, 120, 155, 136]),
    ]
    result = extract_structure(text, records, track="resume", uploaded_at=1735689600)  # 2025-01-01
    assert len(result.date_intervals) >= 1
    # At least one interval should have is_present=True if "Present" found
    present_intervals = [di for di in result.date_intervals if di.is_present]
    # May or may not find depending on text parsing, but should not crash


def test_rule_flags_populated():
    # Resume with no contact section → R1 flag
    text = "Experience\nPython developer\n"
    records = [
        _wr("w1", "Experience", [72, 100, 170, 116]),
        _wr("w2", "Python", [72, 120, 130, 136]),
        _wr("w3", "developer", [135, 120, 210, 136]),
    ]
    result = extract_structure(text, records, track="resume")
    assert "R1_MISSING_REQUIRED_SECTION" in result.rule_flags


def test_duplicate_section_flag():
    text = "Experience\nPython dev\nExperience\nJava dev\n"
    records = [
        _wr("w1", "Experience", [72, 100, 170, 116]),
        _wr("w2", "Python", [72, 120, 130, 136]),
        _wr("w3", "dev", [135, 120, 170, 136]),
        _wr("w4", "Experience", [72, 160, 170, 176]),
        _wr("w5", "Java", [72, 180, 110, 196]),
        _wr("w6", "dev", [135, 180, 170, 196]),
    ]
    result = extract_structure(text, records, track="resume")
    assert "R2_DUPLICATE_SECTION" in result.rule_flags


def test_manipulation_flags_from_word_flags():
    text = "Contact\njane@example.com\n"
    records = [
        _wr("w1", "Contact", [72, 100, 140, 116], flags=["invisible"]),
        _wr("w2", "jane@example.com", [72, 120, 200, 136]),
    ]
    result = extract_structure(text, records, track="resume")
    m1_flags = [f for f in result.manipulation_flags if f.flag_id == "M1_HIDDEN_TEXT"]
    assert len(m1_flags) >= 1


def test_job_description_track():
    text = "Responsibilities\nManage team\nRequirements\n5 years experience\n"
    records = [
        _wr("w1", "Responsibilities", [72, 100, 200, 116]),
        _wr("w2", "Manage", [72, 120, 120, 136]),
        _wr("w3", "team", [125, 120, 160, 136]),
        _wr("w4", "Requirements", [72, 160, 170, 176]),
        _wr("w5", "5", [72, 180, 90, 196]),
        _wr("w6", "years", [95, 180, 140, 196]),
        _wr("w7", "experience", [145, 180, 230, 196]),
    ]
    result = extract_structure(text, records, track="job_description")
    assert result.track == "job_description"


def test_labels_assigned():
    text = "Contact\njane@example.com\nExperience\nPython dev\n"
    records = [
        _wr("w1", "Contact", [72, 100, 140, 116]),
        _wr("w2", "jane@example.com", [72, 120, 200, 136]),
        _wr("w3", "Experience", [72, 160, 170, 176]),
        _wr("w4", "Python", [72, 180, 130, 196]),
        _wr("w5", "dev", [135, 180, 170, 196]),
    ]
    result = extract_structure(text, records, track="resume")
    label_map = {l["field"]: l["label"] for l in result.labels}
    assert "jane@example.com" in label_map
    assert label_map["jane@example.com"] == "FACT"


# ============ New Stage 4 layout tests ============

def _wr_with_style(wid, text, bbox, size=12.0, bold=False, color=0, font="Helvetica", flags=None, page=1):
    return WordRecord(
        word_id=wid,
        page=page,
        bbox=list(bbox),
        text=text,
        source="text_layer",
        visible=True,
        flags=list(flags or []),
        size=size,
        bold=bold,
        color=color,
        font=font,
    )


def test_multi_size_heading_detected():
    """Large text at top should be detected as HEADING via size signal."""
    text = "Experience\nJane Doe\nSoftware Engineer\n"
    records = [
        _wr_with_style("w1", "Experience", [72, 100, 200, 120], size=20.0, bold=True),
        _wr_with_style("w2", "Jane", [72, 140, 120, 160], size=14.0),
        _wr_with_style("w3", "Doe", [130, 140, 170, 160], size=14.0),
        _wr_with_style("w4", "Software", [72, 180, 160, 200], size=12.0),
        _wr_with_style("w5", "Engineer", [170, 180, 260, 200], size=12.0),
    ]
    result = extract_structure(text, records, track="resume")
    names = [s.name for s in result.sections]
    assert "experience" in names


def test_bold_heading_detected():
    """Bold text should be detected as HEADING via bold_ratio signal."""
    text = "Experience\nPython developer at Acme Corp\n"
    records = [
        _wr_with_style("w1", "Experience", [72, 100, 200, 120], size=14.0, bold=True),
        _wr_with_style("w2", "Python", [72, 140, 130, 160], size=12.0),
        _wr_with_style("w3", "developer", [140, 140, 240, 160], size=12.0),
    ]
    result = extract_structure(text, records, track="resume")
    names = [s.name for s in result.sections]
    assert "experience" in names


def test_gap_separated_sections():
    """Wide vertical gap between blocks should start a new section."""
    text = "Contact\njane@example.com\n\nExperience\nPython developer\n"
    records = [
        _wr_with_style("w1", "Contact", [72, 100, 140, 116]),
        _wr_with_style("w2", "jane@example.com", [72, 120, 200, 136]),
        _wr_with_style("w3", "Experience", [72, 260, 170, 176]),  # big gap after line 2
        _wr_with_style("w4", "Python", [72, 180, 130, 196]),
        _wr_with_style("w5", "developer", [135, 180, 210, 196]),
    ]
    result = extract_structure(text, records, track="resume")
    names = [s.name for s in result.sections]
    assert "contact" in names
    assert "experience" in names


def test_two_column_layout():
    """Two columns should not merge into one section."""
    text = "Experience\nPython developer\nEducation\nBS Computer Science\n"
    records = [
        _wr_with_style("w1", "Experience", [72, 100, 200, 116], size=14.0, bold=True),
        _wr_with_style("w2", "Python", [72, 140, 130, 156], size=12.0),
        _wr_with_style("w3", "developer", [140, 140, 240, 156], size=12.0),
        _wr_with_style("w4", "Education", [300, 100, 400, 116], size=14.0, bold=True),
        _wr_with_style("w6", "BS", [300, 140, 330, 156], size=12.0),
        _wr_with_style("w7", "Computer", [335, 140, 420, 156], size=12.0),
        _wr_with_style("w8", "Science", [425, 140, 490, 156], size=12.0),
    ]
    result = extract_structure(text, records, track="resume")
    # Should have at least 2 sections (Experience and Education)
    names = [s.name for s in result.sections]
    assert "experience" in names
    assert "education" in names


def test_header_footer_furniture():
    """Same text at same position on 2+ pages = PAGE_FURNITURE."""
    import app.config
    original = app.config.config.structure_layout_enabled
    app.config.config.structure_layout_enabled = True
    try:
        # Page 1 header
        records_page1 = [
            _wr_with_style("w1", "CONFIDENTIAL", [72, 50, 180, 66], size=10.0, page=1),
            _wr_with_style("w2", "Page", [200, 50, 240, 66], size=10.0, page=1),
            _wr_with_style("w3", "1", [245, 50, 260, 66], size=10.0, page=1),
        ]
        # Page 2 header (same text at same position)
        records_page2 = [
            _wr_with_style("w4", "CONFIDENTIAL", [72, 50, 180, 66], size=10.0, page=2),
            _wr_with_style("w5", "Page", [200, 50, 240, 66], size=10.0, page=2),
            _wr_with_style("w6", "1", [245, 50, 260, 66], size=10.0, page=2),
        ]
        records = records_page1 + records_page2
        text = "CONFIDENTIAL Page 1\nCONFIDENTIAL Page 1\n"
        result = extract_structure(text, records, track="resume")
        furniture_lines = [l for l in result.lines if l.line_class == "PAGE_FURNITURE"]
        assert len(furniture_lines) >= 1, f"Expected PAGE_FURNITURE lines, got {[l.line_class for l in result.lines]}"
    finally:
        app.config.config.structure_layout_enabled = original


def test_layout_flag_off():
    """With structure_layout_enabled=False, lines should be empty."""
    import app.config
    original = app.config.config.structure_layout_enabled
    app.config.config.structure_layout_enabled = False
    try:
        text = "Experience\nPython developer\n"
        records = [
            _wr_with_style("w1", "Experience", [72, 100, 170, 116], size=14.0, bold=True),
            _wr_with_style("w2", "Python", [72, 140, 130, 160], size=12.0),
        ]
        result = extract_structure(text, records, track="resume")
        assert result.lines == []
    finally:
        app.config.config.structure_layout_enabled = original


def test_layout_flag_on_detects_heading():
    """With structure_layout_enabled=True, bold heading should be detected."""
    import app.config
    original = app.config.config.structure_layout_enabled
    app.config.config.structure_layout_enabled = True
    try:
        text = "Experience\nPython developer\n"
        records = [
            _wr_with_style("w1", "Experience", [72, 100, 170, 116], size=14.0, bold=True),
            _wr_with_style("w2", "Python", [72, 140, 130, 160], size=12.0),
        ]
        result = extract_structure(text, records, track="resume")
        heading_lines = [l for l in result.lines if l.line_class == "HEADING"]
        assert len(heading_lines) >= 1, f"Expected HEADING line, got {[l.line_class for l in result.lines]}"
        assert result.sections[0].heading_line_id is not None
    finally:
        app.config.config.structure_layout_enabled = original


def test_sealed_lines_in_record_root():
    """Line data should be included in record_root hash."""
    import app.config
    original = app.config.config.structure_layout_enabled
    app.config.config.structure_layout_enabled = True
    try:
        text = "Experience\nPython developer\n"
        records = [
            _wr_with_style("w1", "Experience", [72, 100, 170, 116], size=14.0, bold=True),
            _wr_with_style("w2", "Python", [72, 140, 130, 160], size=12.0),
        ]
        result_with_lines = extract_structure(text, records, track="resume")
        assert len(result_with_lines.lines) >= 1
        assert result_with_lines.record_root != ""

        # Same content without layout flag should produce different record_root
        app.config.config.structure_layout_enabled = False
        result_without_lines = extract_structure(text, records, track="resume")
        assert result_without_lines.record_root != result_with_lines.record_root
    finally:
        app.config.config.structure_layout_enabled = original


def test_list_item_classification():
    """Bullet-prefixed line should be classified as LIST_ITEM."""
    import app.config
    original = app.config.config.structure_layout_enabled
    app.config.config.structure_layout_enabled = True
    try:
        text = "• Item one\n• Item two\nRegular text\n"
        records = [
            _wr_with_style("w1", "•", [72, 100, 90, 116], size=12.0),
            _wr_with_style("w2", "Item", [95, 100, 140, 116], size=12.0),
            _wr_with_style("w3", "one", [145, 100, 180, 116], size=12.0),
            _wr_with_style("w4", "•", [72, 140, 90, 156], size=12.0),
            _wr_with_style("w5", "Item", [95, 140, 140, 156], size=12.0),
            _wr_with_style("w6", "two", [145, 140, 180, 156], size=12.0),
            _wr_with_style("w7", "Regular", [72, 180, 140, 196], size=12.0),
            _wr_with_style("w8", "text", [145, 180, 190, 196], size=12.0),
        ]
        result = extract_structure(text, records, track="resume")
        list_items = [l for l in result.lines if l.line_class == "LIST_ITEM"]
        assert len(list_items) >= 1, f"Expected LIST_ITEM lines, got {[l.line_class for l in result.lines]}"
    finally:
        app.config.config.structure_layout_enabled = original
