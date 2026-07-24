from __future__ import annotations

import re
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import streamlit as st


APP_TITLE = "Inventory Management Agent"
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
LIVE_GRN_CSV = DATA_DIR / "live" / "grn_live.csv"
LIVE_GRN_META = LIVE_GRN_CSV.with_suffix(".json")
GRN_EXPORT_SCRIPT = APP_DIR / "scripts" / "scheduled_grn_export.py"
DEFAULT_GOOGLE_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1V3ic-5Dfcz0PoX-0Z0gXdIrFIIOB_lSh-gM20RzLUKs/edit?gid=2111379627#gid=2111379627"
)

TABLES = {
    "part_inventory": {
        "file": DATA_DIR / "part_inventory.csv",
        "title": "Part Inventory",
        "columns": [
            "Buyer",
            "Supplier",
            "Part No.",
            "Part Name",
            "Required Qty",
            "Opening Stock",
            "System Stock",
            "Physical Stock",
            "Closing Stock",
            "Status",
            "Remarks",
        ],
    },
    "inwarding_parts": {
        "file": DATA_DIR / "inwarding_parts.csv",
        "title": "Inwarding Parts",
        "columns": [
            "Buyer",
            "Supplier",
            "Part No.",
            "Part Name",
            "Received Qty",
            "Arrival Date",
            "Arrival Time",
            "PO Number",
            "Plant",
            "Storage Location",
            "Remarks",
        ],
    },
    "outwarding_parts": {
        "file": DATA_DIR / "outwarding_parts.csv",
        "title": "Outwarding Parts",
        "columns": [
            "Buyer",
            "Supplier",
            "Part No.",
            "Part Name",
            "Used Qty",
            "Usage Date",
            "Usage Source",
            "Reference No.",
            "Remarks",
        ],
    },
}


st.set_page_config(page_title=APP_TITLE, layout="wide")


def load_table(key: str) -> pd.DataFrame:
    config = TABLES[key]
    path = config["file"]
    columns = config["columns"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_csv(path, dtype=str).fillna("")
    for column in columns:
        if column not in df.columns:
            df[column] = ""
    return df[columns]


def save_table(key: str, df: pd.DataFrame) -> None:
    config = TABLES[key]
    path = config["file"]
    columns = config["columns"]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cleaned = df.copy().fillna("")
    for column in columns:
        if column not in cleaned.columns:
            cleaned[column] = ""
    cleaned = cleaned[columns]
    tmp_path = path.with_suffix(".tmp")
    cleaned.to_csv(tmp_path, index=False)
    tmp_path.replace(path)


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0)


def normalize_column_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized = {normalize_column_name(column): column for column in df.columns}
    for candidate in candidates:
        column = normalized.get(normalize_column_name(candidate))
        if column:
            return column
    return None


def column_or_blank(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    column = first_existing_column(df, candidates)
    if not column:
        return pd.Series([""] * len(df), index=df.index, dtype=str)
    return df[column].fillna("").astype(str).str.strip()


def parse_grn_dates(series: pd.Series) -> pd.Series:
    values = series.fillna("").astype(str).str.strip()
    dates = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    yyyymmdd = values.str.fullmatch(r"\d{8}", na=False)
    dates.loc[yyyymmdd] = pd.to_datetime(values.loc[yyyymmdd], format="%Y%m%d", errors="coerce")
    dates.loc[~yyyymmdd] = pd.to_datetime(values.loc[~yyyymmdd], errors="coerce")
    return dates


def format_grn_dates(series: pd.Series) -> pd.Series:
    dates = parse_grn_dates(series)
    formatted = dates.dt.strftime("%Y-%m-%d")
    return formatted.fillna(series.fillna("").astype(str).str.strip())


def format_grn_times(series: pd.Series) -> pd.Series:
    def format_one(value: object) -> str:
        text = str(value or "").strip()
        if not text or text.lower() == "nan":
            return ""
        if "." in text and text.replace(".", "", 1).isdigit():
            text = text.split(".", 1)[0]
        digits = re.sub(r"\D", "", text)
        if ":" in text:
            return text
        if 1 <= len(digits) <= 6:
            digits = digits.zfill(6)
            return f"{digits[:2]}:{digits[2:4]}:{digits[4:6]}"
        return text

    return series.apply(format_one)


def load_live_grn() -> pd.DataFrame:
    if not LIVE_GRN_CSV.exists():
        return pd.DataFrame()
    return pd.read_csv(LIVE_GRN_CSV, dtype=str).fillna("")


def load_live_grn_meta() -> dict[str, object]:
    if not LIVE_GRN_META.exists():
        return {}
    try:
        return json.loads(LIVE_GRN_META.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def run_grn_export() -> tuple[bool, str]:
    if not GRN_EXPORT_SCRIPT.exists():
        return False, f"Exporter script not found: {GRN_EXPORT_SCRIPT}"
    try:
        result = subprocess.run(
            [sys.executable, str(GRN_EXPORT_SCRIPT)],
            cwd=APP_DIR,
            text=True,
            capture_output=True,
            timeout=240,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "The Superset GRN export timed out after 4 minutes."
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    if "Zscaler" in output or "company policy prohibits" in output or "Website blocked" in output:
        return (
            False,
            "The live export reached the internal Trino/Superset host, but the company network blocked it through Zscaler. "
            "Run the app/export from the normal VPN/ZPA-enabled environment, or configure `GRN_EXPORT_SOURCE=superset_api` "
            "with a Superset service account in `config/grn_export.env`.",
        )
    if "plain HTTP request was sent to HTTPS port" in output:
        return False, "Use `TRINO_HTTP_SCHEME=https` for this host. Port 443 rejected plain HTTP."
    if len(output) > 4000:
        output = output[-4000:]
    return result.returncode == 0, output or "Export finished."


def grn_file_age_label() -> str:
    if not LIVE_GRN_CSV.exists():
        return "not created yet"
    modified_at = datetime.fromtimestamp(LIVE_GRN_CSV.stat().st_mtime)
    seconds = max(0, int((datetime.now() - modified_at).total_seconds()))
    if seconds < 90:
        return "just now"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hr ago"
    return f"{hours // 24} days ago"


def build_grn_display_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "Buyer",
                "Supplier",
                "Part No.",
                "Part Name",
                "Rcvd Qty",
                "Arrival Time",
                "Arrival Date",
                "PO Number",
                "Storage Location",
                "Plant",
                "Movement Type",
                "UOM",
                "Source Row",
            ]
        )

    result = pd.DataFrame(index=df.index)
    result["Buyer"] = column_or_blank(df, ["buyer", "buyer_name"])
    result["Supplier"] = column_or_blank(df, ["supplier", "supplier_name", "vendor", "vendor_name"])
    result["Part No."] = column_or_blank(df, ["part_no", "matnr", "material", "material_code"])
    result["Part Name"] = column_or_blank(df, ["part_name", "part_description", "material_description", "maktx"])
    result["Rcvd Qty"] = column_or_blank(df, ["received_qty", "rcvd_qty", "menge", "actual_quantity_received"])
    result["Arrival Time"] = format_grn_times(column_or_blank(df, ["arrival_time", "sap_entry_time", "cputm"]))
    result["Arrival Date"] = format_grn_dates(column_or_blank(df, ["arrival_date", "grn_date", "sap_entry_date", "budat", "posting_date"]))
    result["PO Number"] = column_or_blank(df, ["po_no", "po_number", "ebeln"])
    result["Storage Location"] = column_or_blank(df, ["storage_location", "lgort"])
    result["Plant"] = column_or_blank(df, ["plant", "werks"])
    result["Movement Type"] = column_or_blank(df, ["movement_type", "bwart"])
    result["UOM"] = column_or_blank(df, ["uom", "meins"])
    result["Source Row"] = (pd.Series(range(1, len(df) + 1), index=df.index)).astype(str)
    return result


def parse_google_sheet_url(url: str) -> tuple[str, str]:
    match = re.search(r"/spreadsheets/d/([^/]+)", url)
    if not match:
        raise ValueError("This does not look like a Google Sheets link.")
    spreadsheet_id = match.group(1)
    parsed = urlparse(url)
    query_gid = parse_qs(parsed.query).get("gid", ["0"])[0]
    fragment_gid_match = re.search(r"gid=(\d+)", parsed.fragment or "")
    gid = fragment_gid_match.group(1) if fragment_gid_match else query_gid
    return spreadsheet_id, gid


def google_sheet_csv_url(url: str) -> str:
    spreadsheet_id, gid = parse_google_sheet_url(url)
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"


def load_google_sheet(url: str) -> pd.DataFrame:
    csv_url = google_sheet_csv_url(url)
    return pd.read_csv(csv_url, dtype=str).fillna("")


def build_inventory_status(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    result = df.copy()
    required = numeric(result["Required Qty"])
    closing = numeric(result["Closing Stock"])
    physical = numeric(result["Physical Stock"])
    stock = closing.where(closing != 0, physical)
    result["Status"] = "Healthy"
    result.loc[required <= 0, "Status"] = "Requirement missing"
    result.loc[(required > 0) & (stock < required), "Status"] = "Below required"
    result.loc[(required > 0) & (stock <= 0), "Status"] = "Critical"
    return result


def render_metric(label: str, value: object, tone: str = "neutral") -> None:
    colors = {
        "neutral": ("#eff6ff", "#2563eb"),
        "ok": ("#ecfdf5", "#16a34a"),
        "warn": ("#fffbeb", "#d97706"),
        "bad": ("#fef2f2", "#dc2626"),
    }
    bg, accent = colors.get(tone, colors["neutral"])
    st.markdown(
        f"""
        <div class="metric-card" style="background:{bg}; border-left-color:{accent};">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def filter_frame(df: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    if df.empty:
        return df
    search = st.text_input("Search", placeholder="buyer, supplier, part number, part name", key=f"{key_prefix}_search")
    filtered = df.copy()
    if search:
        term = search.strip().lower()
        filtered = filtered[
            filtered.astype(str)
            .apply(lambda col: col.str.lower().str.contains(term, na=False))
            .any(axis=1)
        ]
    return filtered


def render_editable_table(key: str) -> pd.DataFrame:
    config = TABLES[key]
    df = load_table(key)
    if key == "part_inventory":
        df = build_inventory_status(df)

    filtered = filter_frame(df, key)
    st.caption(f"{len(filtered):,} rows shown. Add rows directly in the table, then press Save.")
    edited = st.data_editor(
        filtered,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key=f"{key}_editor",
    )

    left, right = st.columns([1, 5])
    with left:
        if st.button("Save changes", key=f"{key}_save", type="primary"):
            save_table(key, edited)
            st.success("Saved.")
            st.rerun()
    with right:
        st.download_button(
            "Download CSV",
            edited.to_csv(index=False),
            file_name=f"{key}.csv",
            mime="text/csv",
            key=f"{key}_download",
        )
    return edited


def render_part_inventory() -> None:
    st.header("Part Inventory")
    st.write("Current stock position by buyer, supplier, and part.")
    df = build_inventory_status(load_table("part_inventory"))
    total = len(df)
    healthy = int((df["Status"] == "Healthy").sum()) if total else 0
    below = int((df["Status"] == "Below required").sum()) if total else 0
    critical = int((df["Status"] == "Critical").sum()) if total else 0

    cols = st.columns(4)
    with cols[0]:
        render_metric("Parts tracked", total, "neutral")
    with cols[1]:
        render_metric("Healthy", healthy, "ok")
    with cols[2]:
        render_metric("Below required", below, "warn")
    with cols[3]:
        render_metric("Critical", critical, "bad")

    st.subheader("Editable Inventory Table")
    render_editable_table("part_inventory")


def render_live_google_sheet() -> None:
    st.header("Live Google Sheet")
    st.write("This page reads directly from your Google Sheet. When the sheet changes, refresh this page or press reload.")

    sheet_url = st.text_input(
        "Google Sheet link",
        value=DEFAULT_GOOGLE_SHEET_URL,
        help="The sheet must be shared as Anyone with link can view, or published to web.",
    )
    left, right = st.columns([1, 5])
    with left:
        reload_clicked = st.button("Reload sheet", type="primary")
    with right:
        st.caption("Use this as the shared live source. Do not paste private tokens here.")

    if reload_clicked:
        st.cache_data.clear()

    try:
        df = load_google_sheet(sheet_url)
    except Exception as exc:
        st.error("Could not read the Google Sheet.")
        st.write("Most likely reason: the sheet is private.")
        st.write("Fix: in Google Sheets, click Share and give Viewer access to anyone with the link.")
        st.code(str(exc))
        return

    cols = st.columns(3)
    with cols[0]:
        render_metric("Rows", f"{len(df):,}", "neutral")
    with cols[1]:
        render_metric("Columns", f"{len(df.columns):,}", "neutral")
    with cols[2]:
        render_metric("Source", "Google Sheet", "ok")

    filtered = filter_frame(df, "live_google_sheet")
    st.caption(f"{len(filtered):,} rows shown from the live Google Sheet.")
    st.dataframe(filtered, use_container_width=True, hide_index=True)
    st.download_button(
        "Download live view as CSV",
        filtered.to_csv(index=False),
        file_name="live_google_sheet.csv",
        mime="text/csv",
    )


def render_inwarding() -> None:
    st.header("Inwarding Parts")
    st.write(
        "Live GRN inwarding from the Superset/Trino source. "
        "This page does not use sample data or the previous app's files."
    )

    top_left, top_right = st.columns([1, 4])
    with top_left:
        if st.button("Run live export now", type="primary"):
            ok, message = run_grn_export()
            if ok:
                st.success(message)
                st.rerun()
            else:
                st.error("Live Superset GRN export failed.")
                st.code(message)
    with top_right:
        st.caption(
            f"Source file for this new app: `{LIVE_GRN_CSV.relative_to(APP_DIR)}`. "
            f"Last refreshed: {grn_file_age_label()}."
        )

    if not LIVE_GRN_CSV.exists():
        st.warning("No live Superset GRN export exists yet for this new app.")
        st.write("Press **Run live export now** after `config/grn_export.env` is configured on this machine.")
        st.code("python scripts/scheduled_grn_export.py", language="bash")
        return

    raw_df = load_live_grn()
    meta = load_live_grn_meta()
    grn_df = build_grn_display_frame(raw_df)
    if grn_df.empty:
        st.warning("The live Superset GRN export exists, but it has no rows.")
        return

    grn_dates = parse_grn_dates(grn_df["Arrival Date"])
    valid_dates = grn_dates.dropna()
    if not valid_dates.empty:
        latest_date = valid_dates.max().date()
        default_start = latest_date - timedelta(days=2)
        default_end = latest_date
    else:
        default_start = datetime.now().date() - timedelta(days=2)
        default_end = datetime.now().date()

    filter_row_1 = st.columns(4)
    with filter_row_1[0]:
        start_date = st.date_input("Start date", value=default_start, key="grn_start_date")
    with filter_row_1[1]:
        end_date = st.date_input("End date", value=default_end, key="grn_end_date")
    with filter_row_1[2]:
        plants = sorted(value for value in grn_df["Plant"].unique() if value)
        selected_plants = st.multiselect("Plant", plants, default=[], key="grn_plants")
    with filter_row_1[3]:
        locations = sorted(value for value in grn_df["Storage Location"].unique() if value)
        selected_locations = st.multiselect("Storage location", locations, default=[], key="grn_locations")

    filter_row_2 = st.columns(3)
    with filter_row_2[0]:
        part_query = st.text_input("Part No. contains", key="grn_part_query")
    with filter_row_2[1]:
        po_query = st.text_input("PO Number contains", key="grn_po_query")
    with filter_row_2[2]:
        movement_types = sorted(value for value in grn_df["Movement Type"].unique() if value)
        selected_movements = st.multiselect("Movement type", movement_types, default=[], key="grn_movements")

    filtered = grn_df.copy()
    filtered_dates = parse_grn_dates(filtered["Arrival Date"])
    if not valid_dates.empty:
        filtered = filtered[(filtered_dates.dt.date >= start_date) & (filtered_dates.dt.date <= end_date)]
    if selected_plants:
        filtered = filtered[filtered["Plant"].isin(selected_plants)]
    if selected_locations:
        filtered = filtered[filtered["Storage Location"].isin(selected_locations)]
    if selected_movements:
        filtered = filtered[filtered["Movement Type"].isin(selected_movements)]
    if part_query.strip():
        filtered = filtered[filtered["Part No."].str.contains(part_query.strip(), case=False, na=False)]
    if po_query.strip():
        filtered = filtered[filtered["PO Number"].str.contains(po_query.strip(), case=False, na=False)]

    received_total = numeric(filtered["Rcvd Qty"]).sum()
    unique_parts = filtered["Part No."].replace("", pd.NA).dropna().nunique()
    latest_visible = parse_grn_dates(filtered["Arrival Date"]).max()
    exported_at = str(meta.get("exported_at_utc", "") or "").replace("T", " ").replace("+00:00", " UTC")

    metrics = st.columns(4)
    with metrics[0]:
        render_metric("GRN rows", f"{len(filtered):,}", "neutral")
    with metrics[1]:
        render_metric("Received qty", f"{received_total:,.0f}", "ok")
    with metrics[2]:
        render_metric("Parts", f"{unique_parts:,}", "neutral")
    with metrics[3]:
        latest_label = latest_visible.strftime("%Y-%m-%d") if pd.notna(latest_visible) else "not available"
        render_metric("Latest date", latest_label, "neutral")

    if exported_at:
        st.caption(f"Exported at: {exported_at}. Raw Superset rows in file: {len(raw_df):,}.")
    else:
        st.caption(f"Raw Superset rows in file: {len(raw_df):,}.")

    st.subheader("Live GRN Inwarding Table")
    st.dataframe(
        filtered,
        use_container_width=True,
        hide_index=True,
        height=560,
    )
    st.download_button(
        "Download filtered GRN CSV",
        filtered.to_csv(index=False),
        file_name="live_superset_grn_filtered.csv",
        mime="text/csv",
    )


def render_outwarding() -> None:
    st.header("Outwarding Parts")
    st.write("Use this for production consumption, servicing usage, line issue, and other outward movements.")
    df = load_table("outwarding_parts")
    used_total = numeric(df.get("Used Qty", pd.Series(dtype=str))).sum() if not df.empty else 0
    cols = st.columns(3)
    with cols[0]:
        render_metric("Outwarding rows", len(df), "neutral")
    with cols[1]:
        render_metric("Used qty", f"{used_total:,.0f}", "warn")
    with cols[2]:
        render_metric("Usage sources", df["Usage Source"].replace("", pd.NA).dropna().nunique() if not df.empty else 0, "neutral")
    st.subheader("Editable Outwarding Table")
    render_editable_table("outwarding_parts")


def render_agentic_flow() -> None:
    st.header("Agentic Flow")
    st.write("Simple operating logic for the inventory agent.")
    steps = [
        ("1. Capture inwarding", "Record supplier receipts, arrival date/time, PO, plant, and storage location."),
        ("2. Capture outwarding", "Record production usage, servicing usage, and other material movement."),
        ("3. Update stock", "Maintain opening, system, physical, and closing stock by part."),
        ("4. Flag risk", "Mark parts below required quantity or with missing requirement/stock data."),
        ("5. Follow up", "Buyer uses the flagged list to follow up with the supplier or SCM owner."),
    ]
    for title, text in steps:
        st.markdown(f"<div class='flow-step'><b>{title}</b><br>{text}</div>", unsafe_allow_html=True)


def render_setup() -> None:
    st.header("Setup")
    st.write("This starter app stores manual tables as CSV files and reads live GRN inwarding through the Superset export.")
    st.markdown(
        """
        For two people working together:

        - Code changes should happen through GitHub branches.
        - App usage can happen through one shared Streamlit URL.
        - Use the Live Google Sheet page when you want changes in a Google Sheet to show in the app.
        - Use the Inwarding Parts page for live Superset GRN data.
        - Configure `config/grn_export.env` locally; do not commit that file.
        - The live GRN CSV is generated at `data/live/grn_live.csv` in this new app only.
        - For private production data, move from public CSV export to a proper Google service account or database.
        """
    )


st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; max-width: 1440px; }
    h1, h2, h3 { letter-spacing: 0; }
    .metric-card {
        border: 1px solid #dbe3ef;
        border-left: 6px solid #2563eb;
        border-radius: 8px;
        padding: 18px 18px;
        min-height: 112px;
    }
    .metric-label {
        color: #64748b;
        font-weight: 700;
        font-size: 0.9rem;
        margin-bottom: 12px;
    }
    .metric-value {
        color: #0f172a;
        font-size: 2rem;
        line-height: 1.1;
        font-weight: 800;
    }
    .flow-step {
        border: 1px solid #dbe3ef;
        border-left: 5px solid #2563eb;
        border-radius: 8px;
        padding: 16px 18px;
        margin: 12px 0;
        background: #ffffff;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


with st.sidebar:
    st.title(APP_TITLE)
    page = st.radio(
        "Navigation",
        [
            "Part Inventory",
            "Live Google Sheet",
            "Inwarding Parts",
            "Outwarding Parts",
            "Agentic Flow",
            "Setup",
        ],
        label_visibility="collapsed",
    )


st.title(APP_TITLE)

if page == "Part Inventory":
    render_part_inventory()
elif page == "Live Google Sheet":
    render_live_google_sheet()
elif page == "Inwarding Parts":
    render_inwarding()
elif page == "Outwarding Parts":
    render_outwarding()
elif page == "Agentic Flow":
    render_agentic_flow()
else:
    render_setup()
