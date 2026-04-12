import openpyxl
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter
import os
from datetime import date

COLUMN_WIDTHS = {
    "A": 25,    # Company Name
    "B": 18,    # Type
    "C": 28,    # Location
    "D": 24,    # Geographic Area
    "E": 50,    # Why They're a Lead
    "F": 30,    # Company Website
    "G": 35,    # Source URL
    "H": 30,    # Potential Contact
    "I": 12,    # ICP Score
    "J": 55,    # Notes
    "K": 14,    # Date Found
}

HEADERS = [
    "Company Name",
    "Type",
    "Location",
    "Geographic Area",
    "Why They're a Lead",
    "Company Website",
    "Source URL",
    "Potential Contact",
    "ICP Score",
    "Notes",
    "Date Found"
]

TABLE_NAMES = {
    "Corporate": "CorporateLeads",
    "Public Sector": "PublicSectorLeads"
}

def _migrate_schema_if_needed(sheet) -> bool:
    """
    If the sheet was created before the Geographic Area column was added,
    insert an empty column D and write the correct header so existing data
    stays aligned. Returns True if a migration was performed.
    """
    if sheet.max_row < 1:
        return False
    # Old schema: column D header is "Why They're a Lead"
    # New schema: column D header is "Geographic Area"
    if sheet.cell(row=1, column=4).value == "Geographic Area":
        return False
    # Insert a blank column at position 4, shifting D:J → E:K
    sheet.insert_cols(4)
    sheet.cell(row=1, column=4).value = "Geographic Area"
    return True

def get_existing_company_names(sheet) -> set:
    existing_names = set()
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if row[0]:
            existing_names.add(row[0].strip().lower())
    return existing_names

def get_existing_leads_for_segment(segment: str) -> list[str]:
    DATA_DIR = os.environ.get("DATA_DIR", ".")
    filename = os.path.join(DATA_DIR, "leads.xlsx")
    sheet_names = {"corporate": "Corporate", "public_sector": "Public Sector"}
    sheet_name = sheet_names.get(segment, "Corporate")

    if not os.path.exists(filename):
        return []

    workbook = openpyxl.load_workbook(filename)
    if sheet_name not in workbook.sheetnames:
        return []

    sheet = workbook[sheet_name]
    names = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if row[0]:
            names.append(row[0].strip())
    return names

def get_all_leads_for_segment(segment: str) -> list[dict]:
    DATA_DIR = os.environ.get("DATA_DIR", ".")
    filename = os.path.join(DATA_DIR, "leads.xlsx")
    sheet_names = {"corporate": "Corporate", "public_sector": "Public Sector"}
    sheet_name = sheet_names.get(segment, "Corporate")

    if not os.path.exists(filename):
        return []

    workbook = openpyxl.load_workbook(filename)
    if sheet_name not in workbook.sheetnames:
        return []

    sheet = workbook[sheet_name]
    leads = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if row[0]:
            leads.append({
                "company_name": row[0] or "",
                "type": row[1] or "",
                "location": row[2] or "",
                "geographic_area": row[3] or "",
                "why_a_lead": row[4] or "",
                "company_website": row[5] or "",
                "source_url": row[6] or "",
                "potential_contact": row[7] or "",
                "icp_score": row[8] or 0,
                "notes": row[9] or "",
                "date_found": str(row[10]) if len(row) > 10 and row[10] else ""
            })
    return leads

def _apply_table_formatting(sheet, sheet_name):
    sheet.tables.clear()

    max_row = sheet.max_row
    if max_row < 2:
        return

    max_col = len(HEADERS)
    ref = f"A1:{get_column_letter(max_col)}{max_row}"
    table_name = TABLE_NAMES.get(sheet_name, "Leads")

    table = Table(displayName=table_name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium9",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False
    )
    sheet.add_table(table)

    for col_letter, width in COLUMN_WIDTHS.items():
        sheet.column_dimensions[col_letter].width = width

    wrap_alignment = Alignment(wrap_text=True, vertical="top")
    for row in sheet.iter_rows(min_row=2, max_row=max_row, max_col=max_col):
        for cell in row:
            cell.alignment = wrap_alignment

def save_leads_to_spreadsheet(leads: list[dict], segment: str = "corporate") -> tuple[str, list[dict]]:
    """
    Returns a tuple: (result_message, actually_saved_leads)
    """
    DATA_DIR = os.environ.get("DATA_DIR", ".")
    filename = os.path.join(DATA_DIR, "leads.xlsx")
    sheet_names = {"corporate": "Corporate", "public_sector": "Public Sector"}
    sheet_name = sheet_names.get(segment, "Corporate")

    if os.path.exists(filename):
        workbook = openpyxl.load_workbook(filename)
    else:
        workbook = openpyxl.Workbook()
        workbook.active.title = "Corporate"

    if sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        _migrate_schema_if_needed(sheet)
    else:
        sheet = workbook.create_sheet(title=sheet_name)
        sheet.append(HEADERS)

    if sheet.cell(row=1, column=1).value != HEADERS[0]:
        sheet.insert_rows(1)
        for col_idx, header in enumerate(HEADERS, 1):
            sheet.cell(row=1, column=col_idx, value=header)

    existing_names = get_existing_company_names(sheet)

    saved_count = 0
    skipped_count = 0
    actually_saved = []
    today = date.today().strftime("%Y-%m-%d")

    for lead in leads:
        company_name = lead.get("company_name", "").strip()
        if company_name.lower() in existing_names:
            skipped_count += 1
            print(f"Skipping duplicate: {company_name}")
        else:
            row = [
                company_name,
                lead.get("type", ""),
                lead.get("location", ""),
                lead.get("geographic_area", ""),
                lead.get("why_a_lead", ""),
                lead.get("company_website", ""),
                lead.get("source_url", ""),
                lead.get("potential_contact", ""),
                lead.get("icp_score", ""),
                lead.get("notes", ""),
                today
            ]
            sheet.append(row)
            saved_count += 1
            existing_names.add(company_name.lower())
            actually_saved.append(lead)

    _apply_table_formatting(sheet, sheet_name)
    workbook.save(filename)
    message = f"Saved {saved_count} new leads to '{sheet_name}', skipped {skipped_count} duplicates."
    return message, actually_saved
