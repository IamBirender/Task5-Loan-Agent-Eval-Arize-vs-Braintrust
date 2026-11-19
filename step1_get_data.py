"""STEP 1 - Data preparation (run on YOUR OWN computer).

  On your computer: checks the 5 Fannie Mae files, cleans the data (108 -> 61 columns) and builds
                    data/loans.duckdb and data/kb_passages.json (the prepared data).
  Anywhere else (for example an EC2 eval box): upload only those 2 prepared files into data/; this step then just
                    checks them. The raw Fannie Mae files never need to leave your computer.
  This step does not clone the AWS sample repo. SQL safety and citation check live in this repo.

Fannie Mae's terms do not allow us to re-share their files, so each person downloads them in a web browser
(no login needed) and saves them in the data/ folder with the names below.
Usage:  python step1_get_data.py
"""
import sys

from loan_agents import data

PAGE = "https://capitalmarkets.fanniemae.com"
FILES = {  # file name to save in data/  ->  where to download it
    "sf-loan-performance-data-sample.csv": PAGE + "/resources/file/credit-risk/xls/sf-loan-performance-data-sample.csv",
    "crt-file-layout-and-glossary.pdf": PAGE + "/media/6931/display",
    "sf-loan-performance-dataset-faqs.pdf": PAGE + "/media/8921/display",
    "FNMA_SF_Loan_Performance_Stat_Summary_Primary.pdf": PAGE + "/media/document/pdf/FNMA_SF_Loan_Performance_Stat_Summary_Primary.pdf",
    "loan-performance-data-tutorial.pdf": PAGE + "/media/9066/display",
}
data.DATA.mkdir(exist_ok=True)
raw_present = data.SAMPLE_CSV.exists()
if raw_present:   # ---- data preparation (local) ----
    missing = [n for n in FILES if not (data.DATA / n).exists()]
    for name in FILES:
        print(f"{'MISSING' if name in missing else 'ok':7}  data/{name}")
    if missing:
        print("\nOpen each link below in your web browser and save the file into the data/ folder with the name shown:")
        for n in missing:
            print(f"  {n}\n      {FILES[n]}")
        sys.exit(1)
    report = data.build_db()
    print(f"ok       cleaning: kept {report['kept']} of 108 columns (dropped {report['empty']} empty columns) -> results/data_cleaning.md")
    print(f"ok       data/kb_passages.json  ({data.build_kb()} passages from the 5 Fannie Mae documents)")
elif not (data.DB_FILE.exists() and data.KB_FILE.exists()):
    print("No data found. Put the 2 prepared files you received (loans.duckdb and kb_passages.json) into the data/ folder,\n"
          "or put the 5 raw Fannie Mae files into data/ to prepare the data yourself.")
    sys.exit(1)
else:
    print("ok       using the prepared data files data/loans.duckdb and data/kb_passages.json")

con = data.connect()
loans, rows = con.execute("SELECT count(DISTINCT loan_identifier), count(*) FROM loan_monthly").fetchone()
cols = len(con.execute("DESCRIBE loan_monthly").fetchall()) - 1   # minus the added period_ym helper column
print(f"ok       data/loans.duckdb  ({loans} loans, {rows} monthly records, {cols} source columns)")
assert (loans, rows, cols) == (8, 757, 61), "The prepared data is not what the test cases expect (8 loans, 757 records, 61 columns)."
