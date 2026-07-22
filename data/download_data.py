"""
Build data/ttc_subway_delays.csv from the official TTC subway delay dataset
(City of Toronto Open Data, 2023-2024).

The primary source is the City of Toronto Open Data portal:
    https://open.toronto.ca/dataset/ttc-subway-delay-data/

That portal blocks some cloud/CI IP ranges, so this script pulls the same
official raw XLSX files mirrored in a public GitHub repository, then applies
the delay-code descriptions and writes a clean CSV with the schema the
dashboard expects.

Usage:
    python data/download_data.py
"""
import io
import sys
import requests
import pandas as pd

RAW_BASE = "https://raw.githubusercontent.com/asvath/SmartTransit/main/data/raw"
DELAY_FILES = [
    f"{RAW_BASE}/delays/ttc-subway-delay-data-2023.xlsx",
    f"{RAW_BASE}/delays/ttc-subway-delay-data-2024.xlsx",
]
CODES_FILE = f"{RAW_BASE}/code_descriptions/ttc-subway-delay-codes.xlsx"
HEADERS = {"User-Agent": "Mozilla/5.0"}
OUT = "data/ttc_subway_delays.csv"

FINAL_COLUMNS = [
    "Date", "Time", "Day", "Station", "Code",
    "Description", "Min Delay", "Min Gap", "Bound", "Line", "Vehicle",
]


def load_code_map() -> dict:
    r = requests.get(CODES_FILE, timeout=60, headers=HEADERS)
    r.raise_for_status()
    raw = pd.read_excel(io.BytesIO(r.content))
    code_map = {}
    # Two code tables side by side: SUB codes (cols 2,3) and SRT codes (cols 6,7)
    for _, row in raw.iterrows():
        for c_idx, d_idx in [(2, 3), (6, 7)]:
            code, desc = row.iloc[c_idx], row.iloc[d_idx]
            if isinstance(code, str) and isinstance(desc, str):
                code, desc = code.strip(), desc.strip()
                if code and "CODE" not in code:
                    code_map[code] = desc
    return code_map


def load_delays() -> pd.DataFrame:
    frames = []
    for url in DELAY_FILES:
        r = requests.get(url, timeout=90, headers=HEADERS)
        r.raise_for_status()
        xls = pd.ExcelFile(io.BytesIO(r.content))
        for sheet in xls.sheet_names:
            frames.append(xls.parse(sheet))
        print(f"  fetched {url.split('/')[-1]}")
    return pd.concat(frames, ignore_index=True)


def clean(df: pd.DataFrame, code_map: dict) -> pd.DataFrame:
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    df["Time"] = df["Time"].astype(str).str.strip().str[:5]

    df["Line"] = df["Line"].astype(str).str.strip().str.upper()
    df = df[df["Line"].isin(["YU", "BD", "SHP"])]

    df["Description"] = (
        df["Code"].astype(str).str.strip().map(code_map)
        .fillna(df["Code"].astype(str).str.strip())
    )
    df["Station"] = (
        df["Station"].astype(str)
        .str.replace(" STATION", "", regex=False).str.title().str.strip()
    )

    for col in ("Min Delay", "Min Gap", "Vehicle"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    df["Bound"] = df["Bound"].fillna("").astype(str).str.strip()
    df = df[df["Station"].str.strip().ne("") & df["Station"].str.lower().ne("nan")]
    return df[FINAL_COLUMNS]


def main():
    print("Building real TTC subway delay dataset (2023-2024)…")
    try:
        code_map = load_code_map()
        print(f"  loaded {len(code_map)} delay-code descriptions")
        delays = load_delays()
    except Exception as e:
        print(f"\nERROR: download failed — {e}")
        sys.exit(1)

    df = clean(delays, code_map)
    df.to_csv(OUT, index=False)
    print(f"\nSaved {len(df):,} real delay records → {OUT}")
    print("Date range:", df["Date"].min(), "–", df["Date"].max())
    print("Lines:", df["Line"].value_counts().to_dict())


if __name__ == "__main__":
    main()
