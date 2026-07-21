"""
Download real TTC subway delay data from the City of Toronto Open Data portal.
Run this locally (not in the cloud container) — the portal blocks cloud IPs.

Usage:
    python data/download_data.py

Outputs:
    data/ttc_subway_delays.csv   (same schema the dashboard expects)
"""
import sys
import io
import requests
import pandas as pd

CKAN_URL = "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show"
PACKAGE_ID = "ttc-subway-delay-data"

COLUMN_MAP = {
    # Portal column name variants → our canonical name
    "Report Date": "Date",
    "report date":  "Date",
    "Time":         "Time",
    "time":         "Time",
    "Day":          "Day",
    "day":          "Day",
    "Station":      "Station",
    "station":      "Station",
    "Code":         "Code",
    "code":         "Code",
    "Min Delay":    "Min Delay",
    "min delay":    "Min Delay",
    "Min Gap":      "Min Gap",
    "min gap":      "Min Gap",
    "Bound":        "Bound",
    "bound":        "Bound",
    "Line":         "Line",
    "line":         "Line",
    "Vehicle":      "Vehicle",
    "vehicle":      "Vehicle",
    "Incident":     "Description",
    "incident":     "Description",
    "Description":  "Description",
}

DELAY_CODE_DESC = {
    "MUPAA": "Passenger Assistance Alarm",
    "SUDP":  "Passenger Delay",
    "MUIS":  "Investigation at Station",
    "MUPR":  "Personal Injury",
    "MUATC": "ATC / Signal Problem",
    "MUPSH": "Passenger Holding Doors",
    "MUCE":  "Emergency Alarm",
    "MUSC":  "Security",
    "TRNUP": "Train Unable to Proceed",
    "MUTED": "Medical Emergency",
    "EQPSS": "Equipment / Switch",
    "SUDCO": "Door Obstruction",
}


def fetch_resource_list():
    resp = requests.get(CKAN_URL, params={"id": PACKAGE_ID}, timeout=20)
    resp.raise_for_status()
    resources = resp.json()["result"]["resources"]
    xlsx = [r for r in resources if r.get("format", "").upper() in ("XLSX", "XLS")]
    print(f"Found {len(xlsx)} Excel resources.")
    return xlsx


def download_one(resource):
    name = resource.get("name", "unknown")
    url = resource["url"]
    print(f"  Downloading: {name} …", end=" ", flush=True)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content))
    df = df.rename(columns={c: COLUMN_MAP.get(c, c) for c in df.columns})
    print(f"{len(df):,} rows")
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Normalise date
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")

    # Normalise time
    if "Time" in df.columns:
        df["Time"] = df["Time"].astype(str).str.strip().str[:5]

    # Keep only subway lines
    if "Line" in df.columns:
        df["Line"] = df["Line"].astype(str).str.strip().str.upper()
        df = df[df["Line"].isin({"YU", "BD", "SHP", "1", "2", "4"})]
        df["Line"] = df["Line"].replace({"1": "YU", "2": "BD", "4": "SHP"})

    # Fill description from code if missing
    if "Code" in df.columns and "Description" not in df.columns:
        df["Description"] = df["Code"].map(DELAY_CODE_DESC).fillna(df["Code"])

    # Coerce numeric columns
    for col in ("Min Delay", "Min Gap", "Vehicle"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # Drop rows missing core fields
    df = df.dropna(subset=["Date", "Line"])
    return df


def main():
    print("Fetching TTC subway delay data from Toronto Open Data …\n")
    try:
        resources = fetch_resource_list()
    except Exception as e:
        print(f"\nERROR: Could not reach the Toronto Open Data portal.\n{e}")
        print("\nNote: This script must be run on your local machine, not in a cloud container.")
        sys.exit(1)

    frames = []
    for res in resources:
        try:
            frames.append(download_one(res))
        except Exception as e:
            print(f"  SKIP ({e})")

    if not frames:
        print("No data downloaded.")
        sys.exit(1)

    df = pd.concat(frames, ignore_index=True)
    df = clean(df)

    out = "data/ttc_subway_delays.csv"
    df.to_csv(out, index=False)
    print(f"\nSaved {len(df):,} real delay records → {out}")
    print("Date range:", df["Date"].min(), "–", df["Date"].max())
    print("Lines:", df["Line"].value_counts().to_dict())


if __name__ == "__main__":
    main()
