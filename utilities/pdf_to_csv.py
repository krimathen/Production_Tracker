import pdfplumber
import csv

def pdf_to_csv(pdf_path, csv_path):
    with pdfplumber.open(pdf_path) as pdf, open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Name", "Start", "End"])  # adjust headers
        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            for row in table:
                if row and len(row) >= 4:
                    writer.writerow(row[:4])
