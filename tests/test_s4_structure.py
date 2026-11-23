from __future__ import annotations

from app.schemas import WordRecord
from stages.s4_structure import extract_structure


def _wr(wid, text, bbox):
    return WordRecord(word_id=wid, page=1, bbox=list(bbox), text=text, source="text_layer", visible=True, flags=[])


def test_extract_sections_and_fields():
    text = "Contact\njane@example.com\nExperience\nPython developer at Acme Corp\n"
    records = [
        _wr("w1", "Contact", [72, 100, 140, 116]),
        _wr("w2", "jane@example.com", [72, 120, 200, 136]),
        _wr("w3", "Experience", [72, 160, 170, 176]),
        _wr("w4", "Python", [72, 180, 130, 196]),
        _wr("w5", "developer", [135, 180, 210, 196]),
    ]
    sections, fields = extract_structure(text, records)
    names = [s.name for s in sections]
    assert "contact" in names
    assert "experience" in names
    emails = [f for f in fields if f.name == "email"]
    assert len(emails) == 1
    assert emails[0].value == "jane@example.com"
    assert emails[0].word_ids == ["w2"]
