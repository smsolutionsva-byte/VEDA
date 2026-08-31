"""Generate the Project 218 regression fixture for the document-decomposition pipeline.

Writes two files into sample_data/:

  Project_218_P6_Style_Activities.csv                - authoritative schedule
  Daily_Construction_Report_218_TEXT_EXTRACTABLE.pdf - field evidence (real,
                                                       text-extractable PDF)

Project 218 is ONLY a test fixture. No production code references these names.

Run:  .venv\\Scripts\\python.exe tools\\make_project_218_fixture.py
"""
from __future__ import annotations

import csv
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "sample_data"
OUT.mkdir(exist_ok=True)

CSV_PATH = OUT / "Project_218_P6_Style_Activities.csv"
PDF_PATH = OUT / "Daily_Construction_Report_218_TEXT_EXTRACTABLE.pdf"

# Activity ID, Name, WBS, Start, Finish, Baseline Start, Baseline Finish,
# Predecessors, % Complete, Status, Duration
ACTIVITIES = [
    ("P218-STR-Z1-010", "Formworks column - Grnd floor", "Project 218.Structural.Zone 1",
     "2017-08-14", "2017-08-25", "2017-08-14", "2017-08-25", "", "80", "in_progress", "10"),
    ("P218-STR-Z1-020", "Rebar fixing column - Grnd floor", "Project 218.Structural.Zone 1",
     "2017-08-21", "2017-08-30", "2017-08-21", "2017-08-30", "P218-STR-Z1-010", "40", "in_progress", "8"),
    ("P218-STR-Z2-040", "Scaffolding erection for first flr slab", "Project 218.Structural.Zone 2",
     "2017-09-11", "2017-09-22", "2017-09-11", "2017-09-22", "", "70", "in_progress", "10"),
    ("P218-STR-Z2-090", "Concrete pouring for grade slab Zone 2", "Project 218.Structural.Zone 2",
     "2017-09-25", "2017-09-27", "2017-09-25", "2017-09-27", "P218-STR-Z2-040", "0", "not_started", "3"),
    ("P218-STR-Z3-050", "Formworks drop beams -1st flr", "Project 218.Structural.Zone 3",
     "2017-09-18", "2017-09-29", "2017-09-18", "2017-09-29", "P218-STR-Z2-040", "35", "in_progress", "10"),
    ("P218-STR-Z3-060", "Formworks first floor slab", "Project 218.Structural.Zone 3",
     "2017-09-20", "2017-10-03", "2017-09-20", "2017-10-03", "P218-STR-Z3-050", "45", "in_progress", "10"),
    ("P218-PT-Z3-070", "Post tension duct installation-1st flr", "Project 218.Post Tensioning.Zone 3",
     "2017-09-25", "2017-10-05", "2017-09-25", "2017-10-05", "P218-STR-Z3-060", "20", "in_progress", "9"),
    ("P218-MEP-Z3-080", "Plumbing sleeve installation-1st flr", "Project 218.MEP.Zone 3",
     "2017-09-25", "2017-10-04", "2017-09-25", "2017-10-04", "P218-STR-Z3-060", "15", "in_progress", "8"),
    ("P218-STR-Z3-130", "Concrete pouring of first floor slab at Zone 3", "Project 218.Structural.Zone 3",
     "2017-10-04", "2017-10-06", "2017-10-04", "2017-10-06", "P218-PT-Z3-070,P218-MEP-Z3-080", "0", "not_started", "3"),
    ("P218-STR-Z3-140", "Formworks second floor slab", "Project 218.Structural.Zone 3",
     "2017-10-09", "2017-10-20", "2017-10-09", "2017-10-20", "P218-STR-Z3-130", "0", "not_started", "10"),
    ("P218-MEP-Z2-110", "HVAC duct erection ground floor", "Project 218.MEP.Zone 2",
     "2017-09-14", "2017-09-28", "2017-09-14", "2017-09-28", "", "55", "in_progress", "12"),
    ("P218-STR-Z1-030", "Concrete pouring column - Grnd floor", "Project 218.Structural.Zone 1",
     "2017-08-28", "2017-08-30", "2017-08-28", "2017-08-30", "P218-STR-Z1-020", "0", "not_started", "3"),
]

CSV_HEADERS = ["Activity ID", "Activity Name", "WBS", "Start", "Finish",
               "Baseline Start", "Baseline Finish", "Predecessors",
               "% Complete", "Status", "Duration"]


def write_csv() -> None:
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADERS)
        w.writerows(ACTIVITIES)
    print("wrote", CSV_PATH)


DCR_LINES = [
    "Daily Construction Report",
    "Report No: DCR-218-0456",
    "Project: Project 218 - Downtown Commercial Tower",
    "Date: 10.03.2017",
    "Contractor: Meridian BuildCo LLC",
    "Weather: Clear, 33 C, light wind",
    "Prepared by: Site Engineer R. Advani",
    "",
    "WORK PROGRESS",
    "Description | Location | Unit | Total Qty | Planned Today | Achieved Today | Plan Next Day | Cumulative | % Complete",
    "Formworks first floor slab | Zone 3 | m2 | 2000 | 500 | 300 | 200 | 1200 | 60",
    "Formworks drop beams -1st flr | Zone 3 | m2 |  |  |  |  |  | ",
    "Post tension duct installation-1st flr | Zone 3 | nos | 120 | 20 | 15 | 20 | 78 | ",
    "Plumbing sleeve installation-1st flr | Zone 3 | nos | 60 | 12 | 9 | 12 | 41 | ",
    "Scaffolding erection for first flr slab | Zone 2 | m3 | 300 | 40 | 35 | 40 | 245 | 82",
    "Formworks column - Grnd floor | Zone 1 | m2 | 800 | 0 | 0 | 60 | 640 | 80",
    "",
    "MANPOWER",
    "Trade | Count",
    "Site Foreman | 2",
    "Steel Fixer | 14",
    "Carpenter | 18",
    "Welder | 3",
    "Helper | 22",
    "",
    "EQUIPMENT",
    "Equipment | Count | Hours",
    "Tower Crane | 1 | 9",
    "Concrete Pump | 1 | 4",
    "Passenger Hoist | 2 | 8",
    "",
    "ANTICIPATED ACTIVITIES",
    "Concrete pouring of first floor slab at Zone 3 - planned 04-Oct-17",
    "Formworks second floor slab Zone 3 - planned 09-Oct-17",
    "",
    "CRITICAL CONCERN / ISSUES",
    "Description | Reference | Raised | Work Affected | Plan Start",
    "Change of beam dimension design and additional drop beams | F0649/2020-F/2017 | 21-Sep-17 | Concrete pouring of first floor slab at Zone 3 | 4-Oct-17",
    "MEP final design drawings including HVAC opening in slab | F0683/2020-F/2017 | 26-Jul-17 | Concrete pouring of first floor slab at Zone 3 | 4-Oct-17",
    "",
    "SIGN-OFF",
    "Prepared by: R. Advani (Site Engineer)   Approved by: K. Osei (Project Manager)",
]


def write_pdf() -> None:
    import pymupdf  # PyMuPDF; ships with VEDA

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    x, y, leading = 40, 54, 15.0
    fontname, fontsize = "helv", 8.6
    for line in DCR_LINES:
        if y > 800:
            page = doc.new_page(width=595, height=842)
            y = 54
        page.insert_text((x, y), line, fontsize=fontsize, fontname=fontname)
        y += leading
    doc.save(PDF_PATH, deflate=True)
    doc.close()
    print("wrote", PDF_PATH)

    # Sanity: confirm the PDF is genuinely text-extractable with pypdf.
    from pypdf import PdfReader
    text = "\n".join((p.extract_text() or "") for p in PdfReader(str(PDF_PATH)).pages)
    assert "WORK PROGRESS" in text and "Formworks first floor slab" in text, \
        "generated PDF is not text-extractable"
    print("  verified: pypdf extracts", len(text), "characters")


if __name__ == "__main__":
    write_csv()
    write_pdf()
