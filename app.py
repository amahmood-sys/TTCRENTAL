"""TTC Subway Delay Dashboard."""
import datetime
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

try:
    from google.transit import gtfs_realtime_pb2
    _GTFS_RT_OK = True
except ImportError:
    _GTFS_RT_OK = False

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TTC Subway Delays",
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

GTFS_RT_ALERTS_URL = "https://bustime.ttc.ca/gtfsrt/alerts"

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


# ── Data loaders ──────────────────────────────────────────────────────────────
@st.cache_data
def load_data() -> pd.DataFrame:
    df = pd.read_csv("data/ttc_subway_delays.csv", parse_dates=["Date"])
    df["Hour"] = df["Time"].str[:2].astype(int)
    df["Month"] = df["Date"].dt.to_period("M").astype(str)
    df["YearMonth"] = df["Date"].dt.to_period("M")
    df["Day"] = pd.Categorical(df["Day"], categories=DAY_ORDER, ordered=True)
    return df


@st.cache_data(ttl=60)
def fetch_live_alerts(cache_key: int = 0):
    """Fetch TTC GTFS-RT service alerts. Returns (alerts, fetched_at, error_msg)."""
    if not _GTFS_RT_OK:
        return [], datetime.datetime.now(), "gtfs-realtime-bindings not installed"
    try:
        resp = requests.get(
            GTFS_RT_ALERTS_URL,
            timeout=10,
            headers={"User-Agent": "TTC-Dashboard/1.0"},
        )
        resp.raise_for_status()

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(resp.content)

        alerts = []
        for entity in feed.entity:
            if not entity.HasField("alert"):
                continue
            alert = entity.alert

            # Identify affected subway lines by route_id
            lines = {
                _ROUTE_TO_LINE[ie.route_id]
                for ie in alert.informed_entity
                if ie.route_id in _SUBWAY_ROUTE_IDS
            }

            header = (
                alert.header_text.translation[0].text
                if alert.header_text.translation else ""
            )
            desc = (
                alert.description_text.translation[0].text
                if alert.description_text.translation else ""
            )

            # Fall back to keyword matching in the header text
            if not lines:
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
                "lines": lines,
                "header": header,
                "description": desc,
                "label": label,
                "severity": severity,
            })

        return alerts, datetime.datetime.now(), None

    except Exception as exc:
        return [], datetime.datetime.now(), str(exc)


df_all = load_data()

# ── Sidebar filters ───────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🚇 TTC Delays")
    st.markdown("**Subway delay analytics · 2023–2024**")
    st.caption("Source: City of Toronto Open Data")
    st.divider()

    min_date = df_all["Date"].min().date()
    max_date = df_all["Date"].max().date()
    date_range = st.date_input(
        "Date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

    st.divider()
    selected_lines = st.multiselect(
        "Lines",
        options=["YU", "BD", "SHP"],
        default=["YU", "BD", "SHP"],
        format_func=lambda x: LINE_LABELS[x],
    )

    selected_days = st.multiselect(
        "Days of week",
        options=DAY_ORDER,
        default=DAY_ORDER,
    )

    st.divider()
    min_delay = st.slider("Min. delay (minutes)", 0, 30, 0)

# ── Apply filters ─────────────────────────────────────────────────────────────
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

# ── Header ────────────────────────────────────────────────────────────────────
st.title("TTC Subway Delay Dashboard")
st.caption(
    f"Showing **{len(df):,}** delay events · "
    f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"
)

# ── Live Status Section ───────────────────────────────────────────────────────
if "refresh_count" not in st.session_state:
    st.session_state.refresh_count = 0

live_alerts, fetched_at, fetch_error = fetch_live_alerts(st.session_state.refresh_count)

hdr_col, btn_col = st.columns([6, 1])
with hdr_col:
    st.subheader("Live Subway Status")
    st.caption(f"Last updated: {fetched_at.strftime('%I:%M:%S %p')} · auto-refreshes every 60 s")
with btn_col:
    if st.button("↻ Refresh", use_container_width=True):
        st.session_state.refresh_count += 1
        st.rerun()

if fetch_error:
    st.warning(f"Could not reach TTC live feed: {fetch_error}")
else:
    # Build per-line alert index
    line_alerts: dict[str, list] = {"YU": [], "BD": [], "SHP": []}
    for a in live_alerts:
        for line in a["lines"]:
            if line in line_alerts:
                line_alerts[line].append(a)

    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}

    col_yu, col_bd, col_shp = st.columns(3)
    for col, line_key in zip([col_yu, col_bd, col_shp], ["YU", "BD", "SHP"]):
        with col:
            alerts_for_line = line_alerts[line_key]
            line_name = LINE_LABELS[line_key]
            color = LINE_COLORS[line_key]
            st.markdown(
                f"<span style='color:{color};font-weight:700;font-size:1rem'>"
                f"{line_name}</span>",
                unsafe_allow_html=True,
            )
            if not alerts_for_line:
                st.success("On Time")
            else:
                worst = min(alerts_for_line, key=lambda a: severity_order[a["severity"]])
                display_fn = {
                    "error": st.error,
                    "warning": st.warning,
                    "info": st.info,
                    "success": st.success,
                }[worst["severity"]]
                display_fn(worst["label"])
                for a in alerts_for_line:
                    if a["header"]:
                        st.markdown(f"**{a['header']}**")
                    if a["description"]:
                        with st.expander("Details"):
                            st.write(a["description"])

st.divider()

if df.empty:
    st.warning("No data matches the current filters.")
    st.stop()

# ── KPI cards ─────────────────────────────────────────────────────────────────
total_delays = len(df)
avg_delay = df["Min Delay"].mean()
total_delay_min = df["Min Delay"].sum()
worst_station = df.groupby("Station")["Min Delay"].count().idxmax()
worst_line_label = LINE_LABELS[
    df.groupby("Line")["Min Delay"].count().idxmax()
].split("·")[1].strip()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Delays", f"{total_delays:,}")
k2.metric("Avg Delay", f"{avg_delay:.1f} min")
k3.metric("Total Delay Time", f"{total_delay_min:,} min")
k4.metric("Most Delayed Line", worst_line_label)
k5.metric("Most Delayed Station", worst_station)

st.divider()

# ── Row 1: Delays by line  +  Monthly trend ───────────────────────────────────
col_left, col_right = st.columns([1, 2])

with col_left:
    st.subheader("Delays by Line")
    by_line = (
        df.groupby("Line")
        .agg(Count=("Min Delay", "count"), AvgDelay=("Min Delay", "mean"))
        .reset_index()
    )
    by_line["Label"] = by_line["Line"].map(LINE_LABELS)
    fig_line = px.bar(
        by_line,
        x="Label",
        y="Count",
        color="Line",
        color_discrete_map=LINE_COLORS,
        text="Count",
        hover_data={"AvgDelay": ":.1f", "Label": False, "Line": False},
        labels={"Count": "# Delays", "Label": "Line", "AvgDelay": "Avg delay (min)"},
    )
    fig_line.update_traces(textposition="outside")
    fig_line.update_layout(
        showlegend=False,
        margin=dict(t=10, b=10),
        xaxis_title=None,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_line, use_container_width=True)

with col_right:
    st.subheader("Monthly Delay Trend")
    monthly = (
        df.groupby(["Month", "Line"])
        .agg(Count=("Min Delay", "count"))
        .reset_index()
        .sort_values("Month")
    )
    fig_trend = px.line(
        monthly,
        x="Month",
        y="Count",
        color="Line",
        color_discrete_map=LINE_COLORS,
        markers=True,
        labels={"Count": "# Delays", "Month": "Month"},
    )
    fig_trend.update_layout(
        margin=dict(t=10, b=10),
        xaxis_tickangle=-45,
        legend_title="Line",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_trend, use_container_width=True)

# ── Row 2: Hourly distribution  +  Day-of-week heatmap ───────────────────────
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("Delays by Hour of Day")
    hourly = (
        df.groupby(["Hour", "Line"])
        .size()
        .reset_index(name="Count")
    )
    fig_hour = px.bar(
        hourly,
        x="Hour",
        y="Count",
        color="Line",
        color_discrete_map=LINE_COLORS,
        barmode="stack",
        labels={"Count": "# Delays", "Hour": "Hour (24h)"},
    )
    fig_hour.update_layout(
        margin=dict(t=10, b=10),
        legend_title="Line",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(tickmode="linear", dtick=2),
    )
    st.plotly_chart(fig_hour, use_container_width=True)

with col_b:
    st.subheader("Delay Heatmap: Day × Hour")
    heat_data = (
        df.groupby(["Day", "Hour"])
        .size()
        .reset_index(name="Count")
    )
    heat_pivot = heat_data.pivot(index="Day", columns="Hour", values="Count").fillna(0)
    heat_pivot = heat_pivot.reindex([d for d in DAY_ORDER if d in heat_pivot.index])

    fig_heat = px.imshow(
        heat_pivot,
        color_continuous_scale="Reds",
        aspect="auto",
        labels={"x": "Hour", "y": "Day", "color": "# Delays"},
    )
    fig_heat.update_layout(
        margin=dict(t=10, b=10),
        coloraxis_colorbar_title="Delays",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(tickmode="linear", dtick=2),
    )
    st.plotly_chart(fig_heat, use_container_width=True)

# ── Row 3: Top stations  +  Top delay causes ──────────────────────────────────
col_c, col_d = st.columns(2)

with col_c:
    st.subheader("Top 15 Stations by Delay Count")
    top_stations = (
        df.groupby(["Station", "Line"])
        .agg(Count=("Min Delay", "count"), TotalMin=("Min Delay", "sum"))
        .reset_index()
        .nlargest(15, "Count")
        .sort_values("Count")
    )
    fig_stat = px.bar(
        top_stations,
        y="Station",
        x="Count",
        color="Line",
        color_discrete_map=LINE_COLORS,
        orientation="h",
        text="Count",
        hover_data={"TotalMin": True, "Line": False},
        labels={"Count": "# Delays", "TotalMin": "Total delay (min)"},
    )
    fig_stat.update_traces(textposition="outside")
    fig_stat.update_layout(
        margin=dict(t=10, b=10),
        showlegend=True,
        legend_title="Line",
        yaxis_title=None,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_stat, use_container_width=True)

with col_d:
    st.subheader("Top Delay Causes")
    top_causes = (
        df.groupby(["Description"])
        .agg(Count=("Min Delay", "count"), AvgMin=("Min Delay", "mean"))
        .reset_index()
        .nlargest(12, "Count")
        .sort_values("Count")
    )
    fig_cause = px.bar(
        top_causes,
        y="Description",
        x="Count",
        orientation="h",
        text="Count",
        color="AvgMin",
        color_continuous_scale="OrRd",
        labels={"Count": "# Delays", "AvgMin": "Avg delay (min)"},
    )
    fig_cause.update_traces(textposition="outside")
    fig_cause.update_layout(
        margin=dict(t=10, b=10),
        yaxis_title=None,
        coloraxis_colorbar_title="Avg min",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_cause, use_container_width=True)

# ── Row 4: Delay duration distribution ───────────────────────────────────────
st.subheader("Delay Duration Distribution by Line")
fig_box = px.box(
    df,
    x="Line",
    y="Min Delay",
    color="Line",
    color_discrete_map=LINE_COLORS,
    points="outliers",
    labels={"Min Delay": "Delay (minutes)", "Line": "Line"},
)
fig_box.update_layout(
    showlegend=False,
    margin=dict(t=10, b=10),
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(
        ticktext=[LINE_LABELS[l].split("·")[1].strip() for l in ["YU", "BD", "SHP"]],
        tickvals=["YU", "BD", "SHP"],
    ),
)
st.plotly_chart(fig_box, use_container_width=True)

# ── Raw data table ────────────────────────────────────────────────────────────
with st.expander("Raw delay data"):
    st.dataframe(
        df[["Date", "Time", "Day", "Line", "Station", "Description", "Min Delay", "Min Gap", "Bound", "Vehicle"]]
        .sort_values(["Date", "Time"], ascending=False)
        .reset_index(drop=True),
        use_container_width=True,
        height=300,
    )
