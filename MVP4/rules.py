"""
rules.py
---------
Central rule table for JEVBP/JBESS part code generation.

This is deliberately kept as *data*, not scattered logic, so that
Phase 0 (rule finalization) work — filling in the categories that are
still incomplete in the source nomenclature file — means editing this
file only, not touching the app/database code.

Each category defines:
  - `code_format`: human-readable pattern (for display/reference)
  - `fields`: ordered list of (field_key, label, kind, choices/None)
      kind = "choice"  -> dropdown, choices is a list of (code, label)
      kind = "text"    -> free text (validated by `pattern` if given)
      kind = "auto"    -> zero-padded auto-incrementing sequence,
                          scoped per the given `scope_fields`
  - `build_code(values)`: function that assembles the final code string
"""

# ---------------------------------------------------------------------------
# GENERAL PART NUMBERS  (Sheet: "Part Numbers")
# Format: JEVBP-XXXX-XXXXX  ->  actually rendered as PROJECT-CATEGORY-PARTCODE
# Only "01 - GA Drawing" has a starting part code (001) in the source file;
# the rest (02-06) have categories but no part-code ranges defined yet.
# TODO (Phase 0): confirm/expand part-code ranges per category with the
# project team before this category goes into production use.
# ---------------------------------------------------------------------------
GENERAL_PART = {
    "key": "general",
    "label": "General Part Number",
    "code_format": "JEVBP-<CategoryCode>-<PartCode>",
    "fields": [
        ("project_code", "Project Code", "choice", [
            ("JEVBP", "JEVBP"),
            ("JBESS", "JBESS"),
        ]),
        ("category_code", "Product Category", "choice", [
            ("01", "01 - GA Drawing"),
            ("02", "02 - Fabrication"),
            ("03", "03 - Insulation, Plastic, Foam, Gaskets, Epoxy, PC, TIM"),
            ("04", "04 - Busbars"),
            ("05", "05 - Harness"),
            ("06", "06 - Electrical & Electronic parts"),
        ]),
        ("part_code", "Part Code (auto)", "auto", None),
    ],
    "scope_fields": ["project_code", "category_code"],  # auto-sequence resets per (project, category)
    "auto_width": 3,   # 001, 002, ...
    "build_code": lambda v: f"{v['project_code']}-{v['category_code']}-{v['part_code']}",
}

# ---------------------------------------------------------------------------
# CELL  (Sheet: "Cell")
# Format: JEVBP-CXXXXXXXA  ->  JEVBP-C<Supplier><Capacity>A
# ---------------------------------------------------------------------------
CELL = {
    "key": "cell",
    "label": "Cell",
    "code_format": "JEVBP-C<Supplier><Capacity>A",
    "fields": [
        ("supplier", "Supplier", "choice", [
            ("EVE", "EVE"),
            ("REPT", "REPT"),
            ("CATL", "CATL"),
            ("CALB", "CALB"),
        ]),
        ("capacity", "Capacity (Ah)", "choice", [
            ("105", "105"),
            ("230", "230"),
            ("314", "314"),
        ]),
    ],
    "scope_fields": None,  # combination itself must be unique -> handled as duplicate check
    "build_code": lambda v: f"JEVBP-C{v['supplier']}{v['capacity']}A",
}

# ---------------------------------------------------------------------------
# BMS  (Sheet: "BMS")
# Format: JEVBP-XXXX-XX  ->  JEVBP-<Type>-<Supplier>
# ---------------------------------------------------------------------------
BMS = {
    "key": "bms",
    "label": "BMS",
    "code_format": "JEVBP-<Type>-<Supplier>",
    "fields": [
        ("bms_type", "BMS Type", "choice", [
            ("SBMS", "SBMS"),
            ("MBMS", "MBMS"),
        ]),
        ("supplier", "Supplier", "choice", [
            ("RX", "RX"),
            ("XB", "XB"),
        ]),
    ],
    "scope_fields": None,
    "build_code": lambda v: f"JEVBP-{v['bms_type']}-{v['supplier']}",
}

# ---------------------------------------------------------------------------
# FASTENERS  (Sheet: "Fasteners")
# Format: FS-<TYPE>-<THREADSIZE>-<LENGTH>-<HEADSTYLE>
# Example from source file: FS-scr-M3-12-hex
# ---------------------------------------------------------------------------
FASTENER = {
    "key": "fastener",
    "label": "Fastener",
    "code_format": "FS-<Type>-<ThreadSize>-<Length>-<HeadStyle>",
    "fields": [
        ("ftype", "Type", "choice", [
            ("SCR", "SCR - Screw"),
            ("BLT", "BLT - Bolt"),
            ("NUT", "NUT - Nut"),
            ("WSR", "WSR - Washer"),
            ("RV", "RV - Rivet"),
            ("IN", "IN - Insert"),
        ]),
        ("thread_size", "Thread Size", "choice", [
            (f"M{n}", f"M{n}") for n in [3, 4, 5, 6, 8, 10, 12, 14, 16, 20, 24]
        ]),
        ("length", "Length (mm)", "choice", [
            (str(n), str(n)) for n in [6, 8, 10, 12, 16, 20, 25, 30, 35, 40, 45,
                                        50, 55, 60, 65, 70, 80, 90, 100, 110, 120,
                                        130, 140, 150, 160, 180, 200, 220, 250,
                                        280, 300, 350, 400, 450, 500]
        ]),
        ("head_style", "Head Style", "choice", [
            ("PH", "PH - Phillips Head"),
            ("PN", "PN - Pan Head"),
            ("CSK", "CSK - Countersunk Flat Head"),
            ("SHS", "SHS - Socket Head Screw"),
            ("HEX", "HEX - Hex Head Bolt"),
            ("HF", "HF - Hex Flange Bolt"),
            ("TH", "TH - T-Head Bolt"),
            ("EY", "EY - Eye Bolt"),
            ("UB", "UB - U-Bolt"),
            ("HN", "HN - Hex Nut"),
            ("HFN", "HFN - Hex Flange Nut"),
            ("NLN", "NLN - Nylock Nut"),
            ("DN", "DN - Dome Nut"),
            ("CN", "CN - Cage Nut"),
            ("RN", "RN - Rivet Nut"),
            ("WN", "WN - Weld Nut"),
            ("PW", "PW - Plain Washer"),
            ("SW", "SW - Spring Washer"),
        ]),
    ],
    "scope_fields": None,
    "build_code": lambda v: f"FS-{v['ftype']}-{v['thread_size']}-{v['length']}-{v['head_style']}",
}

# ---------------------------------------------------------------------------
# DRAWING / 3D MODEL  (added after Discussion 2)
# One category for both 2D drawings and 3D renderings: the "Document Type"
# field picks which. Sequence restarts per (project, document type), so
# JEVBP-DRW-00001 and JEVBP-3DM-00001 are independent numbering runs.
# Length: 5 + 1 + 3 + 1 + 5 = 15 characters (inside the 10-18 standard).
# Extra document types can be added later from Manage Categories ->
# Manage options, no code change needed (keep the code at 3 characters or
# the length check in app.py will reject it).
# ---------------------------------------------------------------------------
DRAWING = {
    "key": "drawing",
    "label": "Drawing / 3D Model",
    "code_format": "<Project>-<DocType>-<Sequence>",
    "fields": [
        ("project_code", "Project Code", "choice", [
            ("JEVBP", "JEVBP"),
            ("JBESS", "JBESS"),
        ]),
        ("doc_type", "Document Type", "choice", [
            ("DRW", "DRW - 2D Drawing"),
            ("3DM", "3DM - 3D Model / Rendering"),
        ]),
        ("seq", "Sequence (auto)", "auto", None),
    ],
    "scope_fields": ["project_code", "doc_type"],
    "auto_width": 5,   # 00001, 00002, ...
    "build_code": lambda v: f"{v['project_code']}-{v['doc_type']}-{v['seq']}",
}

CATEGORIES = {
    c["key"]: c for c in [GENERAL_PART, DRAWING, CELL, BMS, FASTENER]
}
