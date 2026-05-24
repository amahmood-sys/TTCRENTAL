"""Generate synthetic TTC subway delay data (2023-01-01 to 2024-12-31)."""
import numpy as np
import pandas as pd

rng = np.random.default_rng(42)

LINES = {
    "YU": [
        "Finch", "North York Centre", "Sheppard-Yonge", "York Mills", "Lawrence",
        "Eglinton", "Davisville", "St. Clair", "Summerhill", "Rosedale",
        "Bloor-Yonge", "Wellesley", "College", "Dundas", "Queen",
        "King", "Union", "St. Andrew", "Osgoode", "St. Patrick",
        "Queen's Park", "Museum", "St. George", "Spadina", "Dupont",
        "St. Clair West", "Eglinton West", "Allen", "Lawrence West",
        "Yorkdale", "Wilson", "Sheppard West", "Downsview Park", "Finch West",
        "York University", "Pioneer Village",
    ],
    "BD": [
        "Kipling", "Islington", "Royal York", "Old Mill", "Jane",
        "Runnymede", "High Park", "Keele", "Dundas West", "Lansdowne",
        "Dufferin", "Ossington", "Christie", "Bathurst", "Spadina",
        "Bay", "Bloor-Yonge", "Sherbourne", "Castle Frank", "Broadview",
        "Chester", "Pape", "Donlands", "Greenwood", "Coxwell",
        "Woodbine", "Main Street", "Victoria Park", "Warden", "Kennedy",
    ],
    "SHP": [
        "Sheppard-Yonge", "Bayview", "Bessarion", "Leslie", "Don Mills",
    ],
}

DELAY_CODES = {
    "MUPAA": ("Passenger Assistance Alarm", 5, 12),
    "SUDP":  ("Passenger Delay",            3, 8),
    "MUIS":  ("Investigation at Station",   4, 15),
    "MUPR":  ("Personal Injury",            10, 30),
    "MUATC": ("ATC / Signal Problem",       6, 20),
    "MUPSH": ("Passenger Holding Doors",    2, 6),
    "MUCE":  ("Emergency Alarm",            5, 18),
    "MUSC":  ("Security",                   4, 12),
    "TRNUP": ("Train Unable to Proceed",    8, 25),
    "MUTED": ("Medical Emergency",          8, 22),
    "EQPSS": ("Equipment / Switch",         7, 20),
    "SUDCO": ("Door Obstruction",           3, 7),
}

BOUNDS = {"YU": ["N", "S"], "BD": ["E", "W"], "SHP": ["E", "W"]}

dates = pd.date_range("2023-01-01", "2024-12-31", freq="D")

records = []
for date in dates:
    month = date.month
    is_weekend = date.weekday() >= 5

    # More delays in winter months
    base_count = 18 if is_weekend else 32
    winter_boost = 1.4 if month in (1, 2, 12) else 1.0
    n_delays = int(rng.poisson(base_count * winter_boost))

    for _ in range(n_delays):
        # Weighted line choice: YU busiest
        line = rng.choice(["YU", "BD", "SHP"], p=[0.56, 0.40, 0.04])
        station = rng.choice(LINES[line])
        code = rng.choice(list(DELAY_CODES.keys()),
                          p=[0.15, 0.14, 0.12, 0.08, 0.10,
                             0.12, 0.08, 0.07, 0.06, 0.05, 0.02, 0.01])
        _, lo, hi = DELAY_CODES[code]
        min_delay = int(rng.integers(lo, hi + 1))
        min_gap = min_delay + int(rng.integers(2, 8))
        bound = rng.choice(BOUNDS[line])

        # Bias toward rush hours on weekdays
        if is_weekend:
            # 15 values from 8..22 → equal weights summing to 1
            wp = [1/15] * 15
            hour = int(rng.choice(range(8, 23), p=wp))
        else:
            # 24 hours, peaks at rush hours (8-9, 17-18)
            raw = [0.01, 0.01, 0.01, 0.01, 0.02, 0.03,
                   0.04, 0.06, 0.09, 0.08, 0.05, 0.04,
                   0.04, 0.04, 0.05, 0.06, 0.08, 0.09,
                   0.07, 0.05, 0.04, 0.03, 0.02, 0.01]
            weights = [w / sum(raw) for w in raw]
            hour = int(rng.choice(range(24), p=weights))

        minute = int(rng.integers(0, 60))
        time_str = f"{hour:02d}:{minute:02d}"
        vehicle = int(rng.integers(5100, 6200))

        records.append({
            "Date": date.strftime("%Y-%m-%d"),
            "Time": time_str,
            "Day": date.strftime("%A"),
            "Station": station,
            "Code": code,
            "Description": DELAY_CODES[code][0],
            "Min Delay": min_delay,
            "Min Gap": min_gap,
            "Bound": bound,
            "Line": line,
            "Vehicle": vehicle,
        })

df = pd.DataFrame(records)
df.to_csv("ttc_subway_delays.csv", index=False)
print(f"Generated {len(df):,} delay records → ttc_subway_delays.csv")
