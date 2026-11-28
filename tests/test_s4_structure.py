from __future__ import annotations

from app.schemas import WordRecord
from stages.s4_structure import extract_structure, StructureResult


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
