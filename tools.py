import openpyxl
import os
from datetime import date

def get_existing_company_names(sheet) -> set:
    """
    Reads a sheet and returns a set of company names already in it.
    """
    existing_names = set()
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if row[0]:
            existing_names.add(row[0].strip().lower())
    return existing_names

def get_existing_leads_for_segment(segment: str) -> list[str]:
    """
    Returns a list of company names already saved for a given segment.
    Used to tell Claude which companies to skip before it starts searching.
    """
    DATA_DIR = os.environ.get("DATA_DIR", ".")
    filename = os.path.join(DATA_DIR, "leads.xlsx")

    sheet_names = {
        "corporate": "Corporate",
        "public_sector": "Public Sector"
    }
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
    """
    Returns all leads for a segment as a list of dicts.
    Used to display existing leads in the web UI.
    """
    DATA_DIR = os.environ.get("DATA_DIR", ".")
    filename = os.path.join(DATA_DIR, "leads.xlsx")

    sheet_names = {
        "corporate": "Corporate",
        "public_sector": "Public Sector"
    }
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
                "why_a_lead": row[3] or "",
                "company_website": row[4] or "",
                "source_url": row[5] or "",
                "potential_contact": row[6] or "",
                "icp_score": row[7] or 0,
                "notes": row[8] or "",
                "date_found": str(row[9]) if len(row) > 9 and row[9] else ""
            })
    return leads

def save_leads_to_spreadsheet(leads: list[dict], segment: str = "corporate") -> str:
    """
    Takes a list of leads and writes them to the correct sheet in leads.xlsx.
    Corporate leads go to Sheet 1, public sector leads go to Sheet 2.
    Skips duplicates within each sheet.
    """
    DATA_DIR = os.environ.get("DATA_DIR", ".")
    filename = os.path.join(DATA_DIR, "leads.xlsx")
    
    sheet_names = {
        "corporate": "Corporate",
        "public_sector": "Public Sector"
    }
    sheet_name = sheet_names.get(segment, "Corporate")
    
    headers = [
        "Company Name",
        "Type",
        "Location",
        "Why They're a Lead",
        "Company Website",
        "Source URL",
        "Potential Contact",
        "ICP Score",
        "Notes",
        "Date Found"
    ]

    # Open existing file or create new one
    if os.path.exists(filename):
        workbook = openpyxl.load_workbook(filename)
    else:
        workbook = openpyxl.Workbook()
        workbook.active.title = "Corporate"

    # Get or create the target sheet
    if sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
    else:
        sheet = workbook.create_sheet(title=sheet_name)
        sheet.append(headers)

    # Get existing company names from this sheet
    existing_names = get_existing_company_names(sheet)

    # Write new leads, skipping duplicates
    saved_count = 0
    skipped_count = 0
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

    workbook.save(filename)
    return f"Saved {saved_count} new leads to '{sheet_name}', skipped {skipped_count} duplicates."