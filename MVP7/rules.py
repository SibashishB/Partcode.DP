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
    "description": "Catch-all for GA Drawings, Fabrication and Harness part numbers that don't need their own category yet.",
    "code_format": "JEVBP-<CategoryCode>-<PartCode>",
    "fields": [
        ("project_code", "Project Code", "choice", [
            ("JEVBP", "JEVBP"),
            ("JBESS", "JBESS"),
        ]),
        ("category_code", "Product Category", "choice", [
            ("01", "01 - GA Drawing"),
            ("02", "02 - Fabrication"),
            # "03 - Insulation...", "04 - Busbars" and "06 - Electrical &
            # Electronic parts" were removed from here on purpose: each one
            # either bundled several distinct material types under a single
            # flat code with no way to tell them apart afterwards, or (for
            # Busbars) needed a Material/Sub-Type breakdown. They are now
            # their own categories below (INSULATION, BUSBAR, ELECTRICAL)
            # with a Type field baked into the code, the same treatment
            # DRAWING got for "01 - GA Drawing" vs 3D models.
            ("05", "05 - Harness"),
        ]),
        ("part_code", "Part Code (auto)", "auto", None),
    ],
    "scope_fields": ["project_code", "category_code"],  # auto-sequence resets per (project, category)
    "auto_width": 3,   # 001, 002, ...
    "build_code": lambda v: f"{v['project_code']}-{v['category_code']}-{v['part_code']}",
}

# ---------------------------------------------------------------------------
# INSULATION / SEALING MATERIALS  (was bundled under "03" above)
# Source sheet listed: Insulation, Plastic, Foam, Gaskets, Epoxy, PC, TIM
# as one line with no way to tell them apart in a code. Segregated here via
# a Material Type field. Sequence restarts per (project, material type), so
# e.g. Gasket and Foam each get their own 00001, 00002... run.
# ---------------------------------------------------------------------------
INSULATION = {
    "key": "insulation",
    "label": "Insulation / Plastic / Foam / Gasket / Epoxy / PC / TIM",
    "description": "Insulation and related soft-goods materials. Material Type keeps Gaskets, Foam, Epoxy etc. visibly distinct instead of bundled.",
    "code_format": "<Project>-03-<Type>-<Sequence>",
    "fields": [
        ("project_code", "Project Code", "choice", [
            ("JEVBP", "JEVBP"),
            ("JBESS", "JBESS"),
        ]),
        ("material_type", "Material Type", "choice", [
            ("INS", "INS - Insulation (general)"),
            ("PLA", "PLA - Plastic"),
            ("FOA", "FOA - Foam"),
            ("GKT", "GKT - Gasket"),
            ("EPX", "EPX - Epoxy"),
            ("PC", "PC - Polycarbonate"),
            ("TIM", "TIM - Thermal Interface Material"),
        ]),
        ("seq", "Sequence (auto)", "auto", None),
    ],
    "scope_fields": ["project_code", "material_type"],
    "auto_width": 5,
    "build_code": lambda v: f"{v['project_code']}-03-{v['material_type']}-{v['seq']}",
}

# ---------------------------------------------------------------------------
# BUSBAR  (was bundled under "04" above)
# Request: segregate by Material (Aluminium/Copper, more addable later) then
# Sub-Type (Solid/Flexible). Codes are tight against the 18-char ceiling
# (JEVBP-04-AL-SO-001 = 18 chars exactly), so Material/Sub-Type codes
# added later via Manage options need to stay 2 characters to fit.
# ---------------------------------------------------------------------------
BUSBAR = {
    "key": "busbar",
    "label": "Busbar",
    "description": "Busbars, split by Material (Aluminium/Copper) then Sub-Type (Solid/Flexible) so the two are never bundled into one ambiguous code.",
    "code_format": "<Project>-04-<Material>-<SubType>-<Sequence>",
    "fields": [
        ("project_code", "Project Code", "choice", [
            ("JEVBP", "JEVBP"),
            ("JBESS", "JBESS"),
        ]),
        ("material", "Material", "choice", [
            ("AL", "AL - Aluminium"),
            ("CU", "CU - Copper"),
        ]),
        ("sub_type", "Sub-Type", "choice", [
            ("SO", "SO - Solid"),
            ("FL", "FL - Flexible"),
        ]),
        ("seq", "Sequence (auto)", "auto", None),
    ],
    "scope_fields": ["project_code", "material", "sub_type"],
    "auto_width": 3,
    "build_code": lambda v: f"{v['project_code']}-04-{v['material']}-{v['sub_type']}-{v['seq']}",
}

# ---------------------------------------------------------------------------
# ELECTRICAL & ELECTRONIC PARTS  (was bundled under "06" above)
# "Electrical & Electronic parts" is itself two families plus "parts" is
# open-ended (connectors, switches, relays, sensors, wiring accessories...).
# Started with a Connector/Switch/Relay/Sensor/Other split -- extend the
# choices list (or use Manage Categories -> Manage options as an Admin) once
# the real breakdown from the R&D process study is known.
# ---------------------------------------------------------------------------
ELECTRICAL = {
    "key": "electrical",
    "label": "Electrical & Electronic Parts",
    "description": "Connectors, switches, relays, sensors and other electrical/electronic components, split out by Part Type.",
    "code_format": "<Project>-06-<Type>-<Sequence>",
    "fields": [
        ("project_code", "Project Code", "choice", [
            ("JEVBP", "JEVBP"),
            ("JBESS", "JBESS"),
        ]),
        ("part_type", "Part Type", "choice", [
            ("CON", "CON - Connector"),
            ("SW", "SW - Switch"),
            ("REL", "REL - Relay"),
            ("SEN", "SEN - Sensor"),
            ("OTH", "OTH - Other electrical/electronic part"),
        ]),
        ("seq", "Sequence (auto)", "auto", None),
    ],
    "scope_fields": ["project_code", "part_type"],
    "auto_width": 5,
    "build_code": lambda v: f"{v['project_code']}-06-{v['part_type']}-{v['seq']}",
}

# ---------------------------------------------------------------------------
# CELL  (Sheet: "Cell")
# Format: JEVBP-CXXXXXXXA  ->  JEVBP-C<Supplier><Capacity>A
# ---------------------------------------------------------------------------
CELL = {
    "key": "cell",
    "label": "Cell",
    "description": "Battery cells, identified by Supplier and Capacity (Ah). One code per physical cell spec, shared across projects.",
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
    "description": "Battery Management System units. Series distinguishes hardware/firmware generations of the same Type+Supplier combination.",
    "code_format": "JEVBP-<Type>-<Supplier>-<Series>",
    "fields": [
        ("bms_type", "BMS Type", "choice", [
            ("SBMS", "SBMS"),
            ("MBMS", "MBMS"),
        ]),
        ("supplier", "Supplier", "choice", [
            ("RX", "RX"),
            ("XB", "XB"),
        ]),
        # Placeholder series list — added per the request to show series on
        # BMS codes, but the real set of series wasn't specified. Extend via
        # Manage Categories -> Manage options once the actual series names
        # are known; keep each code <= 3 characters or the 10-18 overall
        # length rule may start refusing new ones.
        ("series", "Series", "choice", [
            ("S1", "Series 1"),
            ("S2", "Series 2"),
            ("S3", "Series 3"),
        ]),
    ],
    "scope_fields": None,
    "build_code": lambda v: f"JEVBP-{v['bms_type']}-{v['supplier']}-{v['series']}",
}

# ---------------------------------------------------------------------------
# FASTENERS  (Sheet: "Fasteners")
# Format: FS-<TYPE>-<THREADSIZE>-<LENGTH>-<HEADSTYLE>
# Example from source file: FS-scr-M3-12-hex
# ---------------------------------------------------------------------------
FASTENER = {
    "key": "fastener",
    "label": "Fastener",
    "description": "Screws, bolts, nuts, washers, rivets and inserts, fully specified by Type, Thread Size, Length and Head Style.",
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
    "description": "2D drawings and 3D models/renderings for any part. Document Type picks which; numbering runs separately for each.",
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
    c["key"]: c for c in [GENERAL_PART, DRAWING, INSULATION, BUSBAR, ELECTRICAL, CELL, BMS, FASTENER]
}
