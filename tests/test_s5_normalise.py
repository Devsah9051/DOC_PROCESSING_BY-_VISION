from __future__ import annotations

from app.schemas import WordRecord, Verdict
from stages.s5_normalise import load_taxonomy, normalise_tokens, build_output


def _wr(wid, text):
    return WordRecord(word_id=wid, page=1, bbox=[0, 0, 10, 10], text=text, source="text_layer", visible=True, flags=[])


def test_normalise_canonical_skills():
    taxonomy = load_taxonomy()
    tokens = [_wr("w1", "python"), _wr("w2", "js"), _wr("w3", "python")]
    skills = normalise_tokens(tokens, taxonomy)
    by_canon = {s["canonical"]: s for s in skills}
    assert by_canon["python"]["word_ids"] == ["w1", "w3"]
    assert by_canon["javascript"]["word_ids"] == ["w2"]
    assert by_canon["python"]["confidence"] == 1.0


def test_normalise_unknown_skill_kept():
    taxonomy = load_taxonomy()
    skills = normalise_tokens([_wr("w1", "obscuretoolxyz")], taxonomy)
    assert skills[0]["canonical"] == "obscuretoolxyz"


def test_build_output_hash_and_seal():
    verdict = Verdict(status="CLEAN", score=0.0, rules=[], reasons=[])
    versions = {"pipeline_version": "1.0.0", "rules_version": "1.0.0"}
    out1 = build_output([], [_wr("w1", "python")], verdict, versions, {}, "prevhash")
    out2 = build_output([], [_wr("w1", "python")], verdict, versions, {}, "prevhash")
    assert out1.report_hash == out2.report_hash
    assert out1.signature == out2.signature
    assert out1.prev_hash == "prevhash"
    assert out1.signature

    out3 = build_output([], [_wr("w1", "ruby")], verdict, versions, {}, "prevhash")
    assert out3.report_hash != out1.report_hash
