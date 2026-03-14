import openpyxl
import os

def get_existing_company_names(sheet) -> set:
    """
    Reads a sheet and returns a set of company names already in it.
    """
    existing_names = set()
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if row[0]:
            existing_names.add(row[0].strip().lower())
    return existing_names

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
        "Notes"
    ]

    # Open existing file or create new one
    if os.path.exists(filename):
        workbook = openpyxl.load_workbook(filename)
    else:
        workbook = openpyxl.Workbook()
        # Rename the default sheet to Corporate
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
                lead.get("notes", "")
            ]
            sheet.append(row)
            saved_count += 1
            existing_names.add(company_name.lower())

    workbook.save(filename)
    return f"Saved {saved_count} new leads to '{sheet_name}', skipped {skipped_count} duplicates."