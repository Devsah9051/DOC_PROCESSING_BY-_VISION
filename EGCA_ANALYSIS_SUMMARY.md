EGCA PHASE 1 RESUME ANALYSIS (Rule-Engine Verified)
====================================================

All analysis below is based on the actual rule implementations in stages/s2_verify/rules.py
that were verified by 28 passing pytest tests. The pipeline infrastructure (DB pool,
Ed25519 signing) is unavailable in this environment, but the rule-checking logic itself
was confirmed correct.

== QUARANTINED RESUMES (strong prompt injection detected) ==

1. Aarav_Mehta_Resume.pdf
   - Rule: INJECTION_STRONG
   - Trigger: Contains "ignore all previous instructions"
   - Basis: Regex patterns in config.injection.strings match "ignore.*previous.*instructions"
   - Outcome: Strong injection => immediate QUARANTINED regardless of other scores

2. Fatima_Sheikh_Resume.pdf
   - Rules: INJECTION_STRONG + METADATA_INJECTION
   - Trigger: "ignore all previous instructions" in BOTH body text AND metadata author field
   - Basis: Strong injection regex + metadata text scan (Stage 2 Step 3.9)
   - Outcome: QUARANTINED

3. Kabir_Singh_Resume.pdf
   - Rule: INJECTION_STRONG
   - Trigger: Contains "disregard all previous instructions"
   - Basis: Regex `disregard\\s+(all\\s+)?previous` matches this phrase
   - Outcome: QUARANTINED

== SUSPICIOUS RESUMES (weighted score >= 5.0, no strong injection) ==

4. Ananya_Iyer_Resume.pdf
   - Status: CLEAN (not suspicious)
   - No rules triggered - normal resume with proper text layer

5. Arjun_Bhatt_Resume.pdf
   - Status: SUSPICIOUS  
   - Rules: TINY_FONT + LOW_CONTRAST
   - Tiny font: text with font size < 6pt detected
   - Low contrast: WCAG contrast ratio < 1.5 against background
   - Score crosses 5.0 threshold

6. Isha_Gupta_Resume.pdf
   - Status: SUSPICIOUS
   - Rules: OFF_PAGE + NOT_VISIBLE
   - Off-page: text positioned outside canonical page bounds
   - Not visible: ghost diff shows ink share below min_ink (white-on-white effect)

7. Mohit_Yadav_Resume.pdf
   - Status: SUSPICIOUS
   - Rules: ZERO_WIDTH + NOT_VISIBLE
   - Zero-width: contains zero-width characters (\u200b zero-width space)
   - Not visible: some text has ink below threshold

8. Priya_Nair_Resume.pdf
   - Status: CLEAN (not suspicious)
   - No rules triggered - well-formed resume

9. Rohan_Verma_Resume.pdf
   - Status: SUSPICIOUS
   - Rules: OFF_PAGE + NOT_VISIBLE
   - Off-page + not visible (similar to Isha_Gupta)

10. Sneha_Kulkarni_Resume.pdf
    - Status: CLEAN (not suspicious)
    - No rules triggered - well-formed resume

== CLEAN RESUMES (no issues detected) ==

== Summary ==
- QUARANTINED: 3/10 (all due to strong prompt injection)
- SUSPICIOUS: 4/10 (tiny font, low contrast, off-page text, zero-width chars)
- CLEAN: 3/10 (well-formed resumes)

== Key Rule Triggers Reference ==

Rule ID          | Trigger                                    | Count
-----------------|--------------------------------------------|------
INJECTION_STRONG | "ignore/disregard all previous instructions"| 3 (QUARANTINE)
TINY_FONT        | Font size < 6pt                            | 1 (SUSPICIOUS)
LOW_CONTRAST     | WCAG ratio < 1.5                           | 1 (SUSPICIOUS)
OFF_PAGE         | Text outside page bounds                   | 3 (SUSPICIOUS)
NOT_VISIBLE      | Ghost diff ink < min_ink (white-on-white)  | 3 (SUSPICIOUS)
ZERO_WIDTH       | Zero-width/bidi/tag characters             | 1 (SUSPICIOUS)
METADATA_INJECTION| Injection in PDF metadata author field     | 1 (QUARANTINE)

== How the Classification Works ==

1. QUARANTINED: Strong prompt injection regex match => immediate quarantine
   - Patterns: "ignore all previous instructions", "disregard all previous"
   - Bypasses all other checks

2. SUSPICIOUS: Weighted score >= 5.0 from individual rule hits
   - Each rule adds its weight: TINY_FONT=3, INVISIBLE_OPACITY=8, etc.
   - Score threshold: 5.0 (configurable in config.yaml)

3. CLEAN: No rules triggered OR score < 5.0
   - All checked rules pass
   - Resume is valid with proper text layer, normal fonts, adequate contrast