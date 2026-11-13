from docx import Document
from openpyxl import load_workbook
print("===== QUESTIONNAIRE =====")
d = Document("/app/var/CRM_answered.docx")
for para in d.paragraphs:
    t = para.text.strip()
    if t:
        print(t)
        print("---")
print("\n===== MUQAVILE FORM =====")
d2 = Document("/app/var/Muqavile_form.docx")
for para in d2.paragraphs:
    t = para.text.strip()
    if t:
        print(t)
        print("---")
for ti, table in enumerate(d2.tables):
    print(f"--- TABLE {ti} ---")
    for row in table.rows:
        cells = [c.text.strip().replace("\n", " | ") for c in row.cells]
        if any(cells):
            print(" || ".join(cells))
print("\n===== YENI MUSTERI XLSX =====")
wb = load_workbook("/app/var/Yeni_musteri.xlsx", read_only=True, data_only=True)
for sn in wb.sheetnames:
    ws = wb[sn]
    print(f"--- SHEET: {sn} ---")
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i > 45:
            print("...truncated...")
            break
        vals = [str(c) if c is not None else "" for c in row]
        if any(v.strip() for v in vals):
            print(" | ".join(vals[:15]))
