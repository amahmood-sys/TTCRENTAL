"""TTC Subway Delay Dashboard — live status + historical analysis."""
import datetime
import os
import re
import time
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

try:
    from google.transit import gtfs_realtime_pb2
    _GTFS_RT_OK = True
except ImportError:
    _GTFS_RT_OK = False

try:
    from streamlit_autorefresh import st_autorefresh
    _AUTOREFRESH_OK = True
except ImportError:
    _AUTOREFRESH_OK = False

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TTC Subway Delays — Live",
    page_icon="🚇",
    layout="wide",
    initial_sidebar_state="expanded",
)

LINE_COLORS = {"YU": "#E3131B", "BD": "#009A44", "SHP": "#A8518A"}
LINE_LABELS = {
    "YU": "Line 1 · Yonge–University",
    "BD": "Line 2 · Bloor–Danforth",
    "SHP": "Line 4 · Sheppard",
}
DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Feed URL is config, not a secret — overridable via env var without code changes.
GTFS_RT_ALERTS_URL = os.environ.get(
    "TTC_ALERTS_URL", "https://bustime.ttc.ca/gtfsrt/alerts"
)
REFRESH_SECONDS = 30
EASTERN = ZoneInfo("America/Toronto")  # Toronto time (auto EST/EDT)

# ── Hardening limits for the untrusted external feed ──────────────────────────
MAX_FEED_BYTES = 5 * 1024 * 1024   # reject feed responses larger than 5 MB
MAX_ALERTS = 500                   # cap alerts processed from one response
MAX_TEXT_LEN = 500                 # truncate any single feed text field
MANUAL_REFRESH_COOLDOWN = 5        # min seconds between manual refresh clicks


def _clean_feed_text(text: str) -> str:
    """Sanitize untrusted text from the live feed before it is rendered.

    Strips control characters, neutralizes Markdown/HTML-significant characters
    (Streamlit already escapes raw HTML, but Markdown emphasis could still be
    injected), collapses whitespace, and truncates to a bounded length.
    """
    if not isinstance(text, str):
        return ""
    text = "".join(ch for ch in text if ch == "\n" or ch >= " ")  # drop control chars
    text = re.sub(r"[*_`#\[\]<>]", "", text)                       # neutralize markdown/html
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_TEXT_LEN:
        text = text[:MAX_TEXT_LEN].rstrip() + "…"
    return text

_ROUTE_TO_LINE = {"1": "YU", "2": "BD", "4": "SHP"}
_SUBWAY_ROUTE_IDS = set(_ROUTE_TO_LINE.keys())
_LINE_KEYWORDS = {
    "YU": {"line 1", "yonge", "university", "yus"},
    "BD": {"line 2", "bloor", "danforth"},
    "SHP": {"line 4", "sheppard"},
}
_EFFECT_LABEL = {
    1: ("No Service", "error"),
    2: ("Reduced Service", "warning"),
    3: ("Significant Delays", "warning"),
    4: ("Detour", "warning"),
    5: ("Additional Service", "success"),
    6: ("Modified Service", "warning"),
    7: ("Service Advisory", "info"),
    8: ("Service Advisory", "info"),
    9: ("Stop Moved", "info"),
    10: ("On Time", "success"),
    11: ("Accessibility Issue", "info"),
}
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2, "success": 3}


# ── Data loaders ──────────────────────────────────────────────────────────────
@st.cache_data
def load_data() -> pd.DataFrame:
    df = pd.read_csv("data/ttc_subway_delays.csv", parse_dates=["Date"])
    required = {"Date", "Time", "Day", "Station", "Line", "Min Delay"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {sorted(missing)}")
    # Coerce Hour defensively — malformed Time values become NaN and are dropped.
    df["Hour"] = pd.to_numeric(df["Time"].astype(str).str[:2], errors="coerce")
    df = df.dropna(subset=["Hour"])
    df["Hour"] = df["Hour"].astype(int)
    df["Month"] = df["Date"].dt.to_period("M").astype(str)
    df["Day"] = pd.Categorical(df["Day"], categories=DAY_ORDER, ordered=True)
    return df


@st.cache_data(ttl=REFRESH_SECONDS)
def fetch_live_alerts(cache_key: int = 0):
    """Fetch TTC GTFS-RT service alerts. Returns (alerts, fetched_at, error_msg)."""
    if not _GTFS_RT_OK:
        return [], datetime.datetime.now(EASTERN), "gtfs-realtime-bindings not installed"
    try:
        resp = requests.get(
            GTFS_RT_ALERTS_URL, timeout=10,
            headers={"User-Agent": "TTC-Dashboard/1.0"},
            stream=True,
        )
        resp.raise_for_status()

        # Fast reject via Content-Length, then hard-cap the streamed body so a
        # malicious or malformed response can't exhaust memory.
        declared = resp.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_FEED_BYTES:
            return [], datetime.datetime.now(EASTERN), "Live feed response too large"
        content = bytearray()
        for chunk in resp.iter_content(chunk_size=16384):
            content.extend(chunk)
            if len(content) > MAX_FEED_BYTES:
                return [], datetime.datetime.now(EASTERN), "Live feed response too large"

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(bytes(content))

        alerts = []
        for entity in feed.entity:
            if len(alerts) >= MAX_ALERTS:  # bound work regardless of feed size
                break
            if not entity.HasField("alert"):
                continue
            alert = entity.alert

            lines = {
                _ROUTE_TO_LINE[ie.route_id]
                for ie in alert.informed_entity
                if ie.route_id in _SUBWAY_ROUTE_IDS
            }
            header = _clean_feed_text(
                alert.header_text.translation[0].text
                if alert.header_text.translation else ""
            )
            desc = _clean_feed_text(
                alert.description_text.translation[0].text
                if alert.description_text.translation else ""
            )

            if not lines:  # keyword fallback
                lower = header.lower()
                for line_key, keywords in _LINE_KEYWORDS.items():
                    if any(kw in lower for kw in keywords):
                        lines.add(line_key)
                if not lines and "subway" in lower:
                    lines = {"YU", "BD", "SHP"}
            if not lines:
                continue

            label, severity = _EFFECT_LABEL.get(alert.effect, ("Service Advisory", "info"))
            alerts.append({
                "lines": lines, "header": header, "description": desc,
                "label": label, "severity": severity,
            })

        return alerts, datetime.datetime.now(EASTERN), None
    except Exception as exc:
        return [], datetime.datetime.now(EASTERN), str(exc)


# ── Live view ─────────────────────────────────────────────────────────────────
def render_live():
    if _AUTOREFRESH_OK:
        st_autorefresh(interval=REFRESH_SECONDS * 1000, key="live_autorefresh")

    if "refresh_count" not in st.session_state:
        st.session_state.refresh_count = 0

    alerts, fetched_at, err = fetch_live_alerts(st.session_state.refresh_count)

    hdr, btn = st.columns([6, 1])
    with hdr:
        st.subheader("🔴 Live Subway Status")
        auto = f"auto-refreshes every {REFRESH_SECONDS}s" if _AUTOREFRESH_OK else "manual refresh"
        st.caption(f"Last updated {fetched_at.strftime('%I:%M:%S %p %Z')} · {auto}")
    with btn:
        if st.button("↻ Refresh", use_container_width=True):
            # Throttle manual refreshes so the button can't hammer the TTC feed.
            now_mono = time.monotonic()
            last = st.session_state.get("last_manual_refresh", 0.0)
            if now_mono - last < MANUAL_REFRESH_COOLDOWN:
                st.toast(f"Please wait {MANUAL_REFRESH_COOLDOWN}s between refreshes.")
            else:
                st.session_state.last_manual_refresh = now_mono
                st.session_state.refresh_count += 1
                st.rerun()

    if err:
        st.warning(f"Could not reach the TTC live feed: {err}")
        st.caption(
            "The live feed is provided by TTC and may be temporarily unavailable, "
            "or blocked from this host. It works from Streamlit Community Cloud."
        )
        return

    # Index alerts per line
    line_alerts = {"YU": [], "BD": [], "SHP": []}
    for a in alerts:
        for line in a["lines"]:
            if line in line_alerts:
                line_alerts[line].append(a)

    lines_with_issues = [k for k, v in line_alerts.items() if v]

    # System overview banner
    if not lines_with_issues:
        st.success("✅ All three subway lines are running normally — no active alerts.")
    else:
        names = ", ".join(LINE_LABELS[k].split("·")[0].strip() for k in lines_with_issues)
        st.warning(f"⚠️ {len(lines_with_issues)} line(s) reporting issues: {names}")

    st.write("")

    # Per-line status cards
    cols = st.columns(3)
    for col, line_key in zip(cols, ["YU", "BD", "SHP"]):
        with col:
            for_line = line_alerts[line_key]
            color = LINE_COLORS[line_key]
            st.markdown(
                f"<span style='color:{color};font-weight:700;font-size:1.05rem'>"
                f"{LINE_LABELS[line_key]}</span>",
                unsafe_allow_html=True,
            )
            if not for_line:
                st.success("On Time")
            else:
                worst = min(for_line, key=lambda a: _SEVERITY_ORDER[a["severity"]])
                {"error": st.error, "warning": st.warning,
                 "info": st.info, "success": st.success}[worst["severity"]](worst["label"])
                for a in for_line:
                    if a["header"]:
                        st.markdown(f"**{a['header']}**")
                    if a["description"]:
                        with st.expander("Details"):
                            st.write(a["description"])

    st.divider()
    st.caption(
        "Live data: TTC GTFS-Realtime service alerts feed. "
        "The subway feed reports service alerts (delays, detours, closures) rather "
        "than per-train delay minutes — which is the granularity TTC publishes."
    )


# ── Historical view ───────────────────────────────────────────────────────────
def render_history(df: pd.DataFrame, start, end):
    st.caption(
        f"Showing **{len(df):,}** delay events · "
        f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"
    )
    if df.empty:
        st.warning("No data matches the current filters.")
        return

    # KPI cards
    worst_station = df.groupby("Station")["Min Delay"].count().idxmax()
    worst_line_label = LINE_LABELS[
        df.groupby("Line")["Min Delay"].count().idxmax()
    ].split("·")[1].strip()

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Delays", f"{len(df):,}")
    k2.metric("Avg Delay", f"{df['Min Delay'].mean():.1f} min")
    k3.metric("Total Delay Time", f"{df['Min Delay'].sum():,} min")
    k4.metric("Most Delayed Line", worst_line_label)
    k5.metric("Most Delayed Station", worst_station)
    st.divider()

    # Row 1: delays by line + monthly trend
    left, right = st.columns([1, 2])
    with left:
        st.subheader("Delays by Line")
        by_line = (
            df.groupby("Line")
            .agg(Count=("Min Delay", "count"), AvgDelay=("Min Delay", "mean"))
            .reset_index()
        )
        by_line["Label"] = by_line["Line"].map(LINE_LABELS)
        fig = px.bar(
            by_line, x="Label", y="Count", color="Line",
            color_discrete_map=LINE_COLORS, text="Count",
            hover_data={"AvgDelay": ":.1f", "Label": False, "Line": False},
            labels={"Count": "# Delays", "Label": "Line", "AvgDelay": "Avg delay (min)"},
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(showlegend=False, margin=dict(t=10, b=10), xaxis_title=None,
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Monthly Delay Trend")
        monthly = (
            df.groupby(["Month", "Line"]).agg(Count=("Min Delay", "count"))
            .reset_index().sort_values("Month")
        )
        fig = px.line(monthly, x="Month", y="Count", color="Line",
                      color_discrete_map=LINE_COLORS, markers=True,
                      labels={"Count": "# Delays", "Month": "Month"})
        fig.update_layout(margin=dict(t=10, b=10), xaxis_tickangle=-45, legend_title="Line",
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    # Row 2: hourly + heatmap
    a, b = st.columns(2)
    with a:
        st.subheader("Delays by Hour of Day")
        hourly = df.groupby(["Hour", "Line"]).size().reset_index(name="Count")
        fig = px.bar(hourly, x="Hour", y="Count", color="Line",
                     color_discrete_map=LINE_COLORS, barmode="stack",
                     labels={"Count": "# Delays", "Hour": "Hour (24h)"})
        fig.update_layout(margin=dict(t=10, b=10), legend_title="Line",
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                          xaxis=dict(tickmode="linear", dtick=2))
        st.plotly_chart(fig, use_container_width=True)
    with b:
        st.subheader("Delay Heatmap: Day × Hour")
        heat = df.groupby(["Day", "Hour"]).size().reset_index(name="Count")
        pivot = heat.pivot(index="Day", columns="Hour", values="Count").fillna(0)
        pivot = pivot.reindex([d for d in DAY_ORDER if d in pivot.index])
        fig = px.imshow(pivot, color_continuous_scale="Reds", aspect="auto",
                        labels={"x": "Hour", "y": "Day", "color": "# Delays"})
        fig.update_layout(margin=dict(t=10, b=10), coloraxis_colorbar_title="Delays",
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                          xaxis=dict(tickmode="linear", dtick=2))
        st.plotly_chart(fig, use_container_width=True)

    # Row 3: top stations + top causes
    c, d = st.columns(2)
    with c:
        st.subheader("Top 15 Stations by Delay Count")
        top = (
            df.groupby(["Station", "Line"])
            .agg(Count=("Min Delay", "count"), TotalMin=("Min Delay", "sum"))
            .reset_index().nlargest(15, "Count").sort_values("Count")
        )
        fig = px.bar(top, y="Station", x="Count", color="Line",
                     color_discrete_map=LINE_COLORS, orientation="h", text="Count",
                     hover_data={"TotalMin": True, "Line": False},
                     labels={"Count": "# Delays", "TotalMin": "Total delay (min)"})
        fig.update_traces(textposition="outside")
        fig.update_layout(margin=dict(t=10, b=10), legend_title="Line", yaxis_title=None,
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
    with d:
        st.subheader("Top Delay Causes")
        causes = (
            df.groupby(["Description"])
            .agg(Count=("Min Delay", "count"), AvgMin=("Min Delay", "mean"))
            .reset_index().nlargest(12, "Count").sort_values("Count")
        )
        fig = px.bar(causes, y="Description", x="Count", orientation="h", text="Count",
                     color="AvgMin", color_continuous_scale="OrRd",
                     labels={"Count": "# Delays", "AvgMin": "Avg delay (min)"})
        fig.update_traces(textposition="outside")
        fig.update_layout(margin=dict(t=10, b=10), yaxis_title=None,
                          coloraxis_colorbar_title="Avg min",
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    # Row 4: duration distribution
    st.subheader("Delay Duration Distribution by Line")
    fig = px.box(df, x="Line", y="Min Delay", color="Line",
                 color_discrete_map=LINE_COLORS, points="outliers",
                 labels={"Min Delay": "Delay (minutes)", "Line": "Line"})
    fig.update_layout(showlegend=False, margin=dict(t=10, b=10),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(
                          ticktext=[LINE_LABELS[l].split("·")[1].strip() for l in ["YU", "BD", "SHP"]],
                          tickvals=["YU", "BD", "SHP"]))
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Raw delay data"):
        st.dataframe(
            df[["Date", "Time", "Day", "Line", "Station", "Description",
                "Min Delay", "Min Gap", "Bound", "Vehicle"]]
            .sort_values(["Date", "Time"], ascending=False).reset_index(drop=True),
            use_container_width=True, height=300,
        )


# ── App ───────────────────────────────────────────────────────────────────────
df_all = load_data()

with st.sidebar:
    st.title("🚇 TTC Delays")
    st.markdown("**Live status + delay analytics**")
    st.caption("Source: City of Toronto Open Data · TTC GTFS-RT")
    st.divider()
    st.markdown("**History filters**")
    st.caption("These apply to the History tab.")

    min_date = df_all["Date"].min().date()
    max_date = df_all["Date"].max().date()
    date_range = st.date_input(
        "Date range", value=(min_date, max_date),
        min_value=min_date, max_value=max_date,
    )
    selected_lines = st.multiselect(
        "Lines", options=["YU", "BD", "SHP"], default=["YU", "BD", "SHP"],
        format_func=lambda x: LINE_LABELS[x],
    )
    selected_days = st.multiselect("Days of week", options=DAY_ORDER, default=DAY_ORDER)
    min_delay = st.slider("Min. delay (minutes)", 0, 30, 0)

if len(date_range) == 2:
    start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
else:
    start, end = df_all["Date"].min(), df_all["Date"].max()

df = df_all[
    df_all["Date"].between(start, end)
    & df_all["Line"].isin(selected_lines)
    & df_all["Day"].isin(selected_days)
    & (df_all["Min Delay"] >= min_delay)
].copy()

st.title("TTC Subway Delay Tracker")

tab_live, tab_history = st.tabs(["🔴 Live Status", "📊 History"])
with tab_live:
    render_live()
with tab_history:
    render_history(df, start, end)
