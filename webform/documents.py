"""Fill the official onboarding documents from a lead's answers.

The PDFs are flattened scans (no form fields), so values are written on top at fixed
coordinates measured from each template. If a template changes, re-measure and update
the coordinates in this file.
"""
import html
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime

import docx
import pymupdf
from docx.enum.text import WD_LINE_SPACING
from docx.shared import Inches

BASE_DIR = os.path.dirname(__file__)
FORMS_DIR = os.path.join(BASE_DIR, "official_forms")
FONTS = pymupdf.Archive(os.path.join(BASE_DIR, "fonts"))
CSS = """
@font-face { font-family: latin; src: url(NotoSans-Regular.ttf); }
@font-face { font-family: deva; src: url(NotoSansDevanagari-Regular.ttf); }
* { font-family: latin, deva; color: #0b1f5c; line-height: 1.15; }
"""
INK = (0.04, 0.12, 0.36)  # dark blue, reads as "filled in" against the black print

REGISTRATION_FEE = "1,999"
APPOINTED_AS = "Business Correspondent Agent (CSP)"
STAMP_PAPER_TOP_INCHES = 3.5


# ---------- helpers ----------

def en(value):
    """Bilingual option labels like 'कृषि (Agriculture)' or 'हाँ / Yes' → the English part."""
    if not value:
        return ""
    value = str(value)
    m = re.search(r"\(([^()]*)\)\s*$", value)
    if m and re.search(r"[ऀ-ॿ]", value):
        return m.group(1)
    if " / " in value and re.search(r"[ऀ-ॿ]", value.split(" / ")[0]):
        return value.split(" / ", 1)[1]
    return value


def put(page, rect, text, size=9, white=False):
    if not text:
        return
    rect = pymupdf.Rect(rect)
    if white:
        page.draw_rect(rect, color=None, fill=(1, 1, 1))
    body = html.escape(str(text)).replace("\n", "<br>")
    page.insert_htmlbox(rect, f'<div style="font-size:{size}pt">{body}</div>', css=CSS, archive=FONTS, scale_low=0)


def boxes(page, edges, y0, y1, text, size=9, whiten=False):
    """One character per box. edges are the x positions of the box borders."""
    for i, ch in enumerate(str(text)[: len(edges) - 1]):
        x0, x1 = edges[i], edges[i + 1]
        if whiten:
            page.draw_rect(pymupdf.Rect(x0 + 1, y0 + 1, x1 - 1, y1 - 1), color=None, fill=(1, 1, 1))
        w = pymupdf.get_text_length(ch, fontname="helv", fontsize=size)
        page.insert_text(((x0 + x1) / 2 - w / 2, (y0 + y1) / 2 + size * 0.36), ch,
                         fontname="helv", fontsize=size, color=INK)


def even_edges(x0, x1, n):
    step = (x1 - x0) / n
    return [x0 + i * step for i in range(n + 1)]


def tick(page, x0, y0, x1, y1):
    w, h = x1 - x0, y1 - y0
    page.draw_polyline([(x0 + w * 0.18, y0 + h * 0.55), (x0 + w * 0.42, y0 + h * 0.85), (x0 + w * 0.88, y0 + h * 0.15)],
                       color=INK, width=1.4)


def dot(page, x, y, r=2.6):
    page.draw_circle((x, y), r, color=INK, fill=INK)


def circle_word(page, word, within):
    for r in page.search_for(word, clip=pymupdf.Rect(within)):
        page.draw_oval(r + (-3, -2, 3, 2), color=INK, width=1.1)
        return


def ddmmyyyy(value):
    if not value:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d%m%Y")
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d%m%Y")
    except ValueError:
        return ""


def pretty_date(value):
    d = ddmmyyyy(value)
    return f"{d[:2]}/{d[2:4]}/{d[4:]}" if d else ""


def age_from(dob):
    try:
        b = datetime.strptime(dob, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return ""
    t = date.today()
    return str(t.year - b.year - ((t.month, t.day) < (b.month, b.day)))


def split_name(full):
    parts = (full or "").split()
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return (parts[0], " ".join(parts[1:-1]), parts[-1]) if parts else ("", "", "")


def aadhaar_address(a):
    tail = ", ".join(x for x in [a.get("city"), a.get("state")] if x)
    pin = a.get("pincode")
    return ", ".join(x for x in [a.get("address_line"), tail] if x) + (f" - {pin}" if pin else "")


def residence_address(a):
    if a.get("lives_at_aadhaar_address") == "no" and a.get("local_address"):
        return a["local_address"]
    return aadhaar_address(a)


def is_ascii(s):
    return all(ord(c) < 128 for c in s)


# ---------- Aggregator Application Form ----------

def fill_application_form(a, lead, photo_path, out_path):
    doc = pymupdf.open(os.path.join(FORMS_DIR, "application_form.pdf"))
    p = doc[0]

    boxes(p, [202.8, 215.5, 228.3, 241.0, 253.7, 266.3, 279.2, 291.7, 304.4], 165, 178,
          ddmmyyyy(date.today()), whiten=True)
    boxes(p, [353.3, 366.0, 378.6, 391.5, 404.1, 416.6, 429.5, 442.1, 454.8, 467.6, 480.2], 165, 178,
          a.get("pan_number", ""))

    first, middle, last = split_name(a.get("full_name"))
    name_edges = even_edges(74.0, 479.0, 32)
    for value, (y0, y1) in zip([first, middle, last], [(185, 199), (204, 218), (223, 237)]):
        if is_ascii(value):
            boxes(p, name_edges, y0, y1, value.upper())
        else:
            put(p, (76, y0, 478, y1), value, 9, white=True)
    boxes(p, even_edges(139.7, 241.7, 8), 247, 261, ddmmyyyy(a.get("dob")), whiten=True)

    if photo_path:
        try:
            p.insert_image(pymupdf.Rect(487, 148, 573, 237), filename=photo_path, keep_proportion=True)
        except Exception:
            pass

    put(p, (186, 279, 574, 309), a.get("address_line"), 9)
    if a.get("lives_at_aadhaar_address") == "no":
        put(p, (62, 310, 574, 323), f"Current residence: {a.get('local_address', '')}", 8)
    put(p, (64, 326, 154, 340), a.get("city"), 8)
    put(p, (187, 326, 288, 340), a.get("state"), 8)
    put(p, (322, 326, 423, 340), "India", 9)
    boxes(p, [466.3, 485.7, 505.7, 522.3, 541.1, 559.6, 578.3], 324, 341, a.get("pincode", ""))
    boxes(p, [408.9, 424.4, 437.0, 451.1, 466.3, 479.4, 493.5, 505.8, 522.3, 535.9, 550.0, 564.1, 578.3], 342, 360,
          "91" + (lead.get("mobile_number") or ""))
    put(p, (76, 362, 574, 376), lead.get("email") or a.get("email"), 9)
    dot(p, 99.4, 397.7)  # Nature of business: Individual

    put(p, (200, 538, 430, 554), a.get("bank_account_number"), 10)
    if "Current" in (a.get("account_type") or ""):
        dot(p, 495.0, 543.5)
    else:
        dot(p, 437.0, 543.5)
    put(p, (78, 559.5, 573, 571), ", ".join(x for x in [a.get("bank_name"), a.get("bank_branch")] if x), 9, white=True)
    put(p, (63, 578.5, 160, 590.5), (a.get("bank_branch") or "").split(",")[-1].strip(), 8)
    boxes(p, [294.4, 307.7, 321.2, 334.5, 348.0, 361.4, 374.8, 388.4, 401.9, 415.2, 428.7, 442.2], 579, 591,
          a.get("ifsc", ""))
    put(p, (485, 578.5, 573, 590.5), a.get("micr"), 9)

    tick(p, 23.8, 627, 32.4, 636)
    put(p, (122, 637, 313, 648.5), APPOINTED_AS, 7.5)
    put(p, (292, 645, 492, 656.5), APPOINTED_AS, 7.5)
    put(p, (55, 662, 158, 673), date.today().strftime("%d/%m/%Y"), 9)
    put(p, (55, 680, 158, 691), a.get("city"), 9)

    doc.subset_fonts()
    doc.save(out_path, garbage=4, deflate=True)


# ---------- Field Verification Report (Aceware format) ----------

def fill_fvr(a, lead, visit, out_path):
    v = visit or {}
    doc = pymupdf.open(os.path.join(FORMS_DIR, "fvr.pdf"))
    p = doc[0]

    for text, (x0, x1) in zip([v.get("state"), v.get("cluster"), v.get("division"), v.get("branch_name_code"),
                               v.get("cibil_score")],
                              [(25, 139), (139, 224), (224, 302), (302, 437), (437, 577)]):
        put(p, (x0 + 3, 231, x1 - 3, 256), text, 8.5)
    put(p, (28, 286, 136, 307), v.get("business_location_type"), 9)
    officer = " / ".join(x for x in [v.get("officer_name"), v.get("officer_emp_code")] if x)
    put(p, (142, 286, 435, 307), officer, 8.5)
    put(p, (440, 286, 574, 307), pretty_date(v.get("visit_date")), 9)

    L, R = (142, 299), (440, 574)
    dob = a.get("dob")
    left_right = [
        ((308, 334), a.get("full_name"), en(a.get("gender"))),
        ((334, 357), lead.get("mobile_number"), f"{age_from(dob)} yrs, {pretty_date(dob)}" if dob else ""),
        ((357, 412), f"XXXX XXXX {a['aadhaar_last4']} (self-attested copy collected)" if a.get("aadhaar_last4") else "",
         f"{a.get('pan_number', '')} (self-attested copy collected)" if a.get("pan_number") else ""),
        ((412, 441), None, en(a.get("years_at_location"))),
        ((441, 484), en(a.get("resident_type")), f"{en(a.get('family_size'))} / {en(a.get('children_count'))} children"),
        ((484, 533), v.get("spouse_father_occupation"), en(a.get("children_school"))),
        ((533, 590), ", ".join(x for x in [en(a.get("occupation")), a.get("shop_name")] if x), en(a.get("experience"))),
        ((590, 643), f"{en(a.get('occupation'))}: Rs. {en(a.get('income_band'))}",
         f"Rs. {en(a.get('secondary_income'))}"),
        ((643, 684), en(a.get("current_work_hours")), en(a.get("hours_available"))),
        ((684, 739), f"Rs. {en(a.get('initial_capital'))}", v.get("negative_credit_info") or "None reported"),
    ]
    for (y0, y1), left, right in left_right:
        put(p, (L[0], y0 + 3, L[1], y1 - 2), left, 8.5)
        put(p, (R[0], y0 + 3, R[1], y1 - 2), right, 8.5)
    marital = en(a.get("marital_status"))
    if marital:
        circle_word(p, "Widow" if "Widow" in marital else marital, (139, 412, 302, 441))

    p = doc[1]
    L, R = (154, 304), (434, 556)
    rows = [
        ((103, 168), v.get("establishment_type"), v.get("footfall")),
        ((168, 253), v.get("road_access"), v.get("nearest_esaf")),
        ((253, 324), v.get("population"), v.get("visibility")),
        ((324, 364), v.get("fi_nearby"), v.get("agents_within_5km")),
        ((364, 418), v.get("criminal_involvement"), v.get("sangam_name_relation")),
        ((418, 484), v.get("remarks"), v.get("sangam_member_name")),
    ]
    for (y0, y1), left, right in rows:
        put(p, (L[0], y0 + 3, L[1], y1 - 3), left, 8.5)
        put(p, (R[0], y0 + 3, R[1], y1 - 3), right, 8.5)
    if v.get("recommendation"):
        circle_word(p, v["recommendation"], (151, 497, 307, 544))
    put(p, (434, 520, 556, 543), " / ".join(x for x in [v.get("officer_name"), v.get("officer_emp_code"),
                                                          pretty_date(v.get("visit_date"))] if x), 7.5)

    doc.subset_fonts()
    doc.save(out_path, garbage=4, deflate=True)


# ---------- Customer Declaration Form (only when something doesn't match) ----------

SECTION_BODIES = {  # (page, rect of the dotted sentence lines, y of the section title)
    "name": (0, (62, 291, 553, 359), 277.5),
    "dob": (0, (62, 392, 553, 453), 371.4),
    "shop_address": (0, (62, 479, 553, 528), 467.6),
    "local_address": (0, (62, 580, 553, 647), 544.0),
    "father_name": (0, (62, 690, 553, 767), 662.8),
    "signature": (1, (62, 35, 553, 84), 11.0),
}


def declaration_text(kind, m, a):
    va, vb, sa, sb = m.get("value_a") or "", m.get("value_b") or "", m.get("source_a") or "", m.get("source_b") or ""
    if kind == "name":
        return (f"I, hereby declare that my name is correctly mentioned in {sa} as {va}, whereas in the {sb} "
                f"the name is mentioned as {vb}. The name in the Bank is to be as {va}.")
    if kind == "dob":
        return (f"I, hereby declare that my DOB is correctly mentioned in {sa} as {pretty_date(va) or va}, whereas "
                f"in {sb} the DOB is {pretty_date(vb) or vb}. DOB in the bank is to be {pretty_date(va) or va}.")
    if kind == "shop_address":
        return ("I hereby declare that, I do not have any shop address proof. Kindly onboard me as an agent with "
                f"the shop address {a.get('shop_address', '')}.")
    if kind == "local_address":
        return ("I hereby declare that, the below mentioned is my correct local address. Kindly onboard me as an "
                f"agent with the local address {a.get('local_address', '')}.")
    if kind == "father_name":
        return (f"I hereby declare that my father's name is correctly mentioned in {sa} as {va}, whereas in the "
                f"{sb}, the name is mentioned as {vb}. Father's name in bank is to be as {va}.")
    return (f"I hereby affirm that my signature has changed from the one featured in my {sa or vb} over passage of "
            "time. My present signature is as under and I hereby confirm that all actions and transactions "
            "authorized/executed by me using the below signature shall be legally binding on me.")


def fill_declaration(a, lead, mismatches, out_path):
    doc = pymupdf.open(os.path.join(FORMS_DIR, "declaration.pdf"))
    p0 = doc[0]

    put(p0, (63, 133, 298, 204), f"{a.get('full_name', '')}\n{residence_address(a)}", 9, white=True)
    put(p0, (336, 207, 540, 221), a.get("city"), 9)
    date_label = p0.search_for("Date:", clip=pymupdf.Rect(300, 228, 460, 248))
    x0 = date_label[0].x1 + 2 if date_label else 332
    put(p0, (x0, 231, 450, 246), date.today().strftime("%d / %m / %Y"), 9, white=True)

    by_kind = {}
    for m in mismatches:
        by_kind.setdefault(m["field_name"], m)

    for kind, (pi, body, title_y) in SECTION_BODIES.items():
        page = doc[pi]
        squares = [it[1] for dr in page.get_drawings() for it in dr["items"]
                   if it[0] == "re" and 7 < it[1].width < 16 and abs(it[1].width - it[1].height) < 3
                   and abs(it[1].y0 - title_y) < 10]
        r = pymupdf.Rect(body)
        if kind in by_kind:
            if squares:
                s = squares[0]
                tick(page, s.x0, s.y0, s.x1, s.y1)
            put(page, r, declaration_text(kind, by_kind[kind], a), 9.5, white=True)
        else:
            page.draw_line(r.tl + (0, 4), r.br - (0, 4), color=INK, width=0.8)  # strike off: not applicable

    name_label = doc[1].search_for("Name:", clip=pymupdf.Rect(240, 268, 490, 288))
    x0 = name_label[0].x1 + 2 if name_label else 276
    put(doc[1], (x0, 271, 484, 285), a.get("full_name"), 9, white=True)
    doc.subset_fonts()
    doc.save(out_path, garbage=4, deflate=True)


# ---------- Agent Banking Agreement (.docx → .pdf) ----------

def fill_agreement(a, lead, out_docx):
    d = docx.Document(os.path.join(FORMS_DIR, "agreement.docx"))
    name = a.get("full_name") or lead.get("name") or ""
    body = d.paragraphs

    runs = body[2].runs
    runs[0].text = "THIS AGREEMENT is entered into as on "
    runs[1].text = date.today().strftime("%d/%m/%Y") + " "

    first = body[6].runs[0]
    first.text = first.text.replace("(XXXXXX ………", name).replace("(AGENT ADDRESS)………….", residence_address(a))

    sign_cell = d.tables[0].rows[2].cells[1]
    for para in sign_cell.paragraphs:
        if para.text.startswith("Name:"):
            para.runs[0].text = f"Name: {name}"
        elif para.text.startswith("Designation:"):
            para.runs[0].text = f"Designation: {APPOINTED_AS}"

    fee_runs = d.tables[1].rows[2].cells[1].paragraphs[0].runs
    fee_runs[1].text = fee_runs[1].text.replace("____________", REGISTRATION_FEE)

    # Leave room at the top of page 1 for the ₹100 e-stamp header.
    spacer = body[0].insert_paragraph_before("")
    spacer.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    spacer.paragraph_format.line_spacing = Inches(STAMP_PAPER_TOP_INCHES - 1.0625)  # minus the existing top margin

    d.save(out_docx)


def docx_to_pdf(docx_path):
    out_dir = os.path.dirname(docx_path)
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(
            ["soffice", f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", "pdf",
             "--outdir", out_dir, docx_path],
            check=True, capture_output=True, timeout=120,
        )
    return os.path.splitext(docx_path)[0] + ".pdf"


def soffice_available():
    return shutil.which("soffice") is not None
