from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st


APP_TITLE = "Inventory Management Agent"
DATA_DIR = Path("data")

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


def render_inwarding() -> None:
    st.header("Inwarding Parts")
    st.write("Use this for parts received from suppliers, GRN entries, gate entry checks, and arrival tracking.")
    df = load_table("inwarding_parts")
    received_total = numeric(df.get("Received Qty", pd.Series(dtype=str))).sum() if not df.empty else 0
    cols = st.columns(3)
    with cols[0]:
        render_metric("Inwarding rows", len(df), "neutral")
    with cols[1]:
        render_metric("Received qty", f"{received_total:,.0f}", "ok")
    with cols[2]:
        render_metric("Suppliers", df["Supplier"].replace("", pd.NA).dropna().nunique() if not df.empty else 0, "neutral")
    st.subheader("Editable Inwarding Table")
    render_editable_table("inwarding_parts")


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
    st.write("This starter app stores editable tables as CSV files in the `data/` folder.")
    st.markdown(
        """
        For two people working together:

        - Code changes should happen through GitHub branches.
        - App usage can happen through one shared Streamlit URL.
        - For real production data sharing, move the CSV tables to Google Sheets or a database.
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
elif page == "Inwarding Parts":
    render_inwarding()
elif page == "Outwarding Parts":
    render_outwarding()
elif page == "Agentic Flow":
    render_agentic_flow()
else:
    render_setup()
