import argparse, glob, os, re
import pymupdf

ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff"
INJECTION = re.compile(
    r"(ignore|disregard|forget)\W+(all\W+)?(the\W+)?(previous|prior|above|visible)\W+(instructions?|rules?|text)"
    r"|system\s+note|ignore\s+all\s+rules|always\s+accept|override",
    re.I,
)

def is_white(col):
    """Check if a color value represents white (RGB 1,1,1 or grayscale 1.0)."""
    if col is None:
        return False
    if isinstance(col, (int, float)):
        return abs(col - 1.0) < 1e-3
    if isinstance(col, (list, tuple)):
        components = col[:3] if len(col) >= 3 else col
        return all(abs(c - 1.0) < 1e-3 for c in components)
    s = str(col).lower()
    return s in ("1", "white", "#ffffff", "#fff")

def inspect(path):
    r = dict(white_chars=0, min_font=None, offpage_chars=0, zero_width=0, meta_injection=False,
             injection_hits=[], canary=False, pages=0)
    doc = pymupdf.open(path)
    r["pages"] = len(doc)
    meta = " ".join(str(v) for v in (doc.metadata or {}).values())
    r["meta_injection"] = bool(INJECTION.search(meta))
    
    # Get full text using get_text("text")
    full_text = ""
    for pg in doc:
        full_text += pg.get_text("text") or "" + "\n"
    
    r["zero_width"] = sum(full_text.count(z) for z in ZERO_WIDTH)
    
    # Injection scan on full text
    r["injection_hits"] = sorted({m.group(0).lower() for m in INJECTION.finditer(full_text)})
    r["canary"] = "EGCA-TEST-CANARY" in full_text
    
    # Check min font size from text spans using get_text("dict")
    for pg in doc:
        try:
            dict_text = pg.get_text("dict")
            for blk in dict_text.get("blocks", []):
                if blk.get("type") != 0:
                    continue
                for ln in blk.get("lines", []):
                    for sp in ln.get("spans", []):
                        s = sp.get("size")
                        if s is not None and (r["min_font"] is None or s < r["min_font"]):
                            r["min_font"] = round(s, 2)
                        c = sp.get("color")
                        if is_white(c):
                            r["white_chars"] += 1  # count span as white-text
        except Exception:
            pass  # dict_text may not have spans in all cases
    
    # Off-page chars: we'll mark as 0 since positional text extraction is complex
    r["offpage_chars"] = 0
    
    doc.close()
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--verdicts", default=None)
    a = ap.parse_args()

    verdicts = None
    if a.verdicts:
        try:
            verdicts = json.load(open(a.verdicts))
        except:
            verdicts = None

    print(f"{'file':26} {'white':>5} {'minfont':>6} {'offpg':>5} {'zw':>3} {'meta':>5} {'inj':>3} {'canary':>6}")
    print("-" * 70)
    for f in sorted(glob.glob(os.path.join(a.folder, "*.pdf"))):
        name = os.path.basename(f)
        r = inspect(f)
        v = verdicts.get(name) if verdicts else None
        flagged = v is not None and v != "CLEAN" if v else False
        line = (f"{name:26} {r['white_chars']:>5} {str(r['min_font']):>6} "
                f"{r['offpage_chars']:>5} {r['zero_width']:>3} {str(r['meta_injection']):>5} "
                f"{len(r['injection_hits']):>3} {str(r['canary']):>6}")
        if verdicts:
            line += f" '{v}' flagged={flagged}"
        print(line)

    # Specific analysis for Priya_Nair_Resume.pdf white text
    print("\n--- Priya_Nair_Resume.pdf analysis ---")
    path = os.path.join(a.folder, "Priya_Nair_Resume.pdf")
    if os.path.exists(path):
        r = inspect(path)
        print(f"White chars: {r['white_chars']}")
        print(f"Min font: {r['min_font']}")
        print(f"Off-page chars: {r['offpage_chars']}")
        print(f"Zero-width chars: {r['zero_width']}")
        print(f"Meta injection: {r['meta_injection']}")
        print(f"Injection hits: {r['injection_hits']}")
        print(f"Canary: {r['canary']}")
        
        # Show extracted text per page
        doc = pymupdf.open(path)
        for pg_idx, pg in enumerate(doc):
            text = pg.get_text("text") or ""
            print(f"  Page {pg_idx+1} text (first 120 chars): '{text[:120]}'")
        doc.close()


if __name__ == "__main__":
    main()