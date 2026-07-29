from __future__ import annotations

import re
import json
import os
import hashlib
import subprocess
import sys
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import pandas as pd
import requests
import streamlit as st
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow


APP_TITLE = "Inventory Management Agent"
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
AUTO_REFRESH_INTERVAL_SECONDS = 15 * 60
LIVE_GRN_CSV = DATA_DIR / "live" / "grn_live.csv"
LIVE_GRN_META = LIVE_GRN_CSV.with_suffix(".json")
LIVE_GOOGLE_SHEET_SNAPSHOT_CSV = DATA_DIR / "live" / "google_sheet_snapshot.csv"
LIVE_GOOGLE_SHEET_SNAPSHOT_META = LIVE_GOOGLE_SHEET_SNAPSHOT_CSV.with_suffix(".json")
SPOC_SUMMARY_SNAPSHOT_CSV = DATA_DIR / "live" / "spoc_summary_snapshot.csv"
SPOC_SUMMARY_SNAPSHOT_META = SPOC_SUMMARY_SNAPSHOT_CSV.with_suffix(".json")
GRN_EXPORT_SCRIPT = APP_DIR / "scripts" / "scheduled_grn_export.py"
DEFAULT_GOOGLE_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1V3ic-5Dfcz0PoX-0Z0gXdIrFIIOB_lSh-gM20RzLUKs/edit?gid=2111379627#gid=2111379627"
)
DEFAULT_SPOC_SUMMARY_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1j3cRrw-O5TzBEICHYvfUBcQBRyZveYEmR3TD7wLfIzo/edit?gid=543512006#gid=543512006"
)
BUYER_NAME_ALIASES = {
    "kavipriya": "Kavipriya",
    "subash": "Subhash",
    "subhash": "Subhash",
}
GOOGLE_SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
GOOGLE_OAUTH_SCOPE = GOOGLE_SHEETS_READONLY_SCOPE
GOOGLE_TOKEN_PATH = APP_DIR / ".streamlit" / "google_oauth_token.json"
GOOGLE_STATE_PATH = APP_DIR / ".streamlit" / "google_oauth_state.txt"
PRODUCTION_SHEET_ID = "1KLvkeqE71PwJN6keLuIqQYLywfFvvQa7sCq9bo-Ii6I"
BOM_SHEET_ID = "1dXeJ6dkDoxgyLlkapGFyws75i3ck2-TYeemvq-dKZ9Y"
SCM_REV_SHEET_ID = "147vIBFZxf6aQddMG-cpQmuFtcM-6nH0pjn0HDHMyLhE"


def sheet_url(spreadsheet_id: str, gid: int) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        f"?gid={gid}#gid={gid}"
    )


SOURCE_SHEETS = {
    "scm_stock_summary": {
        "url": sheet_url(SCM_REV_SHEET_ID, 0),
        "cache": DATA_DIR / "scm_stock_summary.csv",
    },
    "daily_plan_summary": {
        "url": sheet_url(PRODUCTION_SHEET_ID, 1380714334),
        "cache": DATA_DIR / "daily_plan_summary.csv",
    },
    "production_plan_breakup": {
        "url": sheet_url(PRODUCTION_SHEET_ID, 643919697),
        "cache": DATA_DIR / "production_plan_breakup.csv",
    },
    "vin_details": {
        "url": sheet_url(PRODUCTION_SHEET_ID, 1559707768),
        "cache": DATA_DIR / "vin_details_daily.csv",
    },
    "sku_map": {
        "url": sheet_url(PRODUCTION_SHEET_ID, 514997806),
        "cache": DATA_DIR / "daywise_sku_map.csv",
    },
    "exploded_bom": {
        "url": sheet_url(BOM_SHEET_ID, 1116146509),
        "cache": DATA_DIR / "exploded_bom.csv",
    },
    "raw_bom": {
        "url": sheet_url(BOM_SHEET_ID, 1001674488),
        "cache": DATA_DIR / "raw_bom.csv",
    },
    "part_types": {
        "url": sheet_url(BOM_SHEET_ID, 1024064922),
        "cache": DATA_DIR / "part_type_mapping.csv",
    },
    "suppliers": {
        "url": sheet_url(BOM_SHEET_ID, 1323700198),
        "cache": DATA_DIR / "part_supplier_mapping.csv",
    },
}
COMPUTED_USAGE_CACHE_PATH = DATA_DIR / "computed_part_usage.csv"
INWARDING_SHEET_URL = DEFAULT_GOOGLE_SHEET_URL
INWARDING_SNAPSHOT_PATH = DATA_DIR / "inwarding_sheet_snapshot.csv"
INWARDING_SNAPSHOT_META_PATH = DATA_DIR / "inwarding_sheet_snapshot.json"
BUYER_MAPPING_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    f"{SCM_REV_SHEET_ID}/edit?gid=0#gid=0"
)
BUYER_MAPPING_CACHE_PATH = DATA_DIR / "buyer_mapping_source.csv"
AGENT_ACTIONS_PATH = DATA_DIR / "agent_actions.csv"
RM_FOLLOWUPS_PATH = DATA_DIR / "rm_followups.csv"
PVIN_INPUTS_PATH = DATA_DIR / "pvin_variant_inputs.csv"
HEADER_PARTS_SUPPLEMENT_PATH = DATA_DIR / "header_parts_supplement.csv"
VARIANT_OPERATING_OVERRIDES_PATH = DATA_DIR / "variant_operating_overrides.csv"
INVENTORY_CONTROL_CASES_PATH = DATA_DIR / "inventory_control_cases.csv"
INVENTORY_CORRECTIONS_PATH = DATA_DIR / "inventory_correction_requests.csv"
PVIN_INPUT_COLUMNS = [
    "Plan Date",
    "Variant",
    "Generated P-VIN",
    "Produced P-VIN",
]
VARIANT_OPERATING_OVERRIDE_COLUMNS = [
    "Plan Date",
    "Model",
    "Planned Qty",
    "Visibility Qty",
    "P-VIN Produced Qty",
    "VNA Qty",
    "Free VIN Qty",
    "Produced Qty",
]
RM_FOLLOWUP_COLUMNS = [
    "Part No.",
    "Supplier Status",
    "Next Expected Qty",
    "Expected Delivery",
    "Next Follow-up",
    "Follow-up Owner",
    "Follow-up Notes",
]
INVENTORY_CONTROL_CASE_COLUMNS = [
    "Case ID",
    "Active",
    "Part No.",
    "Part Name",
    "Buyer",
    "Supplier",
    "Unexplained Delta",
    "Status",
    "Recommended Action",
    "First Detected",
    "Last Checked",
    "Resolved At",
]
INVENTORY_CORRECTION_COLUMNS = [
    "Request ID",
    "Part No.",
    "Part Name",
    "Stock Field",
    "Current Value",
    "Proposed Value",
    "Reason",
    "Requested By",
    "Approver",
    "Status",
    "Requested At",
    "Decision At",
]
AGENT_ACTION_COLUMNS = [
    "Action ID",
    "Active",
    "Issue Type",
    "Severity",
    "Buyer Name",
    "Supplier Name",
    "Part Number",
    "Part Name",
    "Gate Entry No",
    "Entry Date",
    "Invoice Qty",
    "Receipt Qty",
    "Difference Qty",
    "Latest Production Demand",
    "Production Impact",
    "Reason",
    "Status",
    "Age (days)",
    "Escalation",
    "First Detected",
    "Last Checked",
    "Acknowledged At",
    "Resolved At",
    "Notes",
]

TABLES = {
    "part_inventory": {
        "file": DATA_DIR / "part_inventory.csv",
        "title": "Part Inventory",
        "columns": [
            "Buyer",
            "Supplier",
            "Part No.",
            "Part Name",
            "Plan Date",
            "Daily Production Plan",
            "Produced So Far",
            "Planned Part Consumption",
            "Consumed So Far",
            "Remaining Part Need",
            "Required Qty",
            "Operational Shortage",
            "Today's OS",
            "Parts Inwarded",
            "Production Outwarded",
            "Other Outwarded",
            "Parts Outwarded",
            "Tomorrow's OS",
            "System Stock",
            "Physical Stock",
            "Generated Consumption",
            "Produced Consumption",
            "COGI Qty",
            "Stock Delta",
            "Expected Delta",
            "Unexplained Delta",
            "Delta Flag",
            "SCM Stock Match",
            "Stock Data Status",
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


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = re.sub(r"\s+", " ", str(value).strip())
    if text.lower() in {"", "nan", "none", "nat", "na", "n/a", "-", "#n/a"}:
        return ""
    return text


def normalize_buyer_name(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    alias_key = re.sub(r"[^a-z0-9]+", "", text.lower())
    if alias_key in BUYER_NAME_ALIASES:
        return BUYER_NAME_ALIASES[alias_key]
    return " ".join(part.capitalize() for part in text.split(" "))


def normalize_supplier_name(value: object) -> str:
    text = clean_text(value)
    return text.upper() if text else ""


def stock_part_key(value: object) -> str:
    text = clean_text(value)
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text.upper()


def scm_base_part_key(value: object) -> str:
    """Remove one trailing revision/suffix solely for mismatch diagnostics."""
    return re.sub(r"(?:/[A-Z0-9]+|_[A-Z0-9]+)$", "", stock_part_key(value))


def display_qty(value: object) -> str:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").fillna(0).iloc[0]
    return f"{number:,.0f}" if float(number).is_integer() else f"{number:,.1f}"


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


def google_sheets_credentials_configured() -> bool:
    try:
        if "google_service_account" in st.secrets:
            return True
    except Exception:
        pass
    return bool(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    )


def google_sheets_credentials():
    try:
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError("Install Google API packages first: pip install -r requirements.txt") from exc

    info = None
    try:
        if "google_service_account" in st.secrets:
            info = dict(st.secrets["google_service_account"])
    except Exception:
        info = None

    if info:
        if "private_key" in info:
            info["private_key"] = str(info["private_key"]).replace("\\n", "\n")
        return service_account.Credentials.from_service_account_info(
            info,
            scopes=[GOOGLE_SHEETS_READONLY_SCOPE],
        )

    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if credentials_path:
        return service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=[GOOGLE_SHEETS_READONLY_SCOPE],
        )

    credentials_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if credentials_json:
        info = json.loads(credentials_json)
        if "private_key" in info:
            info["private_key"] = str(info["private_key"]).replace("\\n", "\n")
        return service_account.Credentials.from_service_account_info(
            info,
            scopes=[GOOGLE_SHEETS_READONLY_SCOPE],
        )

    raise RuntimeError(
        "Google Sheets API credentials are not configured. Add `.streamlit/secrets.toml` "
        "with `[google_service_account]`, then share the Google Sheet with that service-account email."
    )


def google_sheets_service():
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError("Install Google API packages first: pip install -r requirements.txt") from exc
    return build("sheets", "v4", credentials=google_sheets_credentials(), cache_discovery=False)


def sheet_title_from_gid(service, spreadsheet_id: str, gid: str) -> str:
    metadata = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))")
        .execute()
    )
    sheets = metadata.get("sheets", [])
    if not sheets:
        raise ValueError("The spreadsheet has no visible sheets.")
    for sheet in sheets:
        properties = sheet.get("properties", {})
        if str(properties.get("sheetId", "")) == str(gid):
            return str(properties.get("title", ""))
    return str(sheets[0].get("properties", {}).get("title", ""))


def load_google_sheet_api_raw(url: str) -> pd.DataFrame:
    spreadsheet_id, gid = parse_google_sheet_url(url)
    service = google_sheets_service()
    sheet_title = sheet_title_from_gid(service, spreadsheet_id, gid)
    safe_title = sheet_title.replace("'", "''")
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"'{safe_title}'!A:ZZ")
        .execute()
    )
    rows = result.get("values", [])
    if not rows:
        return pd.DataFrame()
    width = max(len(row) for row in rows)
    padded_rows = [row + [""] * (width - len(row)) for row in rows]
    return pd.DataFrame(padded_rows, dtype=str).fillna("")


def raw_sheet_to_table(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw
    header_row = 0
    for index in range(min(len(raw), 20)):
        non_blank_count = sum(bool(clean_text(value)) for value in raw.iloc[index].tolist())
        if non_blank_count >= 2:
            header_row = index
            break
    columns = [clean_text(value) or f"Column {idx + 1}" for idx, value in enumerate(raw.iloc[header_row].tolist())]
    table = raw.iloc[header_row + 1 :].copy()
    table.columns = columns
    return table.reset_index(drop=True).fillna("")


def google_sheet_csv_url(url: str) -> str:
    spreadsheet_id, gid = parse_google_sheet_url(url)
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"


def load_google_sheet(url: str) -> pd.DataFrame:
    if google_sheets_credentials_configured():
        return raw_sheet_to_table(load_google_sheet_api_raw(url))
    csv_url = google_sheet_csv_url(url)
    return pd.read_csv(csv_url, dtype=str).fillna("")


def load_google_sheet_raw(url: str) -> pd.DataFrame:
    if google_sheets_credentials_configured():
        return load_google_sheet_api_raw(url)
    csv_url = google_sheet_csv_url(url)
    raw = pd.read_csv(csv_url, dtype=str, header=None, keep_default_na=False).fillna("")
    if raw.empty:
        return raw
    first_cell = str(raw.iat[0, 0]).lower()
    if "<html" in first_cell or "unauthorized" in first_cell or "sign in" in first_cell:
        raise ValueError("Google did not return sheet data. The sheet is probably private.")
    return raw


def save_sheet_snapshot(raw: pd.DataFrame, snapshot_path: Path, meta_path: Path, source_url: str, source_label: str) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = snapshot_path.with_suffix(snapshot_path.suffix + ".tmp")
    raw.fillna("").to_csv(tmp_path, index=False, header=False)
    tmp_path.replace(snapshot_path)
    meta = {
        "source_url": source_url,
        "source": source_label,
        "rows": int(len(raw)),
        "columns": int(raw.shape[1]) if not raw.empty else 0,
        "copied_at": datetime.now().isoformat(timespec="seconds"),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def load_sheet_snapshot(snapshot_path: Path) -> pd.DataFrame:
    if not snapshot_path.exists():
        return pd.DataFrame()
    return pd.read_csv(snapshot_path, dtype=str, header=None, keep_default_na=False).fillna("")


def load_snapshot_meta(meta_path: Path) -> dict[str, object]:
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def create_sheet_snapshot(source_url: str, snapshot_path: Path, meta_path: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    source_label = "Google Sheets API" if google_sheets_credentials_configured() else "CSV export link"
    raw = load_google_sheet_raw(source_url)
    save_sheet_snapshot(raw, snapshot_path, meta_path, source_url, source_label)
    return raw, load_snapshot_meta(meta_path)


def show_google_sheet_access_help(exc: Exception) -> None:
    st.write("This means the Streamlit app is not allowed to read the Google Sheet.")
    st.write("Being logged in to Google on Chrome does not log in the Python app running Streamlit.")
    st.markdown(
        """
        **Quick fix**

        1. Open the Google Sheet.
        2. Click **Share**.
        3. Under **General access**, choose **Anyone with the link**.
        4. Set it to **Viewer**.
        5. Come back here and click the copy/update button again.

        **Private-company-data fix**

        1. Configure `.streamlit/secrets.toml` from `.streamlit/secrets.toml.example`.
        2. Paste the Google service-account JSON values there.
        3. Share the Google Sheet with the service account `client_email` as **Viewer**.
        """
    )
    st.code(str(exc))


def snapshot_age_label(snapshot_path: Path) -> str:
    if not snapshot_path.exists():
        return "no copy yet"
    modified_at = datetime.fromtimestamp(snapshot_path.stat().st_mtime)
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


def parse_report_date(value: object) -> pd.Timestamp:
    text = clean_text(value)
    if not text:
        return pd.NaT
    parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
    if pd.notna(parsed):
        return parsed
    for fmt in ("%d-%b", "%d %b", "%d/%m", "%m/%d"):
        try:
            parsed_dt = datetime.strptime(text, fmt)
            return pd.Timestamp(year=datetime.now().year, month=parsed_dt.month, day=parsed_dt.day)
        except ValueError:
            continue
    return pd.NaT


def find_spoc_header_row(raw: pd.DataFrame) -> int | None:
    max_rows = min(len(raw), 30)
    for row_index in range(max_rows):
        headers = {normalize_column_name(value) for value in raw.iloc[row_index].tolist() if clean_text(value)}
        has_part = bool(headers.intersection({"component", "part_no", "part_number"}))
        has_supplier = bool(headers.intersection({"supplier", "supplier_name"}))
        has_buyer = bool(headers.intersection({"scm_buyer", "buyer", "buyer_name"}))
        if has_part and has_supplier and has_buyer:
            return row_index
    return None


def sheet_col(headers: list[str], *names: str) -> int | None:
    wanted = {normalize_column_name(name) for name in names}
    for index, header in enumerate(headers):
        if normalize_column_name(header) in wanted:
            return index
    return None


def sheet_col_contains(headers: list[str], *terms: str) -> int | None:
    wanted = [term.lower() for term in terms]
    for index, header in enumerate(headers):
        label = clean_text(header).lower()
        if label and all(term in label for term in wanted):
            return index
    return None


def choose_latest_group_date_column(raw: pd.DataFrame, header_row: int, *group_terms: str) -> tuple[int | None, str]:
    if raw.empty:
        return None, ""
    group_row = max(header_row - 1, 0)
    start_col = None
    terms = [term.lower() for term in group_terms]
    for col in range(raw.shape[1]):
        group_label = clean_text(raw.iat[group_row, col]).lower()
        if any(term in group_label for term in terms):
            start_col = col
            break
    if start_col is None:
        return None, ""

    candidates: list[tuple[int, pd.Timestamp, str]] = []
    for col in range(start_col, raw.shape[1]):
        group_label = clean_text(raw.iat[group_row, col]).lower()
        header_label = clean_text(raw.iat[header_row, col])
        if col != start_col and group_label:
            break
        parsed = parse_report_date(header_label)
        if pd.notna(parsed):
            candidates.append((col, parsed, header_label))
        elif candidates and header_label:
            break
    if not candidates:
        return None, ""
    col, _, label = sorted(candidates, key=lambda item: item[1])[-1]
    return col, label


def raw_cell(raw: pd.DataFrame, row: int, col: int | None) -> object:
    if col is None or row >= len(raw) or col >= raw.shape[1]:
        return ""
    return raw.iat[row, col]


def parse_spoc_summary_raw(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    columns = [
        "Buyer",
        "Supplier",
        "Part No.",
        "Part Name",
        "Opening Stock",
        "MRP / Requirement",
        "Initial Commitment",
        "Closing Stock",
        "Stock Gap",
        "Status",
    ]
    empty = pd.DataFrame(columns=columns)
    header_row = find_spoc_header_row(raw)
    if header_row is None:
        return empty, {"error": "Could not find Summary headers: Component, Supplier, SCM Buyer."}

    headers = [clean_text(value) for value in raw.iloc[header_row].tolist()]
    part_col = sheet_col(headers, "component", "part_no", "part_number")
    part_name_col = sheet_col(headers, "object_description", "part_description", "description", "part_name")
    supplier_col = sheet_col(headers, "supplier", "supplier_name")
    buyer_col = sheet_col(headers, "scm_buyer", "buyer", "buyer_name")
    opening_col = sheet_col_contains(headers, "opening", "stock")
    cumulative_req_col = sheet_col(headers, "cummulative_req", "cumulative_req")
    requirement_col, requirement_label = choose_latest_group_date_column(raw, header_row, "part requirement")
    commitment_col, commitment_label = choose_latest_group_date_column(raw, header_row, "supply visiblity", "supply visibility")
    closing_col, closing_label = choose_latest_group_date_column(raw, header_row, "closing stock")
    if requirement_col is None:
        requirement_col = cumulative_req_col

    records = []
    for row_index in range(header_row + 1, len(raw)):
        part_no = stock_part_key(raw_cell(raw, row_index, part_col))
        supplier = normalize_supplier_name(raw_cell(raw, row_index, supplier_col))
        buyer = normalize_buyer_name(raw_cell(raw, row_index, buyer_col))
        part_name = clean_text(raw_cell(raw, row_index, part_name_col)).upper()
        if not part_no or part_no in {"#N/A", "N/A", "NA", "NONE"}:
            continue
        if not any([supplier, buyer, part_name]):
            continue

        opening_stock = pd.to_numeric(raw_cell(raw, row_index, opening_col), errors="coerce")
        requirement = pd.to_numeric(raw_cell(raw, row_index, requirement_col), errors="coerce")
        commitment = pd.to_numeric(raw_cell(raw, row_index, commitment_col), errors="coerce")
        closing_stock = pd.to_numeric(raw_cell(raw, row_index, closing_col), errors="coerce")
        opening_stock = 0 if pd.isna(opening_stock) else float(opening_stock)
        requirement = 0 if pd.isna(requirement) else float(requirement)
        commitment = 0 if pd.isna(commitment) else float(commitment)
        closing_stock = 0 if pd.isna(closing_stock) else float(closing_stock)
        stock_gap = max(requirement - closing_stock, 0)
        if requirement <= 0:
            status = "Requirement missing"
        elif closing_stock <= 0:
            status = "Critical"
        elif closing_stock < requirement:
            status = "Below required"
        else:
            status = "Healthy"

        records.append(
            {
                "Buyer": buyer or "Unmapped buyer",
                "Supplier": supplier or "Unmapped supplier",
                "Part No.": part_no,
                "Part Name": part_name,
                "Opening Stock": opening_stock,
                "MRP / Requirement": requirement,
                "Initial Commitment": commitment,
                "Closing Stock": closing_stock,
                "Stock Gap": stock_gap,
                "Status": status,
            }
        )

    if not records:
        return empty, {"error": "Summary sheet was found, but no part rows were readable."}
    meta = {
        "requirement_label": requirement_label,
        "commitment_label": commitment_label,
        "closing_label": closing_label,
    }
    return pd.DataFrame(records, columns=columns), meta


def build_supplier_buyer_summary(parts: pd.DataFrame) -> pd.DataFrame:
    columns = ["Buyer", "Supplier", "Parts", "Below Required", "Critical", "Opening Stock", "Required Qty", "Closing Stock"]
    if parts.empty:
        return pd.DataFrame(columns=columns)
    grouped = (
        parts.groupby(["Buyer", "Supplier"], as_index=False)
        .agg(
            Parts=("Part No.", "nunique"),
            **{
                "Below Required": ("Status", lambda values: values.isin(["Below required", "Critical"]).sum()),
                "Critical": ("Status", lambda values: values.eq("Critical").sum()),
                "Opening Stock": ("Opening Stock", "sum"),
                "Required Qty": ("MRP / Requirement", "sum"),
                "Closing Stock": ("Closing Stock", "sum"),
            },
        )
        .sort_values(["Below Required", "Critical", "Parts", "Supplier"], ascending=[False, False, False, True])
        .reset_index(drop=True)
    )
    return grouped[columns]


def google_oauth_settings() -> dict[str, str] | None:
    try:
        config = st.secrets["google_oauth"]
        return {
            "client_id": str(config["client_id"]),
            "client_secret": str(config["client_secret"]),
            "redirect_uri": str(config["redirect_uri"]),
        }
    except (FileNotFoundError, KeyError):
        return None


def build_google_oauth_flow(
    settings: dict[str, str],
    state: str | None = None,
) -> Flow:
    client_config = {
        "web": {
            "client_id": settings["client_id"],
            "client_secret": settings["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings["redirect_uri"]],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=[GOOGLE_OAUTH_SCOPE],
        state=state,
    )
    flow.redirect_uri = settings["redirect_uri"]
    return flow


def save_private_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(path)


def save_google_credentials(credentials: Credentials) -> None:
    save_private_text(GOOGLE_TOKEN_PATH, credentials.to_json())


def load_google_credentials() -> Credentials | None:
    if not GOOGLE_TOKEN_PATH.exists():
        return None
    try:
        credentials = Credentials.from_authorized_user_file(
            GOOGLE_TOKEN_PATH,
            scopes=[GOOGLE_OAUTH_SCOPE],
        )
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(GoogleAuthRequest())
            save_google_credentials(credentials)
        return credentials if credentials.valid else None
    except Exception:
        return None


def begin_google_oauth(settings: dict[str, str]) -> str:
    flow = build_google_oauth_flow(settings)
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    save_private_text(
        GOOGLE_STATE_PATH,
        json.dumps(
            {
                "state": state,
                "code_verifier": flow.code_verifier,
            }
        ),
    )
    return authorization_url


def complete_google_oauth(settings: dict[str, str]) -> bool:
    authorization_code = st.query_params.get("code")
    returned_state = st.query_params.get("state")
    if not authorization_code:
        return False
    if not GOOGLE_STATE_PATH.exists():
        st.error("Google sign-in state expired. Start the connection again.")
        st.query_params.clear()
        return False

    try:
        oauth_state = json.loads(GOOGLE_STATE_PATH.read_text(encoding="utf-8"))
        expected_state = oauth_state["state"]
        code_verifier = oauth_state["code_verifier"]
    except (json.JSONDecodeError, KeyError, TypeError):
        st.error("Google sign-in state is invalid. Start the connection again.")
        GOOGLE_STATE_PATH.unlink(missing_ok=True)
        st.query_params.clear()
        return False

    if not returned_state or returned_state != expected_state:
        st.error("Google sign-in could not be verified. Start the connection again.")
        st.query_params.clear()
        return False

    try:
        flow = build_google_oauth_flow(settings, state=expected_state)
        flow.code_verifier = code_verifier
        flow.fetch_token(code=authorization_code)
        save_google_credentials(flow.credentials)
    except Exception as exc:
        st.error(f"Google sign-in failed: {exc}")
        return False
    finally:
        GOOGLE_STATE_PATH.unlink(missing_ok=True)

    st.query_params.clear()
    return True


def unique_headers(values: list[object], width: int) -> list[str]:
    headers: list[str] = []
    counts: dict[str, int] = {}
    padded = values + [""] * (width - len(values))
    for index, value in enumerate(padded):
        base = str(value).strip() or f"Column {index + 1}"
        counts[base] = counts.get(base, 0) + 1
        suffix = f" ({counts[base]})" if counts[base] > 1 else ""
        headers.append(f"{base}{suffix}")
    return headers


def load_google_sheet_oauth(
    url: str,
    credentials: Credentials,
) -> tuple[pd.DataFrame, str]:
    spreadsheet_id, gid = parse_google_sheet_url(url)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleAuthRequest())
        save_google_credentials(credentials)

    headers = {"Authorization": f"Bearer {credentials.token}"}
    metadata_response = requests.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}",
        headers=headers,
        params={"fields": "sheets.properties(sheetId,title,index)"},
        timeout=20,
    )
    metadata_response.raise_for_status()
    sheets = metadata_response.json().get("sheets", [])
    if not sheets:
        raise ValueError("The spreadsheet contains no worksheets.")

    selected_properties = next(
        (
            item["properties"]
            for item in sheets
            if str(item.get("properties", {}).get("sheetId")) == str(gid)
        ),
        None,
    )
    if selected_properties is None:
        raise ValueError(f"Could not find worksheet gid {gid}.")

    selected_sheet = selected_properties["title"]
    escaped_title = selected_sheet.replace("'", "''")
    encoded_range = quote(f"'{escaped_title}'", safe="")
    values_response = requests.get(
        (
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
            f"/values/{encoded_range}"
        ),
        headers=headers,
        params={
            "majorDimension": "ROWS",
            "valueRenderOption": "FORMATTED_VALUE",
        },
        timeout=60,
    )
    values_response.raise_for_status()
    values = values_response.json().get("values", [])
    if not values:
        return pd.DataFrame(), selected_sheet

    width = max(len(row) for row in values)
    columns = unique_headers(values[0], width)
    rows = [row + [""] * (width - len(row)) for row in values[1:]]
    return pd.DataFrame(rows, columns=columns).fillna(""), selected_sheet


def save_source_cache(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    df.to_csv(tmp_path, index=False)
    tmp_path.replace(path)


def load_source_cache(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


def canonical_model(value: object) -> str:
    text = str(value).upper().replace("ROADSTER", "RX").replace("+", "PLUS")
    text = re.sub(r"^(?:GEN[\s-]*3|G3)\s*", "", text)
    text = re.sub(r"[^A-Z0-9]", "", text).replace("KWH", "KW")
    text = text.replace("RXX", "RX")
    aliases = {
        "S1PROPLUS4KW": "S1PROPLUS",
        "S1XPLUS": "S1XPLUS4KW",
        "XPLUS52": "S1XPLUS52KW",
        "RX91KW": "RXPLUS91KW",
    }
    return aliases.get(text, text)


def canonical_color(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def parse_sku_map(df: pd.DataFrame) -> dict[tuple[str, str], str]:
    mapping: dict[tuple[str, str], str] = {}
    for row in df.itertuples(index=False, name=None):
        if len(row) < 5:
            continue
        model, color, fg = row[2], row[3], str(row[4]).strip()
        if fg:
            mapping[(canonical_model(model), canonical_color(color))] = fg
    return mapping


def explode_raw_bom_for_fgs(
    raw_bom: pd.DataFrame,
    fgs: set[str],
) -> pd.DataFrame:
    """Build cumulative component quantities for supplemental header materials."""
    output_columns = [
        "FG",
        "Component",
        "Qty per FG (exploded)",
        "VINs for FG",
        "Units consumed",
    ]
    required = {
        "FG",
        "Explosion level",
        "Component number",
        "Comp Qty CUn",
    }
    if not fgs or not required.issubset(raw_bom.columns):
        return pd.DataFrame(columns=output_columns)
    records: list[dict[str, object]] = []
    filtered = raw_bom[
        raw_bom["FG"].astype(str).str.strip().isin(fgs)
    ]
    for fg, rows in filtered.groupby("FG", sort=False):
        stack: dict[int, float] = {}
        for _, row in rows.iterrows():
            level = str(row["Explosion level"])
            depth = len(level) - len(level.lstrip("."))
            local_qty = pd.to_numeric(
                row["Comp Qty CUn"],
                errors="coerce",
            )
            component = clean_text(row["Component number"])
            if depth <= 0 or pd.isna(local_qty) or not component:
                continue
            cumulative = float(local_qty)
            if depth > 1:
                if depth - 1 not in stack:
                    continue
                cumulative *= stack[depth - 1]
            stack[depth] = cumulative
            stack = {
                current_depth: value
                for current_depth, value in stack.items()
                if current_depth <= depth
            }
            records.append(
                {
                    "FG": clean_text(fg),
                    "Component": component,
                    "Qty per FG (exploded)": cumulative,
                }
            )
    if not records:
        return pd.DataFrame(columns=output_columns)
    exploded = (
        pd.DataFrame(records)
        .groupby(["FG", "Component"], as_index=False)[
            "Qty per FG (exploded)"
        ]
        .sum()
    )
    exploded["VINs for FG"] = 0
    exploded["Units consumed"] = 0
    return exploded[output_columns]


def apply_header_parts_supplement(
    sources: dict[str, pd.DataFrame],
) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
    """Fill verified current-model SKU/BOM gaps from HEADER PARTS.xlsx."""
    diagnostics: dict[str, object] = {
        "supplemental_header_mappings": 0,
        "supplemental_exploded_fgs": 0,
    }
    if not HEADER_PARTS_SUPPLEMENT_PATH.exists():
        return sources, diagnostics
    supplement = pd.read_csv(
        HEADER_PARTS_SUPPLEMENT_PATH,
        dtype=str,
    ).fillna("")
    required = {"Variant", "Model", "Color", "Part No."}
    sku_map = sources.get("sku_map", pd.DataFrame()).copy()
    if not required.issubset(supplement.columns) or sku_map.shape[1] < 5:
        return sources, diagnostics

    supplement_rows = pd.DataFrame(
        {
            sku_map.columns[0]: range(
                len(sku_map) + 1,
                len(sku_map) + len(supplement) + 1,
            ),
            sku_map.columns[1]: supplement["Variant"],
            sku_map.columns[2]: supplement["Model"],
            sku_map.columns[3]: supplement["Color"],
            sku_map.columns[4]: supplement["Part No."],
        }
    )
    existing_mapping = parse_sku_map(sku_map)
    supplement_rows = supplement_rows[
        ~supplement_rows.apply(
            lambda row: (
                canonical_model(row.iloc[2]),
                canonical_color(row.iloc[3]),
            )
            in existing_mapping,
            axis=1,
        )
    ]
    sources = {key: value.copy() for key, value in sources.items()}
    if not supplement_rows.empty:
        sources["sku_map"] = pd.concat(
            [sku_map, supplement_rows],
            ignore_index=True,
        )
    diagnostics["supplemental_header_mappings"] = len(supplement_rows)

    exploded = sources.get("exploded_bom", pd.DataFrame()).copy()
    existing_fgs = set(
        exploded.get("FG", pd.Series(dtype=str))
        .astype(str)
        .str.strip()
    )
    supplemental_fgs = set(supplement["Part No."].str.strip()) - existing_fgs
    supplemental_explosion = explode_raw_bom_for_fgs(
        sources.get("raw_bom", pd.DataFrame()),
        supplemental_fgs,
    )
    if not supplemental_explosion.empty:
        sources["exploded_bom"] = pd.concat(
            [exploded, supplemental_explosion],
            ignore_index=True,
        )
    diagnostics["supplemental_exploded_fgs"] = int(
        supplemental_explosion["FG"].nunique()
        if not supplemental_explosion.empty
        else 0
    )
    return sources, diagnostics


def parse_sheet_date(value: object) -> pd.Timestamp:
    text = clean_text(value)
    if not text:
        return pd.NaT
    current_year = pd.Timestamp.now(tz="Asia/Kolkata").year
    return pd.to_datetime(f"{text}-{current_year}", errors="coerce", dayfirst=True)


def parse_daily_plan_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Read the repeated weekly blocks in Weekly_Plan & Results_Rev.1."""
    columns = ["Plan Date", "Daily Production Plan", "Produced So Far"]
    if df.empty:
        return pd.DataFrame(columns=columns)

    records: list[dict[str, object]] = []
    header_map: dict[str, int] = {}
    for row in df.astype(str).to_numpy().tolist():
        normalized = [normalize_column_name(value) for value in row]
        if "date" in normalized and "plan" in normalized:
            header_map = {
                name: normalized.index(name)
                for name in ["date", "plan", "actual"]
                if name in normalized
            }
            continue
        if not header_map:
            continue
        date_index = header_map["date"]
        if date_index >= len(row):
            continue
        plan_date = parse_sheet_date(row[date_index])
        if pd.isna(plan_date):
            continue
        plan_value = (
            pd.to_numeric(str(row[header_map["plan"]]).replace(",", ""), errors="coerce")
            if header_map["plan"] < len(row)
            else pd.NA
        )
        actual_value = (
            pd.to_numeric(str(row[header_map["actual"]]).replace(",", ""), errors="coerce")
            if "actual" in header_map and header_map["actual"] < len(row)
            else pd.NA
        )
        records.append(
            {
                "Plan Date": plan_date.normalize(),
                "Daily Production Plan": float(plan_value) if pd.notna(plan_value) else 0.0,
                "Produced So Far": float(actual_value) if pd.notna(actual_value) else 0.0,
            }
        )
    if not records:
        return pd.DataFrame(columns=columns)
    return (
        pd.DataFrame(records, columns=columns)
        .drop_duplicates("Plan Date", keep="last")
        .sort_values("Plan Date")
        .reset_index(drop=True)
    )


def parse_production_plan_breakup(df: pd.DataFrame) -> pd.DataFrame:
    """Read model-level plan and production from Production Plan Breakup_Rev.1."""
    columns = [
        "Plan Date",
        "Model",
        "Planned Qty",
        "Visibility Qty",
        "P-VIN Produced Qty",
        "VNA Qty",
        "Free VIN Qty",
        "Produced Qty",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)

    rows = df.astype(str).to_numpy().tolist()
    plan_header = next(
        (
            index
            for index, row in enumerate(rows)
            if row
            and normalize_column_name(row[0]) == "variant"
            and any(normalize_column_name(value) == "plan" for value in row[1:])
        ),
        None,
    )
    if plan_header is None or plan_header + 2 >= len(rows):
        return pd.DataFrame(columns=columns)

    date_row = rows[plan_header + 1]
    label_row = rows[plan_header + 2]
    date_columns: list[tuple[int, pd.Timestamp, int]] = []
    for index, label in enumerate(label_row):
        if normalize_column_name(label) != "daily_plan":
            continue
        plan_date = parse_sheet_date(date_row[index] if index < len(date_row) else "")
        if pd.notna(plan_date):
            next_daily_plan = next(
                (
                    candidate
                    for candidate in range(index + 1, len(label_row))
                    if normalize_column_name(label_row[candidate]) == "daily_plan"
                ),
                len(label_row),
            )
            date_columns.append((index, plan_date.normalize(), next_daily_plan))

    records: list[dict[str, object]] = []
    for row in rows[plan_header + 3 :]:
        model = clean_text(row[0] if row else "")
        if normalize_column_name(model) in {"total_auto", "variant"}:
            if normalize_column_name(model) == "total_auto":
                break
            continue
        if not model:
            continue
        for column_index, plan_date, next_date_column in date_columns:
            values: dict[str, float] = {}
            for value_index in range(column_index, next_date_column):
                label = normalize_column_name(
                    label_row[value_index] if value_index < len(label_row) else ""
                )
                raw_value = row[value_index] if value_index < len(row) else ""
                parsed_value = pd.to_numeric(
                    str(raw_value).replace(",", ""),
                    errors="coerce",
                )
                if label and pd.notna(parsed_value):
                    values[label] = float(parsed_value)
            planned = values.get("daily_plan", 0.0)
            visibility = values.get("visibility", 0.0)
            pvin_produced = values.get("pvin", pd.NA)
            vna_qty = values.get("vna", pd.NA)
            free_vin_qty = values.get(
                "free_vins",
                values.get("free_vin", pd.NA),
            )
            component_total = sum(
                values.get(label, 0.0)
                for label in [
                    "a_shift",
                    "b_shift",
                    "c_shift",
                    "pvin",
                    "vna",
                    "free_vins",
                    "free_vin",
                ]
            )
            produced = visibility if "visibility" in values else component_total
            if planned > 0 or produced > 0:
                records.append(
                    {
                        "Plan Date": plan_date,
                        "Model": model,
                        "Planned Qty": planned,
                        "Visibility Qty": visibility,
                        "P-VIN Produced Qty": pvin_produced,
                        "VNA Qty": vna_qty,
                        "Free VIN Qty": free_vin_qty,
                        "Produced Qty": produced,
                    }
                )
    parsed = pd.DataFrame(records, columns=columns)
    return apply_variant_operating_overrides(parsed)


def parse_vin_detail_plan_actual(
    df: pd.DataFrame,
    sku_map: dict[tuple[str, str], str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [
        "Plan Date",
        "Model",
        "Color",
        "FG",
        "Detailed Plan Qty",
        "Produced Qty",
    ]
    unmatched_columns = [
        "Plan Date",
        "Model",
        "Color",
        "Detailed Plan Qty",
        "Produced Qty",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns), pd.DataFrame(columns=unmatched_columns)

    rows = df.astype(str).to_numpy().tolist()
    header_index = next(
        (index for index, row in enumerate(rows) if row and row[0].strip() == "Model"),
        None,
    )
    if header_index is None or header_index + 3 >= len(rows):
        return pd.DataFrame(columns=columns), pd.DataFrame(columns=unmatched_columns)

    date_header = rows[header_index]
    date_columns: list[tuple[list[int], list[int], pd.Timestamp]] = []
    for index, value in enumerate(date_header):
        if not re.fullmatch(r"\d{1,2}-[A-Za-z]{3}", value.strip()):
            continue
        plan_date = parse_sheet_date(value)
        if pd.notna(plan_date) and index + 7 < len(date_header):
            date_columns.append(
                (
                    [index, index + 2, index + 4],
                    [index + 1, index + 3, index + 5],
                    plan_date.normalize(),
                )
            )

    mapped: list[dict[str, object]] = []
    unmatched: list[dict[str, object]] = []
    current_model = ""
    for row in rows[header_index + 3 :]:
        if len(row) < 2:
            continue
        if row[0].strip():
            current_model = row[0].strip()
        color = row[1].strip()
        if not current_model or not color:
            continue
        fg = sku_map.get((canonical_model(current_model), canonical_color(color)))
        for plan_columns, actual_columns, plan_date in date_columns:
            plan_qty = sum(
                float(value)
                for value in (
                    pd.to_numeric(
                        str(row[column]).replace(",", ""),
                        errors="coerce",
                    )
                    for column in plan_columns
                )
                if pd.notna(value)
            )
            actual_qty = sum(
                float(value)
                for value in (
                    pd.to_numeric(
                        str(row[column]).replace(",", ""),
                        errors="coerce",
                    )
                    for column in actual_columns
                )
                if pd.notna(value)
            )
            if plan_qty <= 0 and actual_qty <= 0:
                continue
            record = {
                "Plan Date": plan_date,
                "Model": current_model,
                "Color": color,
                "Detailed Plan Qty": plan_qty,
                "Produced Qty": actual_qty,
            }
            if fg:
                mapped.append({**record, "FG": fg})
            else:
                unmatched.append(record)
    return (
        pd.DataFrame(mapped, columns=columns),
        pd.DataFrame(unmatched, columns=unmatched_columns),
    )


def parse_vin_detail_production(
    df: pd.DataFrame,
    sku_map: dict[tuple[str, str], str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = ["Usage Date", "FG", "Produced Qty", "Production Source"]
    unmatched_columns = ["Usage Date", "Model", "Color", "Produced Qty"]
    detail, unmatched = parse_vin_detail_plan_actual(df, sku_map)
    production = detail[["Plan Date", "FG", "Produced Qty"]].copy()
    production = production[production["Produced Qty"] > 0]
    production = production.rename(columns={"Plan Date": "Usage Date"})
    production["Production Source"] = "VIN Details Daily"
    if not production.empty:
        production = (
            production.groupby(
                ["Usage Date", "FG", "Production Source"],
                as_index=False,
            )["Produced Qty"]
            .sum()
        )
    unmatched = unmatched[unmatched["Produced Qty"] > 0].rename(
        columns={"Plan Date": "Usage Date"}
    )
    return production, unmatched[unmatched_columns]


def build_daily_production(
    vin_details: pd.DataFrame,
    sku_mapping: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    production, unmatched = parse_vin_detail_production(
        vin_details,
        parse_sku_map(sku_mapping),
    )
    if production.empty:
        return production, unmatched
    production = (
        production.groupby(["Usage Date", "FG"], as_index=False)
        .agg(
            {
                "Produced Qty": "sum",
                "Production Source": lambda values: ", ".join(
                    sorted(set(map(str, values)))
                ),
            }
        )
        .sort_values(["Usage Date", "FG"], ascending=[False, True])
    )
    return production, unmatched


def joined_text(values: pd.Series) -> str:
    cleaned = {
        str(value).strip()
        for value in values
        if str(value).strip() and str(value).strip().lower() != "nan"
    }
    return ", ".join(sorted(cleaned))


def compute_production_part_usage(
    production: pd.DataFrame,
    exploded_bom: pd.DataFrame,
    raw_bom: pd.DataFrame,
    part_types: pd.DataFrame,
    suppliers: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    output_columns = [
        "Usage Date",
        "Daily Total Production",
        "Part No.",
        "Part Name",
        "Material Type",
        "Supplier",
        "Production Used Qty",
    ]
    required_bom = {"FG", "Component", "Qty per FG (exploded)"}
    if production.empty or not required_bom.issubset(exploded_bom.columns):
        return pd.DataFrame(columns=output_columns), []

    bom = exploded_bom[
        ["FG", "Component", "Qty per FG (exploded)"]
    ].copy()
    bom["FG"] = bom["FG"].astype(str).str.strip()
    bom["Component"] = bom["Component"].astype(str).str.strip()
    bom["Qty per FG"] = pd.to_numeric(
        bom["Qty per FG (exploded)"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
    bom = bom[
        bom["FG"].ne("")
        & bom["Component"].ne("")
        & bom["Qty per FG"].notna()
    ].drop_duplicates(["FG", "Component"])

    missing_fgs = sorted(set(production["FG"]) - set(bom["FG"]))
    detail = production.merge(
        bom[["FG", "Component", "Qty per FG"]],
        on="FG",
        how="inner",
    )
    detail["Production Used Qty"] = (
        detail["Produced Qty"] * detail["Qty per FG"]
    )
    usage = (
        detail.groupby(["Usage Date", "Component"], as_index=False)[
            "Production Used Qty"
        ]
        .sum()
        .rename(columns={"Component": "Part No."})
    )
    daily_totals = (
        production.groupby("Usage Date", as_index=False)["Produced Qty"]
        .sum()
        .rename(columns={"Produced Qty": "Daily Total Production"})
    )
    usage = usage.merge(daily_totals, on="Usage Date", how="left")

    if {"Component number", "Material type"}.issubset(part_types.columns):
        type_map = part_types[["Component number", "Material type"]].copy()
        type_map.columns = ["Part No.", "Material Type"]
        type_map["Part No."] = type_map["Part No."].astype(str).str.strip()
        usage = usage.merge(
            type_map.drop_duplicates("Part No."),
            on="Part No.",
            how="left",
        )
    else:
        usage["Material Type"] = ""

    raw_columns = {"Component number", "Object description", "Material type"}
    if raw_columns.issubset(raw_bom.columns):
        raw_map = raw_bom[
            ["Component number", "Object description", "Material type"]
        ].copy()
        raw_map.columns = ["Part No.", "BOM Part Name", "BOM Material Type"]
        raw_map["Part No."] = raw_map["Part No."].astype(str).str.strip()
        raw_map = raw_map.groupby("Part No.", as_index=False).agg(
            {
                "BOM Part Name": joined_text,
                "BOM Material Type": joined_text,
            }
        )
        usage = usage.merge(raw_map, on="Part No.", how="left")
    else:
        usage["BOM Part Name"] = ""
        usage["BOM Material Type"] = ""

    supplier_columns = {"Material", "Material Description", "Supplier Name"}
    if supplier_columns.issubset(suppliers.columns):
        supplier_map = suppliers[
            ["Material", "Material Description", "Supplier Name"]
        ].copy()
        supplier_map.columns = ["Part No.", "Supplier Part Name", "Supplier"]
        supplier_map["Part No."] = supplier_map["Part No."].astype(str).str.strip()
        supplier_map = supplier_map.groupby("Part No.", as_index=False).agg(
            {"Supplier Part Name": joined_text, "Supplier": joined_text}
        )
        usage = usage.merge(supplier_map, on="Part No.", how="left")
    else:
        usage["Supplier Part Name"] = ""
        usage["Supplier"] = ""

    for column in [
        "Supplier Part Name",
        "BOM Part Name",
        "Material Type",
        "BOM Material Type",
        "Supplier",
    ]:
        usage[column] = usage[column].fillna("")
    usage["Part Name"] = usage["Supplier Part Name"].where(
        usage["Supplier Part Name"].ne(""),
        usage["BOM Part Name"],
    )
    usage["Material Type"] = usage["Material Type"].where(
        usage["Material Type"].ne(""),
        usage["BOM Material Type"],
    )
    return (
        usage[output_columns].sort_values(
            ["Usage Date", "Part No."],
            ascending=[False, True],
        ),
        missing_fgs,
    )


def combine_manual_outwarding(
    production_usage: pd.DataFrame,
    manual_outwarding: pd.DataFrame,
) -> pd.DataFrame:
    manual_columns = [
        "Usage Date",
        "Part No.",
        "Manual Part Name",
        "Manual Supplier",
        "Servicing Used Qty",
    ]
    if manual_outwarding.empty:
        manual = pd.DataFrame(columns=manual_columns)
    else:
        manual = manual_outwarding.copy()
        manual["Usage Date"] = pd.to_datetime(
            manual["Usage Date"],
            errors="coerce",
            format="mixed",
        ).dt.normalize()
        manual["Part No."] = manual["Part No."].astype(str).str.strip()
        manual["Manual Part Name"] = manual["Part Name"].astype(str).str.strip()
        manual["Manual Supplier"] = manual["Supplier"].astype(str).str.strip()
        manual["Servicing Used Qty"] = numeric(manual["Used Qty"])
        manual = (
            manual[manual["Usage Date"].notna() & manual["Part No."].ne("")]
            .groupby(["Usage Date", "Part No."], as_index=False)
            .agg(
                {
                    "Manual Part Name": joined_text,
                    "Manual Supplier": joined_text,
                    "Servicing Used Qty": "sum",
                }
            )
        )

    combined = production_usage.merge(
        manual,
        on=["Usage Date", "Part No."],
        how="outer",
    )
    for column in [
        "Part Name",
        "Material Type",
        "Supplier",
        "Manual Part Name",
        "Manual Supplier",
    ]:
        if column not in combined:
            combined[column] = ""
        combined[column] = combined[column].fillna("")
    combined["Part Name"] = combined["Part Name"].where(
        combined["Part Name"].ne(""),
        combined["Manual Part Name"],
    )
    combined["Supplier"] = combined["Supplier"].where(
        combined["Supplier"].ne(""),
        combined["Manual Supplier"],
    )
    combined["Part Name"] = combined["Part Name"].replace("", "Not mapped")
    combined["Supplier"] = combined["Supplier"].replace("", "Not mapped")
    for column in [
        "Daily Total Production",
        "Production Used Qty",
        "Servicing Used Qty",
    ]:
        combined[column] = numeric(combined[column])
    combined["Total Outwarding Qty"] = (
        combined["Production Used Qty"] + combined["Servicing Used Qty"]
    )
    ordered = [
        "Usage Date",
        "Daily Total Production",
        "Part No.",
        "Part Name",
        "Material Type",
        "Supplier",
        "Production Used Qty",
        "Servicing Used Qty",
        "Total Outwarding Qty",
    ]
    return combined[ordered].sort_values(
        ["Usage Date", "Part No."],
        ascending=[False, True],
    )


def allocate_integer_quantities(weights: pd.Series, total: float) -> pd.Series:
    """Allocate a whole-vehicle total without creating fractional vehicles."""
    target = max(int(round(float(total))), 0)
    clean_weights = pd.to_numeric(weights, errors="coerce").fillna(0).clip(lower=0)
    if target == 0 or clean_weights.sum() <= 0:
        return pd.Series(0, index=weights.index, dtype=int)
    raw = clean_weights / clean_weights.sum() * target
    allocated = raw.apply(lambda value: int(value // 1))
    remainder = target - int(allocated.sum())
    if remainder:
        order = (raw - allocated).sort_values(ascending=False).index[:remainder]
        allocated.loc[order] += 1
    return allocated.astype(int)


def build_planned_and_actual_production(
    daily_summary: pd.DataFrame,
    plan_breakup: pd.DataFrame,
    vin_details: pd.DataFrame,
    sku_mapping: pd.DataFrame,
) -> tuple[pd.Timestamp | None, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Build FG-level plan and actuals from the variant-wise breakup sheet."""
    diagnostics: dict[str, object] = {}
    summary = parse_daily_plan_summary(daily_summary)
    if summary.empty:
        return None, pd.DataFrame(), pd.DataFrame(), {"error": "Daily plan summary is empty."}

    today = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
    eligible = summary[
        summary["Plan Date"].le(today) & summary["Daily Production Plan"].gt(0)
    ]
    if eligible.empty:
        eligible = summary[summary["Daily Production Plan"].gt(0)]
    if eligible.empty:
        return None, pd.DataFrame(), pd.DataFrame(), {"error": "No positive daily plan was found."}
    selected = eligible.sort_values("Plan Date").iloc[-1]
    plan_date = pd.Timestamp(selected["Plan Date"]).normalize()
    daily_target = float(selected["Daily Production Plan"])
    produced_target = float(selected["Produced So Far"])

    detail, unmatched = parse_vin_detail_plan_actual(
        vin_details,
        parse_sku_map(sku_mapping),
    )
    model_plan = parse_production_plan_breakup(plan_breakup)
    model_plan = model_plan[model_plan["Plan Date"].eq(plan_date)].copy()
    if model_plan.empty:
        return plan_date, pd.DataFrame(), pd.DataFrame(), {
            "error": f"No variant plan was found for {plan_date:%d %b %Y}.",
            "daily_target": daily_target,
            "produced_target": produced_target,
        }
    breakup_daily_target = float(numeric(model_plan["Planned Qty"]).sum())
    breakup_produced_target = float(numeric(model_plan["Produced Qty"]).sum())
    if breakup_daily_target > 0:
        daily_target = breakup_daily_target
    produced_target = breakup_produced_target
    model_plan["Planned Qty"] = allocate_integer_quantities(
        model_plan["Planned Qty"],
        daily_target,
    )
    model_plan["Produced Qty"] = allocate_integer_quantities(
        model_plan["Produced Qty"],
        produced_target,
    )

    plan_rows: list[pd.DataFrame] = []
    actual_rows: list[pd.DataFrame] = []
    fallback_dates: list[pd.Timestamp] = []
    missing_models: list[str] = []
    for _, model_row in model_plan.iterrows():
        model = str(model_row["Model"])
        model_key = canonical_model(model)
        planned_quantity = float(model_row["Planned Qty"])
        produced_quantity = float(model_row["Produced Qty"])
        candidates = detail[
            detail["Model"].map(canonical_model).eq(model_key)
            & detail["Plan Date"].eq(plan_date)
            & detail["Detailed Plan Qty"].gt(0)
        ].copy()
        if candidates.empty:
            historical = detail[
                detail["Model"].map(canonical_model).eq(model_key)
                & detail["Plan Date"].lt(plan_date)
                & detail["Detailed Plan Qty"].gt(0)
            ].copy()
            if not historical.empty:
                fallback_date = historical["Plan Date"].max()
                fallback_dates.append(fallback_date)
                candidates = historical[historical["Plan Date"].eq(fallback_date)].copy()
        if candidates.empty:
            missing_models.append(model)
            continue
        candidates = (
            candidates.groupby("FG", as_index=False)["Detailed Plan Qty"].sum()
        )
        candidates["Produced Qty"] = allocate_integer_quantities(
            candidates["Detailed Plan Qty"],
            planned_quantity,
        )
        if planned_quantity > 0:
            plan_rows.append(candidates[["FG", "Produced Qty"]])
        if produced_quantity > 0:
            produced_candidates = candidates[["FG", "Detailed Plan Qty"]].copy()
            produced_candidates["Produced Qty"] = allocate_integer_quantities(
                produced_candidates["Detailed Plan Qty"],
                produced_quantity,
            )
            actual_rows.append(produced_candidates[["FG", "Produced Qty"]])

    planned = (
        pd.concat(plan_rows, ignore_index=True)
        if plan_rows
        else pd.DataFrame(columns=["FG", "Produced Qty"])
    )
    if not planned.empty:
        planned = planned.groupby("FG", as_index=False)["Produced Qty"].sum()
        planned["Usage Date"] = plan_date
        planned["Production Source"] = "Daily plan × variant mix"

    actual = (
        pd.concat(actual_rows, ignore_index=True)
        if actual_rows
        else pd.DataFrame(columns=["FG", "Produced Qty"])
    )
    if not actual.empty:
        actual = actual.groupby("FG", as_index=False)["Produced Qty"].sum()
        actual = actual[actual["Produced Qty"].gt(0)]
        actual["Usage Date"] = plan_date
        actual["Production Source"] = "Production Plan Breakup visibility / shifts"

    diagnostics.update(
        {
            "daily_target": daily_target,
            "produced_target": produced_target,
            "fallback_mix_date": max(fallback_dates) if fallback_dates else None,
            "missing_models": sorted(set(missing_models)),
            "unmatched_variants": len(unmatched),
        }
    )
    ordered = ["Usage Date", "FG", "Produced Qty", "Production Source"]
    return (
        plan_date,
        planned[ordered] if not planned.empty else pd.DataFrame(columns=ordered),
        actual[ordered] if not actual.empty else pd.DataFrame(columns=ordered),
        diagnostics,
    )


def parse_scm_system_stock(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, str]:
    """Read part-level System Opening Stock from SCM Plan Working Revision 1."""
    columns = ["Part Key", "SCM System Stock", "SCM Stock Match"]
    if df.empty:
        return pd.DataFrame(columns=columns), ""
    rows = df.astype(str).to_numpy().tolist()
    header_index = None
    part_index = None
    stock_index = None
    stock_label = ""
    for row_index, row in enumerate(rows):
        normalized = [normalize_column_name(value) for value in row]
        component_indexes = [
            index
            for index, value in enumerate(normalized)
            if value in {"component", "part_no", "part_number"}
        ]
        stock_indexes = [
            index
            for index, value in enumerate(normalized)
            if value.startswith("system_opening_stock")
        ]
        if component_indexes and stock_indexes:
            header_index = row_index
            part_index = component_indexes[0]
            stock_index = stock_indexes[0]
            stock_label = clean_text(row[stock_index])
            break
    if header_index is None or part_index is None or stock_index is None:
        return pd.DataFrame(columns=columns), ""

    records: list[dict[str, object]] = []
    for row in rows[header_index + 1 :]:
        part_no = clean_text(row[part_index] if part_index < len(row) else "")
        stock_value = row[stock_index] if stock_index < len(row) else ""
        stock = pd.to_numeric(
            str(stock_value).replace(",", ""),
            errors="coerce",
        )
        if part_no:
            raw_stock = clean_text(stock_value)
            if pd.notna(stock):
                match_status = "Exact SCM match"
                parsed_stock: object = float(stock)
            elif not raw_stock:
                match_status = "System Opening Stock blank"
                parsed_stock = pd.NA
            else:
                match_status = f"Invalid System Opening Stock: {raw_stock}"
                parsed_stock = pd.NA
            records.append(
                {
                    "Part Key": stock_part_key(part_no),
                    "SCM System Stock": parsed_stock,
                    "SCM Stock Match": match_status,
                }
            )
    if not records:
        return pd.DataFrame(columns=columns), stock_label
    return (
        pd.DataFrame(records, columns=columns)
        .drop_duplicates("Part Key", keep="last"),
        stock_label,
    )


def load_pvin_inputs() -> pd.DataFrame:
    if not PVIN_INPUTS_PATH.exists():
        return pd.DataFrame(columns=PVIN_INPUT_COLUMNS)
    frame = pd.read_csv(PVIN_INPUTS_PATH, dtype=str).fillna("")
    for column in PVIN_INPUT_COLUMNS:
        if column not in frame:
            frame[column] = ""
    for column in ["Generated P-VIN", "Produced P-VIN"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)
    return frame[PVIN_INPUT_COLUMNS]


def load_variant_operating_overrides() -> pd.DataFrame:
    if not VARIANT_OPERATING_OVERRIDES_PATH.exists():
        return pd.DataFrame(columns=VARIANT_OPERATING_OVERRIDE_COLUMNS)
    frame = pd.read_csv(
        VARIANT_OPERATING_OVERRIDES_PATH,
        dtype=str,
    ).fillna("")
    for column in VARIANT_OPERATING_OVERRIDE_COLUMNS:
        if column not in frame:
            frame[column] = ""
    frame["Plan Date"] = pd.to_datetime(
        frame["Plan Date"],
        errors="coerce",
    ).dt.normalize()
    frame["Model"] = frame["Model"].map(clean_text)
    for column in VARIANT_OPERATING_OVERRIDE_COLUMNS[2:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame[VARIANT_OPERATING_OVERRIDE_COLUMNS]


def save_variant_operating_overrides(frame: pd.DataFrame) -> None:
    cleaned = frame.copy()
    for column in VARIANT_OPERATING_OVERRIDE_COLUMNS:
        if column not in cleaned:
            cleaned[column] = pd.NA
    cleaned["Plan Date"] = pd.to_datetime(
        cleaned["Plan Date"],
        errors="coerce",
    ).dt.strftime("%Y-%m-%d")
    cleaned["Model"] = cleaned["Model"].map(clean_text)
    for column in VARIANT_OPERATING_OVERRIDE_COLUMNS[2:]:
        cleaned[column] = (
            pd.to_numeric(cleaned[column], errors="coerce")
            .clip(lower=0)
            .round()
        )
    cleaned = cleaned[
        cleaned["Plan Date"].ne("") & cleaned["Model"].ne("")
    ][VARIANT_OPERATING_OVERRIDE_COLUMNS].drop_duplicates(
        ["Plan Date", "Model"],
        keep="last",
    )
    VARIANT_OPERATING_OVERRIDES_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary = VARIANT_OPERATING_OVERRIDES_PATH.with_suffix(".tmp")
    cleaned.to_csv(temporary, index=False)
    temporary.replace(VARIANT_OPERATING_OVERRIDES_PATH)


def apply_variant_operating_overrides(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    overrides = load_variant_operating_overrides()
    if frame.empty or overrides.empty:
        return frame
    result = frame.copy()
    override_lookup = {
        (
            pd.Timestamp(row["Plan Date"]).normalize(),
            canonical_model(row["Model"]),
        ): row
        for _, row in overrides.dropna(subset=["Plan Date"]).iterrows()
    }
    value_columns = VARIANT_OPERATING_OVERRIDE_COLUMNS[2:]
    for index, row in result.iterrows():
        key = (
            pd.Timestamp(row["Plan Date"]).normalize(),
            canonical_model(row["Model"]),
        )
        override = override_lookup.get(key)
        if override is None:
            continue
        for column in value_columns:
            if pd.notna(override[column]):
                result.at[index, column] = override[column]
    return result


def save_pvin_inputs(frame: pd.DataFrame) -> None:
    cleaned = frame.copy().fillna("")
    for column in PVIN_INPUT_COLUMNS:
        if column not in cleaned:
            cleaned[column] = ""
    cleaned["Plan Date"] = pd.to_datetime(
        cleaned["Plan Date"],
        errors="coerce",
    ).dt.strftime("%Y-%m-%d")
    cleaned["Variant"] = cleaned["Variant"].map(clean_text)
    for column in ["Generated P-VIN", "Produced P-VIN"]:
        cleaned[column] = (
            pd.to_numeric(cleaned[column], errors="coerce")
            .fillna(0)
            .clip(lower=0)
            .round()
            .astype(int)
        )
    cleaned = cleaned[
        cleaned["Plan Date"].ne("") & cleaned["Variant"].ne("")
    ][PVIN_INPUT_COLUMNS].drop_duplicates(
        ["Plan Date", "Variant"],
        keep="last",
    )
    PVIN_INPUTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PVIN_INPUTS_PATH.with_suffix(".tmp")
    cleaned.to_csv(temporary, index=False)
    temporary.replace(PVIN_INPUTS_PATH)


def pvin_input_template(
    sources: dict[str, pd.DataFrame],
    plan_date: pd.Timestamp,
) -> pd.DataFrame:
    plan = parse_production_plan_breakup(
        sources.get("production_plan_breakup", pd.DataFrame())
    )
    plan_for_date = plan.loc[plan["Plan Date"].eq(plan_date)].copy()
    variants = sorted(
        plan_for_date["Model"]
        .dropna()
        .map(clean_text)
        .loc[lambda values: values.ne("")]
        .unique()
        .tolist()
    )
    saved = load_pvin_inputs()
    saved_for_date = saved[
        saved["Plan Date"].eq(plan_date.strftime("%Y-%m-%d"))
    ].copy()
    saved_variants = saved_for_date["Variant"].map(clean_text).tolist()
    variants = sorted(set(variants) | set(saved_variants))
    template = pd.DataFrame(
        {
            "Plan Date": plan_date.strftime("%Y-%m-%d"),
            "Variant": variants,
            "Generated P-VIN": 0,
            "Produced P-VIN": pd.NA,
        }
    )
    if template.empty:
        return pd.DataFrame(columns=PVIN_INPUT_COLUMNS)
    produced_lookup = (
        plan_for_date.assign(
            Variant=plan_for_date["Model"].map(clean_text),
        )
        .groupby("Variant")["P-VIN Produced Qty"]
        .sum(min_count=1)
    )
    template["Produced P-VIN"] = (
        template["Variant"].map(produced_lookup)
    )
    if not saved_for_date.empty:
        saved_lookup = saved_for_date.set_index("Variant")
        template["Generated P-VIN"] = (
            template["Variant"].map(saved_lookup["Generated P-VIN"]).fillna(0)
        )
    return template[PVIN_INPUT_COLUMNS]


def allocate_variant_pvin_to_fgs(
    inputs: pd.DataFrame,
    plan_date: pd.Timestamp,
    vin_details: pd.DataFrame,
    sku_mapping: pd.DataFrame,
    quantity_column: str,
) -> tuple[pd.DataFrame, list[str]]:
    output_columns = [
        "Usage Date",
        "FG",
        "Produced Qty",
        "Production Source",
    ]
    if inputs.empty:
        return pd.DataFrame(columns=output_columns), []
    detail, _ = parse_vin_detail_plan_actual(
        vin_details,
        parse_sku_map(sku_mapping),
    )
    rows: list[pd.DataFrame] = []
    missing_variants: list[str] = []
    for _, record in inputs.iterrows():
        variant = clean_text(record.get("Variant", ""))
        quantity = pd.to_numeric(
            record.get(quantity_column, 0),
            errors="coerce",
        )
        if not variant or pd.isna(quantity) or float(quantity) <= 0:
            continue
        variant_rows = detail[
            detail["Model"].map(canonical_model).eq(canonical_model(variant))
        ].copy()
        current_mix = variant_rows[
            variant_rows["Plan Date"].eq(plan_date)
            & variant_rows["Detailed Plan Qty"].gt(0)
        ]
        if current_mix.empty:
            historical = variant_rows[
                variant_rows["Plan Date"].lt(plan_date)
                & variant_rows["Detailed Plan Qty"].gt(0)
            ]
            if not historical.empty:
                fallback_date = historical["Plan Date"].max()
                current_mix = historical[
                    historical["Plan Date"].eq(fallback_date)
                ]
        if current_mix.empty:
            missing_variants.append(variant)
            continue
        fg_mix = current_mix.groupby("FG", as_index=False)[
            "Detailed Plan Qty"
        ].sum()
        fg_mix["Produced Qty"] = allocate_integer_quantities(
            fg_mix["Detailed Plan Qty"],
            float(quantity),
        )
        fg_mix["Usage Date"] = plan_date
        fg_mix["Production Source"] = quantity_column
        rows.append(fg_mix[output_columns])
    if not rows:
        return pd.DataFrame(columns=output_columns), sorted(set(missing_variants))
    production = pd.concat(rows, ignore_index=True)
    production = production.groupby(
        ["Usage Date", "FG", "Production Source"],
        as_index=False,
    )["Produced Qty"].sum()
    return production[output_columns], sorted(set(missing_variants))


def build_pvin_part_consumption(
    sources: dict[str, pd.DataFrame],
    plan_date: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, object]]:
    output_columns = [
        "Part No.",
        "Generated Consumption",
        "Produced Consumption",
    ]
    current_inputs = pvin_input_template(sources, plan_date)
    produced_source_available = bool(
        not current_inputs.empty
        and pd.to_numeric(
            current_inputs["Produced P-VIN"],
            errors="coerce",
        ).notna().any()
    )
    diagnostics: dict[str, object] = {
        "pvin_inputs_active": bool(
            not current_inputs.empty
            and (
                numeric(current_inputs["Generated P-VIN"]).sum() > 0
                or numeric(current_inputs["Produced P-VIN"]).sum() > 0
            )
        ),
        "generated_pvin_total": float(
            numeric(current_inputs.get("Generated P-VIN", pd.Series(dtype=float))).sum()
        ),
        "produced_pvin_total": float(
            numeric(current_inputs.get("Produced P-VIN", pd.Series(dtype=float))).sum()
        ),
        "produced_pvin_source_available": produced_source_available,
    }
    if current_inputs.empty:
        return pd.DataFrame(columns=output_columns), diagnostics

    generated_fgs, generated_missing = allocate_variant_pvin_to_fgs(
        current_inputs,
        plan_date,
        sources.get("vin_details", pd.DataFrame()),
        sources.get("sku_map", pd.DataFrame()),
        "Generated P-VIN",
    )
    produced_fgs, produced_missing = allocate_variant_pvin_to_fgs(
        current_inputs,
        plan_date,
        sources.get("vin_details", pd.DataFrame()),
        sources.get("sku_map", pd.DataFrame()),
        "Produced P-VIN",
    )
    common_args = (
        sources.get("exploded_bom", pd.DataFrame()),
        sources.get("raw_bom", pd.DataFrame()),
        sources.get("part_types", pd.DataFrame()),
        sources.get("suppliers", pd.DataFrame()),
    )
    generated_usage, generated_missing_fgs = compute_production_part_usage(
        generated_fgs,
        *common_args,
    )
    produced_usage, produced_missing_fgs = compute_production_part_usage(
        produced_fgs,
        *common_args,
    )
    generated = (
        generated_usage[["Part No.", "Production Used Qty"]].rename(
            columns={"Production Used Qty": "Generated Consumption"}
        )
        if not generated_usage.empty
        else pd.DataFrame(columns=["Part No.", "Generated Consumption"])
    )
    produced = (
        produced_usage[["Part No.", "Production Used Qty"]].rename(
            columns={"Production Used Qty": "Produced Consumption"}
        )
        if not produced_usage.empty
        else pd.DataFrame(columns=["Part No.", "Produced Consumption"])
    )
    consumption = generated.merge(produced, on="Part No.", how="outer").fillna(0)
    diagnostics.update(
        {
            "pvin_missing_variants": sorted(
                set(generated_missing) | set(produced_missing)
            ),
            "pvin_missing_bom_fgs": sorted(
                set(generated_missing_fgs) | set(produced_missing_fgs)
            ),
        }
    )
    return consumption[output_columns], diagnostics


def build_daily_part_movements(
    plan_date: pd.Timestamp,
    produced_consumption: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Aggregate HS01 inwarding and production/manual outwarding for one day."""
    columns = [
        "Part Key",
        "Parts Inwarded",
        "Production Outwarded",
        "Other Outwarded",
        "Parts Outwarded",
    ]
    diagnostics: dict[str, object] = {}

    inwarded = pd.DataFrame(columns=["Part Key", "Parts Inwarded"])
    if INWARDING_SNAPSHOT_PATH.exists():
        inwarding = pd.read_csv(
            INWARDING_SNAPSHOT_PATH,
            dtype=str,
        ).fillna("")
        if {"Date", "Part Number", "Invoice Qty"}.issubset(inwarding.columns):
            inwarding_dates = pd.to_datetime(
                inwarding["Date"],
                errors="coerce",
                dayfirst=True,
            ).dt.normalize()
            inwarding = inwarding[inwarding_dates.eq(plan_date)].copy()
            inwarding["Part Key"] = inwarding["Part Number"].map(stock_part_key)
            inwarding["Parts Inwarded"] = numeric(inwarding["Invoice Qty"])
            inwarding = inwarding[
                inwarding["Part Key"].ne("")
                & inwarding["Parts Inwarded"].gt(0)
            ]
            inwarded = inwarding.groupby(
                "Part Key",
                as_index=False,
            )["Parts Inwarded"].sum()
            diagnostics["inwarding_rows_used"] = len(inwarding)

    production = produced_consumption.copy()
    if production.empty:
        production_outwarded = pd.DataFrame(
            columns=["Part Key", "Production Outwarded"]
        )
    else:
        production["Part Key"] = production["Part No."].map(stock_part_key)
        production["Production Outwarded"] = numeric(
            production["Produced Consumption"]
        )
        production_outwarded = production.groupby(
            "Part Key",
            as_index=False,
        )["Production Outwarded"].sum()

    manual = load_table("outwarding_parts")
    other_outwarded = pd.DataFrame(columns=["Part Key", "Other Outwarded"])
    if not manual.empty:
        manual_dates = pd.to_datetime(
            manual["Usage Date"],
            errors="coerce",
            dayfirst=True,
        ).dt.normalize()
        manual = manual[manual_dates.eq(plan_date)].copy()
        manual["Part Key"] = manual["Part No."].map(stock_part_key)
        manual["Other Outwarded"] = numeric(manual["Used Qty"])
        manual = manual[
            manual["Part Key"].ne("") & manual["Other Outwarded"].gt(0)
        ]
        other_outwarded = manual.groupby(
            "Part Key",
            as_index=False,
        )["Other Outwarded"].sum()
        diagnostics["manual_outwarding_rows_used"] = len(manual)

    movements = inwarded.merge(
        production_outwarded,
        on="Part Key",
        how="outer",
    ).merge(
        other_outwarded,
        on="Part Key",
        how="outer",
    )
    if movements.empty:
        return pd.DataFrame(columns=columns), diagnostics
    for column in [
        "Parts Inwarded",
        "Production Outwarded",
        "Other Outwarded",
    ]:
        movements[column] = numeric(movements[column])
    movements["Parts Outwarded"] = (
        movements["Production Outwarded"] + movements["Other Outwarded"]
    )
    diagnostics["parts_inwarded_total"] = float(
        movements["Parts Inwarded"].sum()
    )
    diagnostics["parts_outwarded_total"] = float(
        movements["Parts Outwarded"].sum()
    )
    return movements[columns], diagnostics


def build_part_inventory_plan(
    saved_inventory: pd.DataFrame,
    sources: dict[str, pd.DataFrame],
    delta_threshold: float = 10.0,
) -> tuple[pd.DataFrame, dict[str, object]]:
    plan_date, planned, actual, diagnostics = build_planned_and_actual_production(
        sources.get("daily_plan_summary", pd.DataFrame()),
        sources.get("production_plan_breakup", pd.DataFrame()),
        sources.get("vin_details", pd.DataFrame()),
        sources.get("sku_map", pd.DataFrame()),
    )
    if plan_date is None or planned.empty:
        return build_inventory_status(saved_inventory), diagnostics

    common_args = (
        sources.get("exploded_bom", pd.DataFrame()),
        sources.get("raw_bom", pd.DataFrame()),
        sources.get("part_types", pd.DataFrame()),
        sources.get("suppliers", pd.DataFrame()),
    )
    planned_usage, missing_plan_fgs = compute_production_part_usage(
        planned,
        *common_args,
    )
    actual_usage, missing_actual_fgs = compute_production_part_usage(
        actual,
        *common_args,
    )
    planned_usage = planned_usage.rename(
        columns={"Production Used Qty": "Planned Part Consumption"}
    )
    actual_usage = actual_usage.rename(
        columns={"Production Used Qty": "Consumed So Far"}
    )
    metadata = ["Part No.", "Part Name", "Supplier"]
    plan_columns = metadata + ["Planned Part Consumption"]
    actual_columns = ["Part No.", "Consumed So Far"]
    result = planned_usage[plan_columns].merge(
        actual_usage[actual_columns] if not actual_usage.empty else pd.DataFrame(columns=actual_columns),
        on="Part No.",
        how="left",
    )
    result["Consumed So Far"] = numeric(result["Consumed So Far"])
    result["Planned Part Consumption"] = numeric(result["Planned Part Consumption"])
    result["Remaining Part Need"] = (
        result["Planned Part Consumption"] - result["Consumed So Far"]
    ).clip(lower=0)

    saved = saved_inventory.copy()
    saved["Part Key"] = saved.get("Part No.", pd.Series(dtype=str)).map(stock_part_key)
    saved = saved.drop_duplicates("Part Key", keep="last").set_index("Part Key")
    result["Part Key"] = result["Part No."].map(stock_part_key)
    preserved = [
        "Buyer",
        "Supplier",
        "Part Name",
        "Today's OS",
        "Tomorrow's OS",
        "System Stock",
        "Physical Stock",
        "Remarks",
    ]
    for column in preserved:
        if column in saved:
            saved_values = result["Part Key"].map(saved[column]).fillna("")
            if column in {"Supplier", "Part Name"}:
                result[column] = saved_values.where(saved_values.ne(""), result[column])
            else:
                result[column] = saved_values
        elif column not in result:
            result[column] = ""

    scm_stock, scm_stock_label = parse_scm_system_stock(
        sources.get("scm_stock_summary", pd.DataFrame())
    )
    if not scm_stock.empty:
        scm_index = scm_stock.set_index("Part Key")
        mapped_scm_stock = result["Part Key"].map(
            scm_index["SCM System Stock"]
        )
        result["SCM Stock Match"] = result["Part Key"].map(
            scm_index["SCM Stock Match"]
        ).fillna("")
        no_exact_match = result["SCM Stock Match"].eq("")
        scm_base_keys = set(scm_stock["Part Key"].map(scm_base_part_key))
        result_base_keys = result["Part Key"].map(scm_base_part_key)
        possible_revision_match = (
            no_exact_match
            & result_base_keys.ne(result["Part Key"])
            & result_base_keys.isin(scm_base_keys)
        )
        result.loc[
            possible_revision_match,
            "SCM Stock Match",
        ] = "Possible revision mismatch — base part exists in SCM"
        result.loc[
            no_exact_match & ~possible_revision_match,
            "SCM Stock Match",
        ] = "Part not found in SCM Summary"
        scm_mapped = mapped_scm_stock.notna()
        result.loc[scm_mapped, "Today's OS"] = mapped_scm_stock.loc[scm_mapped]
        result.loc[scm_mapped, "System Stock"] = mapped_scm_stock.loc[scm_mapped]
        result.loc[scm_mapped, "Physical Stock"] = mapped_scm_stock.loc[scm_mapped]
        diagnostics["scm_stock_rows_mapped"] = int(scm_mapped.sum())
        diagnostics["scm_stock_rows_total"] = len(result)
        diagnostics["scm_stock_label"] = scm_stock_label
        diagnostics["scm_stock_match_counts"] = (
            result["SCM Stock Match"].value_counts().to_dict()
        )
    else:
        result["SCM Stock Match"] = "SCM Summary snapshot unavailable"
        diagnostics["scm_stock_rows_mapped"] = 0
        diagnostics["scm_stock_rows_total"] = len(result)
        diagnostics["scm_stock_label"] = ""
        diagnostics["scm_stock_match_counts"] = {
            "SCM Summary snapshot unavailable": len(result)
        }

    buyer_mapping = clean_buyer_mapping_source(
        load_source_cache(BUYER_MAPPING_CACHE_PATH)
    )
    if not buyer_mapping.empty:
        part_buyers = (
            buyer_mapping[buyer_mapping["Part Number"].ne("")]
            .assign(**{"Part Key": lambda frame: frame["Part Number"].map(stock_part_key)})
            .drop_duplicates("Part Key")
            .set_index("Part Key")["Buyer Name"]
        )
        mapped_buyers = result["Part Key"].map(part_buyers).fillna("")
        result["Buyer"] = result["Buyer"].where(result["Buyer"].astype(str).str.strip().ne(""), mapped_buyers)
    result["Buyer"] = result["Buyer"].replace("", "Unmapped buyer")
    result["Supplier"] = result["Supplier"].replace("", "Unmapped supplier")

    pvin_consumption, pvin_diagnostics = build_pvin_part_consumption(
        sources,
        plan_date,
    )
    diagnostics.update(pvin_diagnostics)
    if not pvin_consumption.empty:
        consumption_lookup = pvin_consumption.set_index("Part No.")
        result["Generated Consumption"] = (
            result["Part No."]
            .map(consumption_lookup["Generated Consumption"])
            .fillna(0)
        )
        result["Produced Consumption"] = (
            result["Part No."]
            .map(consumption_lookup["Produced Consumption"])
            .fillna(0)
        )
    else:
        result["Generated Consumption"] = 0.0
        result["Produced Consumption"] = 0.0

    movements, movement_diagnostics = build_daily_part_movements(
        plan_date,
        result[["Part No.", "Produced Consumption"]],
    )
    diagnostics.update(movement_diagnostics)
    if not movements.empty:
        movement_lookup = movements.set_index("Part Key")
        for column in [
            "Parts Inwarded",
            "Production Outwarded",
            "Other Outwarded",
            "Parts Outwarded",
        ]:
            result[column] = (
                result["Part Key"].map(movement_lookup[column]).fillna(0)
            )
    else:
        result["Parts Inwarded"] = 0.0
        result["Production Outwarded"] = numeric(
            result["Produced Consumption"]
        )
        result["Other Outwarded"] = 0.0
        result["Parts Outwarded"] = result["Production Outwarded"]

    today_os_raw = result["Today's OS"].fillna("").astype(str).str.strip()
    today_os_numeric = pd.to_numeric(today_os_raw, errors="coerce")
    today_os_available = today_os_raw.ne("") & today_os_numeric.notna()
    today_os = today_os_numeric.fillna(0)
    generated_consumption = numeric(result["Generated Consumption"])
    produced_consumption = numeric(result["Produced Consumption"])
    result["Tomorrow's OS"] = (
        today_os
        + numeric(result["Parts Inwarded"])
        - numeric(result["Parts Outwarded"])
    )
    result.loc[~today_os_available, "Tomorrow's OS"] = pd.NA
    result.loc[today_os_available, "System Stock"] = (
        today_os - generated_consumption
    ).clip(lower=0).loc[today_os_available]
    result.loc[today_os_available, "Physical Stock"] = (
        today_os - produced_consumption
    ).loc[today_os_available]
    result["COGI Qty"] = (generated_consumption - today_os).clip(lower=0)

    system_raw = result["System Stock"].fillna("").astype(str).str.strip()
    system_numeric = pd.to_numeric(system_raw, errors="coerce")
    system_available = system_raw.ne("") & system_numeric.notna()
    system = system_numeric.fillna(0)
    physical_raw = result["Physical Stock"].fillna("").astype(str).str.strip()
    physical_numeric = pd.to_numeric(physical_raw, errors="coerce")
    physical_available = physical_raw.ne("") & physical_numeric.notna()
    stock_available = (
        today_os_available & system_available & physical_available
    )
    physical = physical_numeric.fillna(0)
    result["Stock Data Status"] = "Available"
    result.loc[~stock_available, "Stock Data Status"] = "Missing"
    result["Operational Shortage"] = (
        result["Remaining Part Need"] - physical
    ).clip(lower=0).apply(lambda value: int(-(-value // 1)))
    result["Required Qty"] = (
        result["Remaining Part Need"] - system
    ).clip(lower=0).apply(lambda value: int(-(-value // 1)))
    result["Stock Delta"] = physical - system
    result["Expected Delta"] = (
        generated_consumption
        - produced_consumption
        - numeric(result["COGI Qty"])
    )
    result["Unexplained Delta"] = (
        result["Stock Delta"] - result["Expected Delta"]
    )
    result["Delta Flag"] = "Within expected"
    result.loc[
        result["Unexplained Delta"].abs().gt(max(float(delta_threshold), 0)),
        "Delta Flag",
    ] = "Review"
    result["Plan Date"] = plan_date.strftime("%Y-%m-%d")
    result["Daily Production Plan"] = diagnostics.get("daily_target", 0)
    result["Produced So Far"] = diagnostics.get("produced_target", 0)
    result["Status"] = "Healthy"
    result.loc[result["Operational Shortage"].gt(0), "Status"] = "Below required"
    result.loc[
        result["Operational Shortage"].gt(0) & physical.le(0),
        "Status",
    ] = "Critical"
    result.loc[~stock_available, "Required Qty"] = pd.NA
    result.loc[~stock_available, "Operational Shortage"] = pd.NA
    result.loc[~stock_available, "Stock Delta"] = pd.NA
    result.loc[~stock_available, "Expected Delta"] = pd.NA
    result.loc[~stock_available, "Unexplained Delta"] = pd.NA
    result.loc[~stock_available, "Delta Flag"] = "Stock data missing"
    result.loc[~stock_available, "Status"] = "Stock data missing"

    diagnostics["missing_plan_bom_fgs"] = missing_plan_fgs
    diagnostics["missing_actual_bom_fgs"] = missing_actual_fgs
    ordered = TABLES["part_inventory"]["columns"]
    for column in ordered:
        if column not in result:
            result[column] = ""
    return result[ordered].sort_values(
        ["Required Qty", "Supplier", "Part No."],
        ascending=[False, True, True],
    ).reset_index(drop=True), diagnostics


def load_rm_followups() -> pd.DataFrame:
    if not RM_FOLLOWUPS_PATH.exists():
        return pd.DataFrame(columns=RM_FOLLOWUP_COLUMNS)
    frame = pd.read_csv(RM_FOLLOWUPS_PATH, dtype=str).fillna("")
    for column in RM_FOLLOWUP_COLUMNS:
        if column not in frame:
            frame[column] = ""
    return frame[RM_FOLLOWUP_COLUMNS]


def save_rm_followups(frame: pd.DataFrame) -> None:
    cleaned = frame.copy().fillna("")
    for column in RM_FOLLOWUP_COLUMNS:
        if column not in cleaned:
            cleaned[column] = ""
    cleaned = cleaned[RM_FOLLOWUP_COLUMNS].drop_duplicates("Part No.", keep="last")
    RM_FOLLOWUPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = RM_FOLLOWUPS_PATH.with_suffix(".tmp")
    cleaned.to_csv(tmp_path, index=False)
    tmp_path.replace(RM_FOLLOWUPS_PATH)


def load_inventory_control_cases() -> pd.DataFrame:
    if not INVENTORY_CONTROL_CASES_PATH.exists():
        return pd.DataFrame(columns=INVENTORY_CONTROL_CASE_COLUMNS)
    frame = pd.read_csv(
        INVENTORY_CONTROL_CASES_PATH,
        dtype=str,
    ).fillna("")
    for column in INVENTORY_CONTROL_CASE_COLUMNS:
        if column not in frame:
            frame[column] = ""
    return frame[INVENTORY_CONTROL_CASE_COLUMNS]


def reconcile_inventory_control_cases(
    inventory: pd.DataFrame,
) -> pd.DataFrame:
    """Persist delta-review cases and verify resolution on a later recalculation."""
    now_label = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    previous = load_inventory_control_cases()
    previous_lookup = (
        previous.drop_duplicates("Part No.", keep="last").set_index("Part No.")
        if not previous.empty
        else pd.DataFrame(columns=INVENTORY_CONTROL_CASE_COLUMNS).set_index(
            "Part No."
        )
    )
    current = inventory[
        inventory.get(
            "Delta Flag",
            pd.Series("", index=inventory.index),
        ).eq("Review")
    ].copy()
    records: list[dict[str, object]] = []
    active_parts: set[str] = set()
    for _, row in current.iterrows():
        part_no = clean_text(row.get("Part No.", ""))
        if not part_no:
            continue
        active_parts.add(part_no)
        prior = (
            previous_lookup.loc[part_no]
            if part_no in previous_lookup.index
            else pd.Series(dtype=object)
        )
        case_id = clean_text(prior.get("Case ID", ""))
        if not case_id:
            digest = hashlib.sha1(part_no.encode("utf-8")).hexdigest()[:10]
            case_id = f"INV-{digest.upper()}"
        unexplained = pd.to_numeric(
            pd.Series([row.get("Unexplained Delta", "")]),
            errors="coerce",
        ).iloc[0]
        direction = (
            "physical stock exceeds the explained system position"
            if pd.notna(unexplained) and float(unexplained) > 0
            else "physical stock is below the explained system position"
        )
        records.append(
            {
                "Case ID": case_id,
                "Active": "Yes",
                "Part No.": part_no,
                "Part Name": clean_text(row.get("Part Name", "")),
                "Buyer": clean_text(row.get("Buyer", "")),
                "Supplier": clean_text(row.get("Supplier", "")),
                "Unexplained Delta": (
                    float(unexplained) if pd.notna(unexplained) else ""
                ),
                "Status": (
                    clean_text(prior.get("Status", "")) or "New"
                ),
                "Recommended Action": (
                    f"Recount the part and review missing postings because {direction}."
                ),
                "First Detected": (
                    clean_text(prior.get("First Detected", "")) or now_label
                ),
                "Last Checked": now_label,
                "Resolved At": "",
            }
        )
    if not previous.empty:
        for _, prior in previous.iterrows():
            part_no = clean_text(prior.get("Part No.", ""))
            if not part_no or part_no in active_parts:
                continue
            resolved = prior.to_dict()
            resolved["Active"] = "No"
            resolved["Status"] = "Verified resolved"
            resolved["Last Checked"] = now_label
            resolved["Resolved At"] = (
                clean_text(prior.get("Resolved At", "")) or now_label
            )
            records.append(resolved)
    output = pd.DataFrame(records)
    if output.empty:
        output = pd.DataFrame(columns=INVENTORY_CONTROL_CASE_COLUMNS)
    for column in INVENTORY_CONTROL_CASE_COLUMNS:
        if column not in output:
            output[column] = ""
    output = output[INVENTORY_CONTROL_CASE_COLUMNS].drop_duplicates(
        "Part No.",
        keep="first",
    )
    INVENTORY_CONTROL_CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = INVENTORY_CONTROL_CASES_PATH.with_suffix(".tmp")
    output.to_csv(temporary, index=False)
    temporary.replace(INVENTORY_CONTROL_CASES_PATH)
    return output


def load_inventory_corrections() -> pd.DataFrame:
    if not INVENTORY_CORRECTIONS_PATH.exists():
        return pd.DataFrame(columns=INVENTORY_CORRECTION_COLUMNS)
    frame = pd.read_csv(
        INVENTORY_CORRECTIONS_PATH,
        dtype=str,
    ).fillna("")
    for column in INVENTORY_CORRECTION_COLUMNS:
        if column not in frame:
            frame[column] = ""
    return frame[INVENTORY_CORRECTION_COLUMNS]


def save_inventory_corrections(frame: pd.DataFrame) -> None:
    output = frame.copy().fillna("")
    for column in INVENTORY_CORRECTION_COLUMNS:
        if column not in output:
            output[column] = ""
    output = output[INVENTORY_CORRECTION_COLUMNS]
    INVENTORY_CORRECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = INVENTORY_CORRECTIONS_PATH.with_suffix(".tmp")
    output.to_csv(temporary, index=False)
    temporary.replace(INVENTORY_CORRECTIONS_PATH)


def build_part_variant_map(
    exploded_bom: pd.DataFrame,
    sku_mapping: pd.DataFrame,
) -> dict[str, str]:
    if not {"FG", "Component"}.issubset(exploded_bom.columns):
        return {}
    fg_models: dict[str, set[str]] = {}
    for row in sku_mapping.itertuples(index=False, name=None):
        if len(row) < 5:
            continue
        model = clean_text(row[2])
        fg = clean_text(row[4])
        if model and fg:
            fg_models.setdefault(fg, set()).add(model)
    part_models: dict[str, set[str]] = {}
    for row in exploded_bom[["FG", "Component"]].drop_duplicates().itertuples(
        index=False,
        name=None,
    ):
        fg, component = map(clean_text, row)
        for model in fg_models.get(fg, set()):
            part_models.setdefault(stock_part_key(component), set()).add(model)
    return {
        part: ", ".join(sorted(models)[:4])
        + (" +" if len(models) > 4 else "")
        for part, models in part_models.items()
    }


def rm_recommendation(row: pd.Series) -> str:
    status = clean_text(row.get("Supplier Status", "")).lower()
    required_by = pd.to_datetime(row.get("Required By", ""), errors="coerce")
    expected = pd.to_datetime(row.get("Expected Delivery", ""), errors="coerce")
    affected = clean_text(row.get("Affected Variants", "")) or "affected variants"
    quantity = pd.to_numeric(
        pd.Series([row.get("Next Expected Qty", "")]),
        errors="coerce",
    ).fillna(
        pd.to_numeric(
            pd.Series([row.get("RM Shortage", 0)]),
            errors="coerce",
        ).fillna(0)
    ).iloc[0]
    owner = (
        clean_text(row.get("Follow-up Owner", ""))
        or clean_text(row.get("Buyer", ""))
        or "mapped buyer"
    )
    followup = pd.to_datetime(row.get("Next Follow-up", ""), errors="coerce")
    followup_label = (
        followup.strftime("%d %b")
        if pd.notna(followup)
        else "the next follow-up"
    )
    quantity_label = display_qty(quantity)
    required_label = (
        required_by.strftime("%d %b")
        if pd.notna(required_by)
        else "the required date"
    )
    owner_point = f"- **Owner:** {owner} · follow up on **{followup_label}**."
    if status == "delayed":
        eta = expected.strftime("%d %b") if pd.notna(expected) else "confirmed ETA"
        return (
            f"- Expedite or secure alternate supply for **{quantity_label} parts**.\n"
            f"- Move **{affected}** after **{eta}** unless supply is recovered.\n"
            f"{owner_point}"
        )
    if pd.notna(expected) and pd.notna(required_by) and expected > required_by:
        return (
            f"- Pull in **{quantity_label} parts** by **{required_label}**.\n"
            f"- Protect or resequence **{affected}** until the late ETA is resolved.\n"
            f"{owner_point}"
        )
    if status in {"confirmed", "in transit"}:
        eta = expected.strftime("%d %b") if pd.notna(expected) else required_label
        return (
            f"- Track **{quantity_label} parts** against the **{eta}** delivery.\n"
            f"- Escalate immediately if ETA slips beyond **{required_label}**.\n"
            f"{owner_point}"
        )
    if status == "received":
        return (
            f"- Verify receipt and stock posting for **{quantity_label} parts**.\n"
            "- Close the shortage only after Physical Stock reflects the receipt.\n"
            f"{owner_point}"
        )
    return (
        f"- Get supplier confirmation for **{quantity_label} parts** and delivery date.\n"
        f"- Keep an alternate sequence ready for **{affected}** until confirmed.\n"
        f"{owner_point}"
    )


def build_rm_planning_views(
    inventory: pd.DataFrame,
    sources: dict[str, pd.DataFrame],
) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
    if inventory.empty:
        return {}, {"error": "No part requirement rows are available."}
    plan_dates = pd.to_datetime(inventory["Plan Date"], errors="coerce").dropna()
    if plan_dates.empty:
        return {}, {"error": "No production plan date is available."}
    plan_date = plan_dates.max().normalize()
    daily_target = float(numeric(inventory["Daily Production Plan"]).max())
    produced_so_far = float(numeric(inventory["Produced So Far"]).max())

    summary = parse_daily_plan_summary(
        sources.get("daily_plan_summary", pd.DataFrame())
    )
    future = summary[
        summary["Plan Date"].gt(plan_date)
        & summary["Daily Production Plan"].gt(0)
    ][["Plan Date", "Daily Production Plan"]].copy()
    seven_end = plan_date + pd.Timedelta(days=6)
    month_end = plan_date + pd.offsets.MonthEnd(0)
    future_seven = future[future["Plan Date"].le(seven_end)]
    future_month = future[future["Plan Date"].le(month_end)]
    saved_seven_dates = summary[
        summary["Plan Date"].between(plan_date, seven_end)
    ]["Plan Date"]
    saved_month_dates = summary[
        summary["Plan Date"].between(plan_date, month_end)
    ]["Plan Date"]

    part_variants = build_part_variant_map(
        sources.get("exploded_bom", pd.DataFrame()),
        sources.get("sku_map", pd.DataFrame()),
    )
    followups = load_rm_followups().drop_duplicates("Part No.", keep="last")
    followup_lookup = (
        followups.set_index("Part No.")
        if not followups.empty
        else pd.DataFrame(columns=RM_FOLLOWUP_COLUMNS).set_index("Part No.")
    )

    base = inventory.copy()
    system_source = base["System Stock"].fillna("").astype(str).str.strip()
    base["Stock Known"] = (
        base.get("Stock Data Status", pd.Series("", index=base.index))
        .astype(str)
        .eq("Available")
        | (
            system_source.ne("")
            & pd.to_numeric(system_source, errors="coerce").notna()
        )
    )
    base["Physical Stock"] = numeric(base["Physical Stock"])
    base["System Stock"] = numeric(base["System Stock"])
    base["Remaining Part Need"] = numeric(base["Remaining Part Need"])
    base["Planned Part Consumption"] = numeric(base["Planned Part Consumption"])
    base["Part per Planned Vehicle"] = (
        base["Planned Part Consumption"] / daily_target
        if daily_target > 0
        else 0
    )
    base["Affected Variants"] = (
        base["Part No."].map(lambda value: part_variants.get(stock_part_key(value), ""))
    )
    missing_stock = base[~base["Stock Known"]].copy()
    match_reason = missing_stock.get(
        "SCM Stock Match",
        pd.Series("", index=missing_stock.index),
    ).fillna("").astype(str)
    missing_stock["Data Issue"] = match_reason.where(
        match_reason.ne(""),
        "Physical Stock not entered",
    )

    def stock_data_action(reason: object) -> str:
        text = clean_text(reason)
        if text.startswith("Possible revision mismatch"):
            return (
                "Verify the exact revision against the SCM base material. "
                "Base-part stock is not used automatically."
            )
        if text == "Part not found in SCM Summary":
            return (
                "Add the part and System Opening Stock to SCM Summary, or correct "
                "the BOM/master-data part number."
            )
        if text == "System Opening Stock blank":
            return "Populate System Opening Stock for this part in SCM Summary."
        if text.startswith("Invalid System Opening Stock"):
            return "Correct the System Opening Stock value in SCM Summary."
        return (
            "Populate today's opening stock before calculating supplier requirements."
        )

    missing_stock["Recommended Data Action"] = missing_stock["Data Issue"].map(
        stock_data_action
    )

    def build_horizon(
        label: str,
        future_plan: pd.DataFrame,
    ) -> pd.DataFrame:
        view = base.copy()
        future_vehicle_plan = float(future_plan["Daily Production Plan"].sum())
        view["Gross RM Need"] = (
            view["Remaining Part Need"]
            + view["Part per Planned Vehicle"] * future_vehicle_plan
        )
        view["RM Shortage"] = (
            view["Gross RM Need"] - view["System Stock"]
        ).clip(lower=0).apply(lambda value: int(-(-value // 1)))
        view["Horizon"] = label
        view["Horizon Vehicle Plan"] = max(
            daily_target - produced_so_far,
            0,
        ) + future_vehicle_plan

        cumulative = view["Remaining Part Need"].astype(float).copy()
        shortage_dates = pd.Series(pd.NaT, index=view.index, dtype="datetime64[ns]")
        shortage_dates.loc[cumulative.gt(view["System Stock"])] = plan_date
        for _, plan_row in future_plan.sort_values("Plan Date").iterrows():
            cumulative += (
                view["Part per Planned Vehicle"]
                * float(plan_row["Daily Production Plan"])
            )
            newly_short = shortage_dates.isna() & cumulative.gt(view["System Stock"])
            shortage_dates.loc[newly_short] = pd.Timestamp(plan_row["Plan Date"])
        view["Required By"] = shortage_dates.dt.strftime("%Y-%m-%d").fillna("")
        required_ts = pd.to_datetime(view["Required By"], errors="coerce")
        days_to_shortage = (required_ts - plan_date).dt.days
        view["Severity"] = "Covered"
        view.loc[days_to_shortage.eq(0), "Severity"] = "Critical"
        view.loc[days_to_shortage.between(1, 2), "Severity"] = "High"
        view.loc[days_to_shortage.ge(3), "Severity"] = "Medium"
        view = view[view["Stock Known"] & view["RM Shortage"].gt(0)].copy()

        for column in RM_FOLLOWUP_COLUMNS[1:]:
            saved_values = (
                view["Part No."].map(followup_lookup[column]).fillna("")
                if column in followup_lookup
                else ""
            )
            view[column] = saved_values
        view["Supplier Status"] = view["Supplier Status"].replace(
            "",
            "Awaiting confirmation",
        )
        view["Follow-up Owner"] = view["Follow-up Owner"].where(
            view["Follow-up Owner"].ne(""),
            view["Buyer"],
        )
        default_followup = pd.to_datetime(view["Required By"], errors="coerce") - pd.Timedelta(days=2)
        default_followup = default_followup.where(default_followup.gt(plan_date), plan_date)
        view["Next Follow-up"] = view["Next Follow-up"].where(
            view["Next Follow-up"].ne(""),
            default_followup.dt.strftime("%Y-%m-%d").fillna(""),
        )
        view["Recommended Plan Action"] = view.apply(rm_recommendation, axis=1)
        severity_order = {"Critical": 0, "High": 1, "Medium": 2}
        view["_severity_order"] = view["Severity"].map(severity_order).fillna(9)
        return view.sort_values(
            ["_severity_order", "Required By", "RM Shortage"],
            ascending=[True, True, False],
        ).drop(columns="_severity_order").reset_index(drop=True)

    views = {
        "Today": build_horizon("Today", future.iloc[0:0]),
        "Rolling 7 Days": build_horizon("Rolling 7 Days", future_seven),
        "Remaining Month": build_horizon("Remaining Month", future_month),
    }
    meta = {
        "plan_date": plan_date,
        "daily_target": daily_target,
        "produced_so_far": produced_so_far,
        "seven_day_plan": max(daily_target - produced_so_far, 0)
        + float(future_seven["Daily Production Plan"].sum()),
        "month_plan": max(daily_target - produced_so_far, 0)
        + float(future_month["Daily Production Plan"].sum()),
        "seven_day_coverage_end": saved_seven_dates.max()
        if not saved_seven_dates.empty
        else plan_date,
        "month_coverage_end": saved_month_dates.max()
        if not saved_month_dates.empty
        else plan_date,
        "missing_stock": missing_stock,
        "missing_stock_count": len(missing_stock),
        "unmapped_buyer_count": int(base["Buyer"].eq("Unmapped buyer").sum()),
    }
    return views, meta


def build_inventory_status(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    result = df.copy()
    physical_raw = result["Physical Stock"].fillna("").astype(str).str.strip()
    system_raw = result["System Stock"].fillna("").astype(str).str.strip()
    stock_available = (
        physical_raw.ne("")
        & pd.to_numeric(physical_raw, errors="coerce").notna()
        & system_raw.ne("")
        & pd.to_numeric(system_raw, errors="coerce").notna()
    )
    physical = pd.to_numeric(
        physical_raw,
        errors="coerce",
    ).fillna(0)
    system = pd.to_numeric(system_raw, errors="coerce").fillna(0)
    remaining = numeric(result["Remaining Part Need"])
    result["Required Qty"] = (remaining - system).clip(lower=0)
    result["Operational Shortage"] = (remaining - physical).clip(lower=0)
    result["Status"] = "Healthy"
    result.loc[result["Operational Shortage"].gt(0), "Status"] = "Below required"
    result.loc[
        result["Operational Shortage"].gt(0) & physical.le(0),
        "Status",
    ] = "Critical"
    result["Stock Data Status"] = "Available"
    result.loc[~stock_available, "Stock Data Status"] = "Missing"
    result.loc[~stock_available, "Status"] = "Stock data missing"
    return result


def render_metric(
    label: str,
    value: object,
    tone: str = "neutral",
    help_text: str = "",
) -> None:
    colors = {
        "neutral": ("#eff6ff", "#2563eb"),
        "ok": ("#ecfdf5", "#16a34a"),
        "warn": ("#fffbeb", "#d97706"),
        "bad": ("#fef2f2", "#dc2626"),
    }
    bg, accent = colors.get(tone, colors["neutral"])
    tooltip = escape(help_text, quote=True)
    info_icon = (
        f'<span class="metric-info" title="{tooltip}" '
        f'aria-label="{tooltip}">ⓘ</span>'
        if help_text
        else ""
    )
    st.markdown(
        f"""
        <div class="metric-card" title="{tooltip}" style="background:{bg}; border-left-color:{accent};">
            <div class="metric-label">{label}{info_icon}</div>
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


def load_inventory_workspace_snapshot() -> tuple[
    pd.DataFrame,
    dict[str, pd.DataFrame],
    dict[str, object],
]:
    """Load the last saved inventory-planning snapshot without refreshing Google."""
    missing_sources = [
        source["cache"]
        for source in SOURCE_SHEETS.values()
        if not source["cache"].exists()
    ]
    if missing_sources:
        return (
            build_inventory_status(load_table("part_inventory")),
            {},
            {"error": "Planning data has not been saved yet."},
        )
    sources = {
        key: load_source_cache(source["cache"])
        for key, source in SOURCE_SHEETS.items()
    }
    sources, supplement_diagnostics = apply_header_parts_supplement(
        sources
    )
    inventory, diagnostics = build_part_inventory_plan(
        load_table("part_inventory"),
        sources,
        delta_threshold=float(
            st.session_state.get("pvin_delta_threshold", 10.0)
        ),
    )
    diagnostics.update(supplement_diagnostics)
    return inventory, sources, diagnostics


def build_potential_excess_view(
    inventory: pd.DataFrame,
    sources: dict[str, pd.DataFrame],
    horizon: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Screen physical stock against forecast demand using currently available data."""
    if inventory.empty:
        return pd.DataFrame(), {"error": "No inventory rows are available."}
    plan_dates = pd.to_datetime(
        inventory.get("Plan Date", pd.Series(dtype=str)),
        errors="coerce",
    ).dropna()
    if plan_dates.empty:
        return pd.DataFrame(), {"error": "No production plan date is available."}

    plan_date = plan_dates.max().normalize()
    daily_target = float(
        numeric(inventory.get("Daily Production Plan", pd.Series(dtype=float))).max()
    )
    summary = parse_daily_plan_summary(
        sources.get("daily_plan_summary", pd.DataFrame())
    )
    if horizon == "Rolling 7 Days":
        horizon_end = plan_date + pd.Timedelta(days=6)
    else:
        horizon_end = plan_date + pd.offsets.MonthEnd(0)
    future = summary[
        summary["Plan Date"].gt(plan_date)
        & summary["Plan Date"].le(horizon_end)
        & summary["Daily Production Plan"].gt(0)
    ]
    future_vehicle_plan = float(future["Daily Production Plan"].sum())

    view = inventory.copy()
    view["Physical Stock"] = pd.to_numeric(
        view.get("Physical Stock", pd.Series(index=view.index)),
        errors="coerce",
    )
    view["Remaining Part Need"] = numeric(view["Remaining Part Need"])
    view["Planned Part Consumption"] = numeric(
        view["Planned Part Consumption"]
    )
    view["Part per Planned Vehicle"] = (
        view["Planned Part Consumption"] / daily_target
        if daily_target > 0
        else 0
    )
    view["Horizon Demand"] = (
        view["Remaining Part Need"]
        + view["Part per Planned Vehicle"] * future_vehicle_plan
    )
    stock_known = (
        view.get("Stock Data Status", pd.Series("", index=view.index))
        .astype(str)
        .eq("Available")
        & view["Physical Stock"].notna()
    )
    view["Potential Excess Qty"] = (
        view["Physical Stock"].fillna(0) - view["Horizon Demand"]
    ).clip(lower=0)
    view["Coverage Multiple"] = (
        view["Physical Stock"] / view["Horizon Demand"].replace(0, pd.NA)
    )
    view["Excess Signal"] = "Above horizon demand"
    view.loc[
        view["Horizon Demand"].le(0) & view["Physical Stock"].gt(0),
        "Excess Signal",
    ] = "No demand in horizon"
    view.loc[
        view["Horizon Demand"].gt(0) & view["Coverage Multiple"].ge(2),
        "Excess Signal",
    ] = "More than 2× horizon demand"
    view["Data Confidence"] = (
        "Screening estimate — open POs, safety stock and lead time unavailable"
    )
    view["Recommended Action"] = (
        "Verify safety stock and open orders before changing supply."
    )
    view.loc[
        view["Excess Signal"].eq("No demand in horizon"),
        "Recommended Action",
    ] = (
        "Check future demand and freeze additional replenishment pending buyer review."
    )
    view.loc[
        view["Excess Signal"].eq("More than 2× horizon demand"),
        "Recommended Action",
    ] = (
        "Review open orders and consider deferring the next delivery after validation."
    )
    screened = view[
        stock_known
        & view["Physical Stock"].gt(0)
        & view["Potential Excess Qty"].gt(0)
    ].copy()
    screened = screened.sort_values(
        ["Potential Excess Qty", "Coverage Multiple"],
        ascending=[False, False],
    ).reset_index(drop=True)
    meta = {
        "plan_date": plan_date,
        "horizon_end": horizon_end,
        "future_vehicle_plan": future_vehicle_plan,
        "stock_data_gaps": int((~stock_known).sum()),
        "screened_parts": int(stock_known.sum()),
        "confidence": "Indicative only",
    }
    return screened, meta


def render_inventory_executive_overview() -> None:
    inventory, sources, diagnostics = load_inventory_workspace_snapshot()
    st.header(
        "Inventory Control Tower",
        help=(
            "An exceptions-first management view of production progress, line risk, "
            "supplier requirements, excess exposure, and data readiness."
        ),
    )
    if diagnostics.get("error") or inventory.empty:
        st.warning(
            str(
                diagnostics.get(
                    "error",
                    "No inventory snapshot is available. Refresh all sources once.",
                )
            )
        )
        return

    excess, excess_meta = build_potential_excess_view(
        inventory,
        sources,
        "Remaining Month",
    )
    stock_available = inventory["Stock Data Status"].eq("Available")
    operational_shortage = numeric(inventory["Operational Shortage"])
    supplier_required = numeric(inventory["Required Qty"])
    shortage_parts = int(
        (stock_available & operational_shortage.gt(0)).sum()
    )
    missing_parts = int((~stock_available).sum())
    unmapped_mask = inventory["Buyer"].isin(["", "Unmapped buyer"])
    data_issue_parts = int((~stock_available | unmapped_mask).sum())
    supplier_required_qty = float(
        supplier_required.where(stock_available, 0).sum()
    )
    plan_date_values = pd.to_datetime(
        inventory["Plan Date"],
        errors="coerce",
    ).dropna()
    plan_date = (
        plan_date_values.max().normalize()
        if not plan_date_values.empty
        else pd.Timestamp.now().normalize()
    )
    followups = load_rm_followups()
    followup_dates = pd.to_datetime(
        followups.get("Next Follow-up", pd.Series(dtype=str)),
        errors="coerce",
    )
    overdue_mask = followup_dates.le(plan_date) & ~followups.get(
        "Supplier Status",
        pd.Series("", index=followups.index),
    ).isin(["Received"])
    overdue = followups[overdue_mask.fillna(False)].copy()
    overdue_count = len(overdue)
    plan_target = display_qty(diagnostics.get("daily_target", 0))
    total_production = display_qty(diagnostics.get("produced_target", 0))

    st.markdown(
        f"""
        <div class="control-tower-hero">
            <div>
                <span class="control-tower-kicker">TODAY'S DECISION VIEW</span>
                <h2>{plan_target} planned · {total_production} produced so far</h2>
                <p>Work the exceptions below; complete tables and calculation evidence remain available in the focused workflow views.</p>
            </div>
            <div class="control-tower-badge">Data confidence · {escape(str(excess_meta.get("confidence", "Indicative")))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_agent_activity_centre(
        inventory=inventory,
        sources=sources,
        diagnostics=diagnostics,
        potential_excess=excess,
        overdue_count=overdue_count,
    )

    metric_columns = st.columns(5)
    with metric_columns[0]:
        render_metric(
            "Plan / produced",
            f"{plan_target} / {total_production}",
            "neutral",
            (
                "Today's vehicle production target versus total vehicles completed "
                "so far. Total production is separate from Produced P-VIN."
            ),
        )
        st.button(
            "Open requirements",
            key="overview_open_requirements_plan",
            on_click=lambda: st.session_state.update(
                {"inventory_management_workflow": "Requirements"}
            ),
            width="stretch",
        )
    with metric_columns[1]:
        render_metric(
            "Line-risk parts",
            f"{shortage_parts:,}",
            "warn",
            (
                "Number of parts with known Physical Stock where the remaining "
                "production need is greater than the stock physically available."
            ),
        )
        st.button(
            "Open stock health",
            key="overview_open_stock_health",
            on_click=lambda: st.session_state.update(
                {"inventory_management_workflow": "Stock Health"}
            ),
            width="stretch",
        )
    with metric_columns[2]:
        render_metric(
            "Supplier quantity required",
            display_qty(supplier_required_qty),
            "warn",
            (
                "Total additional quantity suppliers must provide to cover the "
                "remaining requirement. Calculated from System Stock, not Physical Stock."
            ),
        )
        st.button(
            "Open requirements",
            key="overview_open_requirements_qty",
            on_click=lambda: st.session_state.update(
                {"inventory_management_workflow": "Requirements"}
            ),
            width="stretch",
        )
    with metric_columns[3]:
        render_metric(
            "Unmapped / missing stock",
            f"{data_issue_parts:,}",
            "neutral",
            (
                "Parts that either have no mapped buyer or do not have usable stock "
                "data. These require data correction before the agent can assign or "
                "assess them reliably."
            ),
        )
        st.button(
            "Open audit",
            key="overview_open_audit",
            on_click=lambda: st.session_state.update(
                {"inventory_management_workflow": "Audit & Evidence"}
            ),
            width="stretch",
        )
    with metric_columns[4]:
        render_metric(
            "Overdue commitments",
            f"{overdue_count:,}",
            "bad" if overdue_count else "ok",
            (
                "Saved supplier follow-ups due on or before the selected plan date "
                "that have not been marked Received."
            ),
        )
        st.button(
            "Open action centre",
            key="overview_open_actions",
            on_click=lambda: st.session_state.update(
                {"inventory_management_workflow": "Action Centre"}
            ),
            width="stretch",
        )

def build_variant_flow_view(
    inventory: pd.DataFrame,
    sources: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    """Build one variant-level control table from the same source state as parts."""
    plan_dates = pd.to_datetime(
        inventory.get("Plan Date", pd.Series(dtype=str)),
        errors="coerce",
    ).dropna()
    if plan_dates.empty:
        return pd.DataFrame(), None
    plan_date = plan_dates.max().normalize()
    variant_plan = parse_production_plan_breakup(
        sources.get("production_plan_breakup", pd.DataFrame())
    )
    variant_plan = variant_plan[
        variant_plan["Plan Date"].eq(plan_date)
    ].copy()
    if variant_plan.empty:
        return pd.DataFrame(), plan_date

    pvin = pvin_input_template(sources, plan_date).rename(
        columns={"Variant": "Model"}
    )
    pvin = pvin[["Model", "Generated P-VIN"]].drop_duplicates(
        "Model",
        keep="last",
    )
    view = variant_plan.merge(pvin, on="Model", how="left")
    view["Generated P-VIN"] = numeric(view["Generated P-VIN"])
    view["Produced P-VIN"] = pd.to_numeric(
        view["P-VIN Produced Qty"],
        errors="coerce",
    )
    view["Daily Plan"] = numeric(view["Planned Qty"]).round().astype(int)
    view["Total Production"] = numeric(view["Produced Qty"]).round().astype(int)
    view["Plan Balance"] = (
        view["Daily Plan"] - view["Total Production"]
    ).clip(lower=0)
    view["Generated–Produced Gap"] = (
        view["Generated P-VIN"]
        - view["Produced P-VIN"].fillna(0)
    )
    view["Completion"] = (
        view["Total Production"]
        / view["Daily Plan"].replace(0, pd.NA)
        * 100
    )
    view["System Trigger"] = view["Generated P-VIN"].map(
        lambda value: f"Deduct BOM × {display_qty(value)}"
    )
    view["Physical Trigger"] = view["Produced P-VIN"].map(
        lambda value: (
            f"Deduct BOM × {display_qty(value)}"
            if pd.notna(value)
            else "P‑VIN data unavailable"
        )
    )
    return (
        view[
            [
                "Model",
                "Daily Plan",
                "Total Production",
                "Visibility Qty",
                "Generated P-VIN",
                "Produced P-VIN",
                "VNA Qty",
                "Free VIN Qty",
                "Plan Balance",
                "Generated–Produced Gap",
                "Completion",
                "System Trigger",
                "Physical Trigger",
            ]
        ].rename(columns={"Model": "Variant"}),
        plan_date,
    )


def build_variant_part_index(
    exploded_bom: pd.DataFrame,
    sku_mapping: pd.DataFrame,
) -> dict[str, set[str]]:
    """Return every mapped component key for each production variant."""
    if not {"FG", "Component"}.issubset(exploded_bom.columns):
        return {}
    fg_variants: dict[str, set[str]] = {}
    for row in sku_mapping.itertuples(index=False, name=None):
        if len(row) < 5:
            continue
        variant = clean_text(row[2])
        fg = clean_text(row[4])
        if variant and fg:
            fg_variants.setdefault(fg, set()).add(variant)
    variant_parts: dict[str, set[str]] = {}
    for fg, component in exploded_bom[
        ["FG", "Component"]
    ].drop_duplicates().itertuples(index=False, name=None):
        fg = clean_text(fg)
        component_key = stock_part_key(component)
        if not component_key:
            continue
        for variant in fg_variants.get(fg, set()):
            variant_parts.setdefault(variant, set()).add(component_key)
    return variant_parts


def render_agent_activity_centre(
    inventory: pd.DataFrame,
    sources: dict[str, pd.DataFrame],
    diagnostics: dict[str, object],
    potential_excess: pd.DataFrame,
    overdue_count: int,
) -> None:
    """Show only agent exceptions that require a person to decide or act."""
    stock_known = inventory["Stock Data Status"].eq("Available")
    shortage_mask = (
        stock_known
        & numeric(inventory["Operational Shortage"]).gt(0)
    )
    shortage_count = int(
        shortage_mask.sum()
    )
    delta_mask = inventory["Delta Flag"].eq("Review")
    delta_count = int(delta_mask.sum())
    missing_stock_mask = ~stock_known
    unmapped_mask = (
        inventory["Buyer"].isin(["", "Unmapped buyer"])
        | inventory["Supplier"].isin(["", "Unmapped supplier"])
    )
    mapping_count = int(
        (unmapped_mask | missing_stock_mask).sum()
    )
    inwarding_actions = load_agent_actions()
    open_inwarding_mask = (
        inwarding_actions.get(
            "Active",
            pd.Series("", index=inwarding_actions.index),
        ).eq("Yes")
        & ~inwarding_actions.get(
            "Status",
            pd.Series("", index=inwarding_actions.index),
        ).isin(["Resolved", "Auto-resolved"])
    )
    open_inwarding_rows = inwarding_actions[open_inwarding_mask].copy()
    open_inwarding = len(open_inwarding_rows)
    produced_available = bool(
        diagnostics.get("produced_pvin_source_available")
    )
    generated_total = float(diagnostics.get("generated_pvin_total", 0))

    def top_owner(frame: pd.DataFrame, column: str) -> str:
        if frame.empty or column not in frame.columns:
            return "Unassigned"
        owners = frame[column].map(clean_text)
        owners = owners[
            ~owners.isin(
                ["", "Unmapped buyer", "Unmapped supplier", "Unassigned"]
            )
        ]
        if owners.empty:
            return "Unassigned"
        return clean_text(owners.value_counts().index[0])

    actions: list[dict[str, str]] = []
    if mapping_count:
        actions.append(
            {
                "priority": "DATA BLOCKER",
                "tone": "warn",
                "title": "Repair inventory data gaps",
                "impact": (
                    f"{mapping_count:,} parts have missing stock or ownership mapping; "
                    "agent conclusions for them require validation."
                ),
                "owner": "Master Data + SCM",
                "due": "Before the next decision run",
                "button": "Open data audit",
                "page": "Inventory Management Agent",
                "workflow": "Audit & Evidence",
            }
        )
    if not produced_available or generated_total <= 0:
        missing_signal = (
            "explicit Produced P‑VIN source"
            if not produced_available
            else "Generated P‑VIN input"
        )
        actions.append(
            {
                "priority": "INPUT NEEDED",
                "tone": "warn",
                "title": "Complete P‑VIN consumption inputs",
                "impact": (
                    f"Missing {missing_signal}; System/Physical consumption cannot "
                    "be treated as a complete live stock movement."
                ),
                "owner": "Production Control",
                "due": "Before stock reconciliation",
                "button": "Open live flow",
                "page": "Inventory Management Agent",
                "workflow": "Live Flow",
            }
        )
    if shortage_count:
        shortage_rows = inventory[shortage_mask]
        critical_count = int(
            shortage_rows.get(
                "Status",
                pd.Series("", index=shortage_rows.index),
            ).eq("Critical").sum()
        )
        actions.append(
            {
                "priority": "PRODUCTION RISK",
                "tone": "bad",
                "title": "Protect the production plan",
                "impact": (
                    f"{shortage_count:,} parts are line-risk"
                    + (
                        f", including {critical_count:,} critical."
                        if critical_count
                        else "."
                    )
                ),
                "owner": top_owner(shortage_rows, "Buyer"),
                "due": "Today",
                "button": "Open shortage queue",
                "page": "Inventory Management Agent",
                "workflow": "Stock Health",
            }
        )
    if open_inwarding:
        inwarding_critical = int(
            open_inwarding_rows.get(
                "Severity",
                pd.Series("", index=open_inwarding_rows.index),
            ).eq("Critical").sum()
        )
        oldest_age = pd.to_numeric(
            open_inwarding_rows.get(
                "Age (days)",
                pd.Series(dtype=float),
            ),
            errors="coerce",
        ).max()
        age_text = (
            f" Oldest case is {int(oldest_age):,} days."
            if pd.notna(oldest_age)
            else ""
        )
        actions.append(
            {
                "priority": "CONTROL ACTION",
                "tone": "bad" if inwarding_critical else "warn",
                "title": "Close inwarding exceptions",
                "impact": (
                    f"{open_inwarding:,} open cases"
                    + (
                        f", including {inwarding_critical:,} critical."
                        if inwarding_critical
                        else "."
                    )
                    + age_text
                ),
                "owner": top_owner(open_inwarding_rows, "Buyer Name"),
                "due": "Today" if inwarding_critical else "Within control SLA",
                "button": "Open inwarding cases",
                "page": "Inwarding Parts",
                "workflow": "",
            }
        )
    if overdue_count:
        followups = load_rm_followups()
        actions.append(
            {
                "priority": "OVERDUE",
                "tone": "bad",
                "title": "Recover supplier commitments",
                "impact": (
                    f"{overdue_count:,} supplier follow-ups are due and have not "
                    "been marked Received."
                ),
                "owner": top_owner(followups, "Follow-up Owner"),
                "due": "Overdue",
                "button": "Open action centre",
                "page": "Inventory Management Agent",
                "workflow": "Action Centre",
            }
        )
    if delta_count:
        delta_rows = inventory[delta_mask]
        actions.append(
            {
                "priority": "RECONCILE",
                "tone": "warn",
                "title": "Explain stock deltas",
                "impact": (
                    f"{delta_count:,} parts exceed the unexplained-delta threshold "
                    "after P‑VIN timing and COGI allowances."
                ),
                "owner": top_owner(delta_rows, "Buyer"),
                "due": "Before stock sign-off",
                "button": "Open reconciliation",
                "page": "Inventory Management Agent",
                "workflow": "Audit & Evidence",
            }
        )
    if not potential_excess.empty:
        actions.append(
            {
                "priority": "VALIDATE",
                "tone": "neutral",
                "title": "Review potential excess",
                "impact": (
                    f"{len(potential_excess):,} indicative signals need open-PO "
                    "and safety-stock validation before changing supply."
                ),
                "owner": top_owner(potential_excess, "Buyer"),
                "due": "Before supplier commitment changes",
                "button": "Open excess review",
                "page": "Inventory Management Agent",
                "workflow": "Requirements",
            }
        )

    st.subheader(
        "Today's Agent Actions",
        help=(
            "Exceptions that need a decision or follow-up now. Each card states the "
            "business impact, accountable owner, urgency, and exact work queue."
        ),
    )
    if actions:
        st.caption(
            f"{len(actions):,} action group(s) require attention. Start with red "
            "production/control risks, then clear inputs and validation decisions."
        )
        for start in range(0, len(actions), 3):
            action_columns = st.columns(3)
            for column, action in zip(
                action_columns,
                actions[start : start + 3],
            ):
                with column:
                    with st.container(border=True):
                        st.markdown(
                            f'<span class="agent-action-pill {action["tone"]}">'
                            f'{escape(action["priority"])}</span>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"#### {action['title']}")
                        st.caption(action["impact"])
                        detail_columns = st.columns(2)
                        with detail_columns[0]:
                            st.markdown("**Owner**")
                            st.caption(action["owner"])
                        with detail_columns[1]:
                            st.markdown("**Due**")
                            st.caption(action["due"])
                        st.button(
                            action["button"],
                            key=(
                                "agent_action_"
                                + re.sub(
                                    r"[^a-z0-9]+",
                                    "_",
                                    action["title"].lower(),
                                ).strip("_")
                            ),
                            width="stretch",
                            on_click=lambda selected=action: (
                                st.session_state.update(
                                    {
                                        "app_navigation": selected["page"],
                                        **(
                                            {
                                                "inventory_management_workflow":
                                                    selected["workflow"]
                                            }
                                            if selected["workflow"]
                                            else {}
                                        ),
                                    }
                                )
                            ),
                        )
    else:
        st.success(
            "No agent exception currently requires a decision or follow-up."
        )

    healthy_agents = []
    if mapping_count == 0:
        healthy_agents.append("Data readiness")
    if produced_available and generated_total > 0:
        healthy_agents.append("P‑VIN consumption")
    if delta_count == 0:
        healthy_agents.append("Reconciliation")
    if shortage_count == 0:
        healthy_agents.append("Shortage prevention")
    if open_inwarding == 0:
        healthy_agents.append("Inwarding control")
    if overdue_count == 0:
        healthy_agents.append("Supplier commitments")
    healthy_agents.append("PPC scenario engine available on demand")
    st.caption("System health · " + " · ".join(healthy_agents))


def render_inventory_live_flow() -> None:
    """Render the live, variant-to-part inventory recalculation workflow."""
    inventory, sources, diagnostics = load_inventory_workspace_snapshot()
    st.header(
        "Live Inventory Flow",
        help=(
            "The controlled path from vehicle plan and P‑VIN activity through BOM "
            "consumption, stock positions, requirements, exceptions and actions."
        ),
    )
    st.caption(
        "Any saved Generated P‑VIN change reruns the same shared calculation used by "
        "Stock Health, Requirements, Excess, buyer queues and audit evidence."
    )
    if diagnostics.get("error") or inventory.empty:
        st.warning(
            str(
                diagnostics.get(
                    "error",
                    "No inventory snapshot is available. Refresh all sources once.",
                )
            )
        )
        return

    variant_view, plan_date = build_variant_flow_view(inventory, sources)
    excess, _ = build_potential_excess_view(
        inventory,
        sources,
        "Remaining Month",
    )
    stock_known = inventory["Stock Data Status"].eq("Available")
    operational_shortage = numeric(inventory["Operational Shortage"])
    supplier_required = numeric(inventory["Required Qty"])
    flow_steps = [
        (
            "1 · Vehicle signal",
            (
                f"{display_qty(diagnostics.get('daily_target', 0))} plan · "
                f"{display_qty(diagnostics.get('produced_target', 0))} total production"
            ),
            "Plan and production are read variant-wise. Total production is never treated as Produced P‑VIN.",
        ),
        (
            "2 · P‑VIN and BOM",
            (
                f"{display_qty(diagnostics.get('generated_pvin_total', 0))} generated · "
                f"{display_qty(diagnostics.get('produced_pvin_total', 0))} produced"
            ),
            "Generated P‑VIN drives System consumption; Produced P‑VIN drives Physical consumption.",
        ),
        (
            "3 · Stock position",
            (
                f"{int(stock_known.sum()):,} available · "
                f"{int((~stock_known).sum()):,} data gaps"
            ),
            "Movements, COGI and explained P‑VIN timing are retained separately.",
        ),
        (
            "4 · Decisions",
            (
                f"{int((stock_known & operational_shortage.gt(0)).sum()):,} shortages · "
                f"{len(excess):,} potential excess"
            ),
            "Supplier requirement uses System Stock; operational shortage uses Physical Stock.",
        ),
    ]
    step_columns = st.columns(4)
    for column, (title, value, detail) in zip(step_columns, flow_steps):
        with column:
            st.markdown(
                f'<div class="flow-control-card">'
                f'<div class="flow-control-step">{escape(title)}</div>'
                f'<div class="flow-control-value">{escape(value)}</div>'
                f'<div class="flow-control-detail">{escape(detail)}</div>'
                "</div>",
                unsafe_allow_html=True,
            )

    st.subheader(
        "Variant control",
        help=(
            "Review plan, total production, Generated P‑VIN and Produced P‑VIN by "
            "variant. Saving Generated P‑VIN immediately recalculates every affected part."
        ),
    )
    if plan_date is None or variant_view.empty:
        st.warning("No variant-wise production plan is available for the selected date.")
        return

    pvin_template = pvin_input_template(sources, plan_date)
    input_col, explanation_col = st.columns([1.8, 1])
    with input_col:
        with st.container(border=True):
            st.subheader(
                "Generated and Produced P‑VIN",
                help=(
                    "Generated P‑VIN is the controlled input until its source is "
                    "integrated. Produced P‑VIN is source-controlled and cannot be edited."
                ),
            )
            edited_pvin = st.data_editor(
                pvin_template,
                width="stretch",
                hide_index=True,
                disabled=["Plan Date", "Variant", "Produced P-VIN"],
                key="live_flow_pvin_editor",
                column_config={
                    "Generated P-VIN": st.column_config.NumberColumn(
                        min_value=0,
                        step=1,
                        help="Reduces System Stock through the variant BOM.",
                    ),
                    "Produced P-VIN": st.column_config.NumberColumn(
                        min_value=0,
                        step=1,
                        help=(
                            "Read only from the explicit P‑VIN production source. "
                            "Reduces Physical Stock through the variant BOM."
                        ),
                    ),
                },
            )
            save_col, threshold_col = st.columns([1, 1])
            with save_col:
                if st.button(
                    "Save and recalculate",
                    type="primary",
                    key="live_flow_save_pvin",
                    width="stretch",
                    help=(
                        "Save the variant input and rerun all part, stock, shortage, "
                        "excess, reconciliation and action calculations."
                    ),
                ):
                    all_inputs = load_pvin_inputs()
                    date_label = plan_date.strftime("%Y-%m-%d")
                    all_inputs = all_inputs[
                        ~all_inputs["Plan Date"].eq(date_label)
                    ]
                    save_pvin_inputs(
                        pd.concat(
                            [all_inputs, edited_pvin],
                            ignore_index=True,
                        )
                    )
                    st.success(
                        "P‑VIN figures saved. All dependent inventory views were recalculated."
                    )
                    st.rerun()
            with threshold_col:
                st.number_input(
                    "Delta alert threshold",
                    min_value=0.0,
                    value=float(
                        st.session_state.get("pvin_delta_threshold", 10.0)
                    ),
                    step=1.0,
                    key="live_flow_delta_threshold",
                    help=(
                        "Create reconciliation review when the absolute unexplained "
                        "System-versus-Physical difference exceeds this quantity."
                    ),
                )
                st.session_state["pvin_delta_threshold"] = float(
                    st.session_state["live_flow_delta_threshold"]
                )
    with explanation_col:
        with st.container(border=True):
            st.subheader(
                "Calculation rules",
                help="The independent stock triggers used throughout the application.",
            )
            st.markdown(
                "- **Generated P‑VIN × BOM** → System consumption\n"
                "- **Produced P‑VIN × BOM** → Physical consumption\n"
                "- System Stock floors at zero; remainder becomes **COGI**\n"
                "- Total Production remains a separate production KPI\n"
                "- Only the newly saved state is used on the next calculation"
            )
            if not diagnostics.get("produced_pvin_source_available"):
                st.warning(
                    "Produced P‑VIN is unavailable. The app has not substituted "
                    "Total Production."
                )

    st.subheader(
        "Variant-wise operating table",
        help=(
            "The table keeps total production, Generated P‑VIN and Produced P‑VIN "
            "separate and shows the stock trigger created by each quantity."
        ),
    )
    total_columns = [
        "Daily Plan",
        "Total Production",
        "Visibility Qty",
        "Generated P-VIN",
        "Produced P-VIN",
        "VNA Qty",
        "Free VIN Qty",
        "Plan Balance",
        "Generated–Produced Gap",
    ]
    total_row: dict[str, object] = {
        column: variant_view[column].sum(min_count=1)
        for column in total_columns
    }
    total_row["Variant"] = "TOTAL"
    total_daily_plan = float(total_row["Daily Plan"] or 0)
    total_production = float(total_row["Total Production"] or 0)
    total_row["Completion"] = (
        total_production / total_daily_plan * 100
        if total_daily_plan > 0
        else pd.NA
    )
    total_row["System Trigger"] = "Combined generated P‑VIN"
    total_row["Physical Trigger"] = "Combined produced P‑VIN"
    variant_table = pd.concat(
        [variant_view, pd.DataFrame([total_row])],
        ignore_index=True,
    )
    total_row_index = len(variant_table) - 1
    whole_number_columns = [
        "Daily Plan",
        "Total Production",
        "Visibility Qty",
        "Generated P-VIN",
        "Produced P-VIN",
        "VNA Qty",
        "Free VIN Qty",
        "Plan Balance",
        "Generated–Produced Gap",
    ]
    variant_styler = (
        variant_table.style.format(
            {column: "{:.0f}" for column in whole_number_columns},
            na_rep="—",
        )
        .apply(
            lambda row: (
                [
                    "background-color:#f1f5f9;font-weight:800;color:#162033"
                ]
                * len(row)
                if row.name == total_row_index
                else [""] * len(row)
            ),
            axis=1,
        )
    )
    st.dataframe(
        variant_styler,
        width="stretch",
        hide_index=True,
        height=min(555, 42 + len(variant_table) * 35),
        column_config={
            "Daily Plan": st.column_config.NumberColumn(format="%d"),
            "Visibility Qty": st.column_config.NumberColumn(format="%d"),
            "Generated P-VIN": st.column_config.NumberColumn(format="%d"),
            "Produced P-VIN": st.column_config.NumberColumn(
                format="%d",
                help="Explicit source P‑VIN only; blank means unavailable."
            ),
            "Total Production": st.column_config.NumberColumn(
                format="%d",
                help="Visibility / total vehicles completed. Not Produced P‑VIN."
            ),
            "VNA Qty": st.column_config.NumberColumn(format="%d"),
            "Free VIN Qty": st.column_config.NumberColumn(format="%d"),
            "Plan Balance": st.column_config.NumberColumn(format="%d"),
            "Generated–Produced Gap": st.column_config.NumberColumn(
                format="%d"
            ),
            "Completion": st.column_config.ProgressColumn(
                format="%.0f%%",
                min_value=0,
                max_value=100,
            ),
        },
    )

    st.subheader(
        "Inventory master sheet",
        help=(
            "The complete part-level calculation base used by Stock Health, "
            "Shortage, Excess, Reconciliation and buyer-action agents."
        ),
    )
    st.caption(
        "Search the full master, change the working view, or select one row to "
        "audit its end-to-end demand, movement and stock calculation."
    )
    master = inventory.copy()
    master["Supplier Required Qty"] = supplier_required
    master["Operational Shortage"] = operational_shortage
    filter_columns = st.columns([1.7, 1, 1, 1, 0.75])
    with filter_columns[0]:
        master_search = st.text_input(
            "Search master",
            placeholder="Part number, part name, buyer or supplier",
            key="live_flow_master_search",
        )
    with filter_columns[1]:
        health_options = [
            "All stock health",
            *sorted(master["Status"].replace("", pd.NA).dropna().unique()),
        ]
        master_health = st.selectbox(
            "Stock health",
            health_options,
            key="live_flow_master_health",
        )
    buyer_options = sorted(
        master["Buyer"].replace("", pd.NA).dropna().unique().tolist()
    )
    with filter_columns[2]:
        master_buyer = st.selectbox(
            "Buyer",
            ["All buyers", *buyer_options],
            key="live_flow_master_buyer",
        )
    supplier_source = master
    if master_buyer != "All buyers":
        supplier_source = supplier_source[
            supplier_source["Buyer"].eq(master_buyer)
        ]
    supplier_options = sorted(
        supplier_source["Supplier"]
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    buyer_key = re.sub(
        r"[^a-z0-9]+",
        "_",
        master_buyer.lower(),
    ).strip("_")
    with filter_columns[3]:
        master_supplier = st.selectbox(
            "Supplier",
            ["All suppliers", *supplier_options],
            key=f"live_flow_master_supplier_{buyer_key}",
            help="Supplier choices are limited to the selected buyer.",
        )
    with filter_columns[4]:
        master_view = st.selectbox(
            "Columns",
            ["Decision", "Movement", "Complete"],
            key="live_flow_master_view",
            help="Switch between focused decision columns, movement evidence and the complete calculation base.",
        )

    filtered = master.copy()
    if master_health != "All stock health":
        filtered = filtered[filtered["Status"].eq(master_health)]
    if master_buyer != "All buyers":
        filtered = filtered[filtered["Buyer"].eq(master_buyer)]
    if master_supplier != "All suppliers":
        filtered = filtered[filtered["Supplier"].eq(master_supplier)]
    if master_search.strip():
        term = master_search.strip()
        filtered = filtered[
            filtered[
                ["Part No.", "Part Name", "Buyer", "Supplier"]
            ]
            .astype(str)
            .apply(
                lambda column: column.str.contains(
                    term,
                    case=False,
                    na=False,
                    regex=False,
                )
            )
            .any(axis=1)
        ]

    master_metrics = st.columns(6)
    master_metric_values = [
        ("Parts shown", len(filtered), "neutral"),
        ("Healthy", int(filtered["Status"].eq("Healthy").sum()), "ok"),
        (
            "Below required",
            int(filtered["Status"].eq("Below required").sum()),
            "warn",
        ),
        ("Critical", int(filtered["Status"].eq("Critical").sum()), "bad"),
        (
            "Stock missing",
            int(filtered["Status"].eq("Stock data missing").sum()),
            "warn",
        ),
        (
            "Delta review",
            int(filtered["Delta Flag"].eq("Review").sum()),
            "warn",
        ),
    ]
    for column, (label, value, tone) in zip(
        master_metrics,
        master_metric_values,
    ):
        with column:
            render_metric(label, value, tone)

    view_columns = {
        "Decision": [
            "Part No.",
            "Part Name",
            "Buyer",
            "Supplier",
            "System Stock",
            "Physical Stock",
            "Remaining Part Need",
            "Supplier Required Qty",
            "Operational Shortage",
            "Status",
            "Delta Flag",
        ],
        "Movement": [
            "Part No.",
            "Part Name",
            "Today's OS",
            "Parts Inwarded",
            "Production Outwarded",
            "Other Outwarded",
            "Parts Outwarded",
            "Tomorrow's OS",
            "Generated Consumption",
            "Produced Consumption",
            "COGI Qty",
        ],
        "Complete": [
            "Buyer",
            "Supplier",
            "Part No.",
            "Part Name",
            "Plan Date",
            "Daily Production Plan",
            "Produced So Far",
            "Planned Part Consumption",
            "Consumed So Far",
            "Remaining Part Need",
            "Supplier Required Qty",
            "Operational Shortage",
            "Today's OS",
            "Parts Inwarded",
            "Production Outwarded",
            "Other Outwarded",
            "Parts Outwarded",
            "Tomorrow's OS",
            "System Stock",
            "Physical Stock",
            "Generated Consumption",
            "Produced Consumption",
            "COGI Qty",
            "Stock Delta",
            "Expected Delta",
            "Unexplained Delta",
            "Delta Flag",
            "SCM Stock Match",
            "Stock Data Status",
            "Status",
            "Remarks",
        ],
    }
    visible_columns = view_columns[master_view]
    master_table = filtered[visible_columns].copy()
    numeric_columns = [
        column
        for column in visible_columns
        if column
        in {
            "Daily Production Plan",
            "Produced So Far",
            "Planned Part Consumption",
            "Consumed So Far",
            "Remaining Part Need",
            "Supplier Required Qty",
            "Operational Shortage",
            "Today's OS",
            "Parts Inwarded",
            "Production Outwarded",
            "Other Outwarded",
            "Parts Outwarded",
            "Tomorrow's OS",
            "System Stock",
            "Physical Stock",
            "Generated Consumption",
            "Produced Consumption",
            "COGI Qty",
            "Stock Delta",
            "Expected Delta",
            "Unexplained Delta",
        }
    ]
    for column in numeric_columns:
        master_table[column] = pd.to_numeric(
            master_table[column],
            errors="coerce",
        )
    master_actions = st.columns([1, 5])
    with master_actions[0]:
        st.download_button(
            "Download master CSV",
            filtered.to_csv(index=False),
            file_name="inventory_master_sheet.csv",
            mime="text/csv",
            key="live_flow_master_download",
            width="stretch",
        )
    with master_actions[1]:
        st.caption(
            f"Showing {len(filtered):,} of {len(master):,} parts · "
            f"{master_view.lower()} column view"
        )
    selection = st.dataframe(
        master_table,
        width="stretch",
        hide_index=True,
        height=560,
        on_select="rerun",
        selection_mode="single-row",
        key=f"live_flow_master_{master_view.lower()}",
    )
    selected_rows = (
        selection.selection.rows
        if hasattr(selection, "selection")
        else selection.get("selection", {}).get("rows", [])
    )
    if not selected_rows:
        st.caption(
            "Select one part to open its complete calculation and movement evidence."
        )
        return
    part = filtered.iloc[selected_rows[0]]
    st.subheader(
        "Part calculation evidence",
        help=(
            "The complete result chain for the selected variant component, using the "
            "same quantities shown in all agent workspaces."
        ),
    )
    calculation_tab, movement_tab, decision_tab = st.tabs(
        ["Demand and stock", "Movements and P‑VIN", "Decision output"]
    )
    with calculation_tab:
        st.dataframe(
            pd.DataFrame(
                [
                    ("Planned Part Consumption", part["Planned Part Consumption"]),
                    ("Consumed So Far", part["Consumed So Far"]),
                    ("Remaining Part Need", part["Remaining Part Need"]),
                    ("System Stock", part["System Stock"]),
                    ("Physical Stock", part["Physical Stock"]),
                    ("Supplier Required Qty", part["Supplier Required Qty"]),
                    ("Operational Shortage", part["Operational Shortage"]),
                ],
                columns=["Stage", "Result"],
            ),
            width="stretch",
            hide_index=True,
        )
    with movement_tab:
        st.dataframe(
            pd.DataFrame(
                [
                    ("Today's OS", part["Today's OS"]),
                    ("Parts Inwarded", part["Parts Inwarded"]),
                    ("Generated-PVIN consumption", part["Generated Consumption"]),
                    ("Produced-PVIN consumption", part["Produced Consumption"]),
                    ("Production Outwarded", part["Production Outwarded"]),
                    ("Other Outwarded", part["Other Outwarded"]),
                    ("Tomorrow's OS", part["Tomorrow's OS"]),
                    ("COGI", part["COGI Qty"]),
                ],
                columns=["Movement", "Quantity"],
            ),
            width="stretch",
            hide_index=True,
        )
    with decision_tab:
        st.write(
            f"**Stock health:** {part['Status']}  \n"
            f"**Delta state:** {part['Delta Flag']}  \n"
            f"**Buyer:** {part['Buyer']}  \n"
            f"**Supplier:** {part['Supplier']}"
        )
        if float(part["Operational Shortage"]) > 0:
            st.error(
                "Shortage Agent: protect production and confirm the required supplier quantity."
            )
        elif part["Delta Flag"] == "Review":
            st.warning(
                "Reconciliation Agent: recount and review missing postings before changing supply."
            )
        else:
            st.success("No immediate shortage or unexplained-delta action is required.")


def render_buyer_command_centre() -> None:
    inventory, sources, diagnostics = load_inventory_workspace_snapshot()
    st.header(
        "Buyer Command Centre",
        help=(
            "Select a buyer to see every shortage, responsible supplier, required "
            "quantity, due date, confirmed incoming quantity, ETA, and next action."
        ),
    )
    st.write(
        "A buyer-owned action queue. Supplier choices automatically narrow to the "
        "suppliers mapped to the selected buyer."
    )
    if diagnostics.get("error") or inventory.empty:
        st.warning(
            str(
                diagnostics.get(
                    "error",
                    "No inventory snapshot is available. Refresh all sources once.",
                )
            )
        )
        return
    views, meta = build_rm_planning_views(inventory, sources)
    if not views:
        st.warning(str(meta.get("error", "No buyer work queue could be built.")))
        return

    horizon = st.radio(
        "Planning horizon",
        list(views),
        horizontal=True,
        key="buyer_centre_horizon",
        help="Changes the demand window used for required quantity and required-by date.",
    )
    queue = views[horizon].copy()
    if queue.empty:
        st.success(f"No supplier requirement is open for {horizon.lower()}.")
        return
    queue["Confirmed Incoming Qty"] = pd.to_numeric(
        queue.get("Next Expected Qty", pd.Series(index=queue.index)),
        errors="coerce",
    ).fillna(0)
    confirmed_status = queue["Supplier Status"].isin(["Confirmed", "In transit"])
    queue.loc[~confirmed_status, "Confirmed Incoming Qty"] = 0
    queue["Recommended Next Action"] = queue["Recommended Plan Action"]

    buyers = sorted(
        queue["Buyer"].replace("", pd.NA).dropna().unique().tolist()
    )
    filter_columns = st.columns([1, 1, 1.5])
    with filter_columns[0]:
        buyer = st.selectbox(
            "Buyer",
            ["All buyers"] + buyers,
            key="buyer_centre_buyer",
        )
    supplier_source = queue
    if buyer != "All buyers":
        supplier_source = supplier_source[supplier_source["Buyer"].eq(buyer)]
    suppliers = sorted(
        supplier_source["Supplier"].replace("", pd.NA).dropna().unique().tolist()
    )
    supplier_key = re.sub(r"[^a-z0-9]+", "_", buyer.lower()).strip("_")
    with filter_columns[1]:
        supplier = st.selectbox(
            "Supplier",
            ["All suppliers"] + suppliers,
            key=f"buyer_centre_supplier_{supplier_key}",
            help="Only suppliers assigned to the selected buyer are available.",
        )
    with filter_columns[2]:
        search = st.text_input(
            "Search part",
            placeholder="part number or part name",
            key="buyer_centre_search",
        )

    filtered = queue.copy()
    if buyer != "All buyers":
        filtered = filtered[filtered["Buyer"].eq(buyer)]
    if supplier != "All suppliers":
        filtered = filtered[filtered["Supplier"].eq(supplier)]
    if search.strip():
        term = search.strip()
        filtered = filtered[
            filtered[["Part No.", "Part Name"]]
            .astype(str)
            .apply(
                lambda column: column.str.contains(
                    term,
                    case=False,
                    na=False,
                    regex=False,
                )
            )
            .any(axis=1)
        ]

    needs_contact = filtered[
        filtered["Supplier Status"].isin(
            ["Awaiting confirmation", "Delayed"]
        )
    ]
    earliest_required = pd.to_datetime(
        filtered["Required By"],
        errors="coerce",
    ).min()
    nearest_eta = pd.to_datetime(
        filtered.loc[
            filtered["Confirmed Incoming Qty"].gt(0),
            "Expected Delivery",
        ],
        errors="coerce",
    ).min()
    metrics = st.columns(6)
    with metrics[0]:
        render_metric(
            "Critical parts",
            f"{int(filtered['Severity'].eq('Critical').sum()):,}",
            "bad",
        )
    with metrics[1]:
        render_metric(
            "Suppliers needing contact",
            f"{needs_contact['Supplier'].nunique():,}",
            "warn",
        )
    with metrics[2]:
        render_metric(
            "Required quantity",
            display_qty(numeric(filtered["RM Shortage"]).sum()),
            "warn",
        )
    with metrics[3]:
        render_metric(
            "Required by",
            earliest_required.strftime("%d %b")
            if pd.notna(earliest_required)
            else "—",
            "neutral",
        )
    with metrics[4]:
        render_metric(
            "Confirmed incoming",
            display_qty(numeric(filtered["Confirmed Incoming Qty"]).sum()),
            "ok",
        )
    with metrics[5]:
        render_metric(
            "Nearest confirmed ETA",
            nearest_eta.strftime("%d %b") if pd.notna(nearest_eta) else "—",
            "neutral",
        )

    st.caption(
        f"{len(filtered):,} action(s) shown. Confirmed incoming includes only "
        "supplier records marked Confirmed or In transit."
    )
    if filtered.empty:
        st.success("No issues match this buyer, supplier, and search combination.")
        return
    decision_columns = [
        "Severity",
        "Part No.",
        "Part Name",
        "Supplier",
        "RM Shortage",
        "Required By",
        "Confirmed Incoming Qty",
        "Expected Delivery",
        "Supplier Status",
        "Recommended Next Action",
    ]
    decision_table = filtered[decision_columns].rename(
        columns={"RM Shortage": "Required Qty"}
    )
    selection = st.dataframe(
        decision_table,
        width="stretch",
        hide_index=True,
        height=min(520, 42 + len(decision_table.head(14)) * 35),
        on_select="rerun",
        selection_mode="single-row",
        key=f"buyer_centre_queue_{normalize_column_name(horizon)}",
    )
    selected_rows = (
        selection.selection.rows
        if hasattr(selection, "selection")
        else selection.get("selection", {}).get("rows", [])
    )
    if not selected_rows:
        st.info(
            "Select a row for a concise agent brief. Use Action Centre "
            "to record or update the supplier commitment."
        )
        st.download_button(
            "Download buyer action queue",
            decision_table.to_csv(index=False),
            file_name=f"buyer_actions_{normalize_column_name(horizon)}.csv",
            mime="text/csv",
        )
        return

    selected = filtered.iloc[selected_rows[0]]
    st.subheader(
        "Agent brief",
        help="The evidence, commitment gap, and recommended next action for the selected part.",
    )
    commitment_gap = max(
        float(numeric(pd.Series([selected["RM Shortage"]])).iloc[0])
        - float(
            numeric(pd.Series([selected["Confirmed Incoming Qty"]])).iloc[0]
        ),
        0,
    )
    brief_columns = st.columns([1.35, 1])
    with brief_columns[0]:
        st.markdown(
            f"### {escape(clean_text(selected['Part No.']))} · "
            f"{escape(clean_text(selected['Part Name']) or 'Part name unavailable')}"
        )
        st.write(
            f"**Buyer:** {clean_text(selected['Buyer']) or 'Unmapped'}  \n"
            f"**Supplier:** {clean_text(selected['Supplier']) or 'Unmapped'}  \n"
            f"**Required quantity:** {display_qty(selected['RM Shortage'])}  \n"
            f"**Confirmed incoming:** {display_qty(selected['Confirmed Incoming Qty'])}  \n"
            f"**Uncovered quantity:** {display_qty(commitment_gap)}  \n"
            f"**Required by:** {clean_text(selected['Required By']) or 'Unavailable'}  \n"
            f"**Expected delivery:** {clean_text(selected['Expected Delivery']) or 'Not confirmed'}"
        )
    with brief_columns[1]:
        st.info(
            "**Recommended next action**\n\n"
            + clean_text(selected["Recommended Next Action"])
        )


def render_inventory_data_audit() -> None:
    inventory, sources, diagnostics = load_inventory_workspace_snapshot()
    st.header(
        "Data Readiness & Audit",
        help=(
            "Shows source freshness, stock and ownership coverage, calculation "
            "exceptions, and the audit capabilities that are or are not implemented."
        ),
    )
    source_labels = {
        "daily_plan_summary": "Daily plan summary",
        "production_plan_breakup": "Production plan breakup",
        "vin_details": "VIN details / colour mix",
        "sku_map": "SKU mapping",
        "exploded_bom": "Exploded BOM",
        "raw_bom": "Raw BOM",
        "part_types": "Part types",
        "suppliers": "Supplier master",
        "scm_stock_summary": "SCM stock summary",
    }
    source_rows = []
    for key, source in SOURCE_SHEETS.items():
        path = source["cache"]
        frame = sources.get(key, pd.DataFrame())
        source_rows.append(
            {
                "Source": source_labels.get(key, key.replace("_", " ").title()),
                "Status": "Saved" if path.exists() else "Missing",
                "Rows": len(frame) if path.exists() else 0,
                "Last saved": (
                    datetime.fromtimestamp(path.stat().st_mtime).strftime(
                        "%d %b %Y · %H:%M"
                    )
                    if path.exists()
                    else "—"
                ),
            }
        )
    additional_sources = [
        ("Inwarding snapshot", INWARDING_SNAPSHOT_PATH),
        ("Buyer mapping", BUYER_MAPPING_CACHE_PATH),
        ("Computed outwarding", COMPUTED_USAGE_CACHE_PATH),
        ("Generated P-VIN inputs", PVIN_INPUTS_PATH),
    ]
    for label, path in additional_sources:
        rows = 0
        if path.exists():
            try:
                rows = len(pd.read_csv(path, dtype=str))
            except Exception:
                rows = 0
        source_rows.append(
            {
                "Source": label,
                "Status": "Saved" if path.exists() else "Missing",
                "Rows": rows,
                "Last saved": (
                    datetime.fromtimestamp(path.stat().st_mtime).strftime(
                        "%d %b %Y · %H:%M"
                    )
                    if path.exists()
                    else "—"
                ),
            }
        )
    source_register = pd.DataFrame(source_rows)
    saved_sources = int(source_register["Status"].eq("Saved").sum())
    missing_sources = int(source_register["Status"].eq("Missing").sum())
    stock_gaps = (
        int(inventory["Stock Data Status"].ne("Available").sum())
        if not inventory.empty and "Stock Data Status" in inventory
        else 0
    )
    delta_reviews = (
        int(inventory["Delta Flag"].eq("Review").sum())
        if not inventory.empty and "Delta Flag" in inventory
        else 0
    )
    unmapped_buyers = (
        int(inventory["Buyer"].isin(["", "Unmapped buyer"]).sum())
        if not inventory.empty and "Buyer" in inventory
        else 0
    )
    readiness = st.columns(5)
    with readiness[0]:
        render_metric("Sources ready", f"{saved_sources:,}", "ok")
    with readiness[1]:
        render_metric("Sources missing", f"{missing_sources:,}", "bad")
    with readiness[2]:
        render_metric("Stock-data gaps", f"{stock_gaps:,}", "warn")
    with readiness[3]:
        render_metric("Delta reviews", f"{delta_reviews:,}", "warn")
    with readiness[4]:
        render_metric("Unmapped buyers", f"{unmapped_buyers:,}", "neutral")

    st.subheader(
        "Source register",
        help="The last saved local copy remains active until a successful refresh replaces it.",
    )
    st.dataframe(
        source_register,
        width="stretch",
        hide_index=True,
        height=420,
    )

    st.subheader(
        "Control status",
        help="A transparent list of safeguards currently active and planned controls not yet available.",
    )
    control_rows = pd.DataFrame(
        [
            (
                "System vs Physical timing",
                "Active",
                "Expected P-VIN timing and COGI are removed before Delta Review.",
            ),
            (
                "Missing-stock suppression",
                "Active",
                "Parts without verified stock are excluded from shortage decisions.",
            ),
            (
                "Buyer/supplier ownership",
                "Active",
                "Supplier lists depend on the selected buyer.",
            ),
            (
                "Supplier action log",
                "Active",
                "Status, expected quantity, ETA, follow-up, owner and notes are saved.",
            ),
            (
                "User-attributed stock correction",
                "Request log active",
                "Reason, requester, approver and decision are retained; Google identity autofill and ERP/Sheet write-back remain pending.",
            ),
            (
                "Automatic supplier communication",
                "Not yet implemented",
                "The app recommends and schedules follow-up but does not send messages.",
            ),
            (
                "Confirmed excess decision",
                "Not yet implemented",
                "Open POs, incoming supply, safety stock, lead time and MOQ are required.",
            ),
        ],
        columns=["Control", "Status", "Meaning"],
    )
    st.dataframe(
        control_rows,
        width="stretch",
        hide_index=True,
    )
    if diagnostics.get("error"):
        st.warning(str(diagnostics["error"]))
    else:
        st.info(
            "Use Audit & Evidence → Calculation evidence for the optional "
            "end-to-end trace. This page reports readiness and control coverage."
        )


def render_stock_health_workspace() -> None:
    inventory, sources, diagnostics = load_inventory_workspace_snapshot()
    st.header(
        "Stock Health",
        help=(
            "An exceptions-first view of healthy, below-required, critical, "
            "missing-stock, and unexplained-delta parts."
        ),
    )
    if diagnostics.get("error") or inventory.empty:
        st.warning(
            str(
                diagnostics.get(
                    "error",
                    "No inventory snapshot is available. Refresh all sources once.",
                )
            )
        )
        return
    control_cases = reconcile_inventory_control_cases(inventory)
    planning_views, _ = build_rm_planning_views(inventory, sources)
    rolling = planning_views.get("Rolling 7 Days", pd.DataFrame())
    planning_lookup = (
        rolling.drop_duplicates("Part No.", keep="first").set_index("Part No.")
        if not rolling.empty
        else pd.DataFrame()
    )
    work = inventory.copy()
    for column, default in [
        ("Required By", ""),
        ("Severity", ""),
        ("Supplier Status", "Not started"),
    ]:
        work[column] = (
            work["Part No."].map(planning_lookup[column]).fillna(default)
            if column in planning_lookup
            else default
        )
    work["Severity"] = work["Severity"].where(
        work["Severity"].ne(""),
        work["Status"].map(
            {
                "Critical": "Critical",
                "Below required": "High",
                "Healthy": "Healthy",
                "Stock data missing": "Unavailable",
            }
        ).fillna("Unavailable"),
    )
    work["Action Status"] = work["Supplier Status"].replace(
        "",
        "Not started",
    )
    queue_frames = {
        "Critical": work[work["Status"].eq("Critical")],
        "Below required": work[work["Status"].eq("Below required")],
        "Delta review": work[work["Delta Flag"].eq("Review")],
        "Stock data missing": work[work["Status"].eq("Stock data missing")],
        "Healthy": work[work["Status"].eq("Healthy")],
    }
    queue_labels = {
        name: f"{name} ({len(frame):,})"
        for name, frame in queue_frames.items()
    }
    queue_name = st.radio(
        "Stock-health queue",
        list(queue_frames),
        horizontal=True,
        format_func=lambda value: queue_labels[value],
        key="stock_health_queue",
    )
    queue = queue_frames[queue_name].copy()
    filters = st.columns([1.5, 1, 1])
    with filters[0]:
        search = st.text_input(
            "Search part",
            placeholder="part number, part name, or supplier",
            key="stock_health_search",
        )
    buyers = sorted(
        queue["Buyer"].replace("", pd.NA).dropna().unique().tolist()
    )
    with filters[1]:
        buyer = st.selectbox(
            "Buyer",
            ["All buyers"] + buyers,
            key="stock_health_buyer",
        )
    supplier_source = queue
    if buyer != "All buyers":
        supplier_source = supplier_source[supplier_source["Buyer"].eq(buyer)]
    suppliers = sorted(
        supplier_source["Supplier"].replace("", pd.NA).dropna().unique().tolist()
    )
    supplier_key = re.sub(r"[^a-z0-9]+", "_", buyer.lower()).strip("_")
    with filters[2]:
        supplier = st.selectbox(
            "Supplier",
            ["All suppliers"] + suppliers,
            key=f"stock_health_supplier_{supplier_key}",
        )
    filtered = queue.copy()
    if buyer != "All buyers":
        filtered = filtered[filtered["Buyer"].eq(buyer)]
    if supplier != "All suppliers":
        filtered = filtered[filtered["Supplier"].eq(supplier)]
    if search.strip():
        term = search.strip()
        filtered = filtered[
            filtered[["Part No.", "Part Name", "Supplier"]]
            .astype(str)
            .apply(
                lambda column: column.str.contains(
                    term,
                    case=False,
                    na=False,
                    regex=False,
                )
            )
            .any(axis=1)
        ]
    st.caption(
        f"{len(filtered):,} of {len(queue):,} parts shown. Select a row for "
        "calculation evidence, impact, movements, P‑VIN controls and audit history."
    )
    if filtered.empty:
        st.success("No parts match this queue and filter combination.")
        return
    compact_columns = [
        "Severity",
        "Part No.",
        "Part Name",
        "Buyer",
        "Supplier",
        "Physical Stock",
        "Required Qty",
        "Operational Shortage",
        "Required By",
        "Action Status",
    ]
    compact = filtered[compact_columns].rename(
        columns={"Required Qty": "Supplier Required Qty"}
    )
    numeric_compact_columns = [
        "Physical Stock",
        "Supplier Required Qty",
        "Operational Shortage",
    ]
    for column in numeric_compact_columns:
        compact[column] = pd.to_numeric(
            compact[column],
            errors="coerce",
        )
    selection = st.dataframe(
        compact,
        width="stretch",
        hide_index=True,
        height=min(520, 42 + len(compact.head(14)) * 35),
        on_select="rerun",
        selection_mode="single-row",
        key=f"stock_health_table_{normalize_column_name(queue_name)}",
    )
    selected_rows = (
        selection.selection.rows
        if hasattr(selection, "selection")
        else selection.get("selection", {}).get("rows", [])
    )
    with st.expander("View all parts"):
        all_parts_table = work[compact_columns].rename(
            columns={"Required Qty": "Supplier Required Qty"}
        )
        for column in numeric_compact_columns:
            all_parts_table[column] = pd.to_numeric(
                all_parts_table[column],
                errors="coerce",
            )
        st.dataframe(
            all_parts_table,
            width="stretch",
            hide_index=True,
            height=460,
        )
    if not selected_rows:
        st.info("Select one exception above to open its structured evidence panel.")
        return
    selected = filtered.iloc[selected_rows[0]]
    st.subheader(
        "Part evidence",
        help="Structured evidence and action context for the selected stock-health item.",
    )
    (
        calculation_tab,
        impact_tab,
        movement_tab,
        pvin_tab,
        supplier_tab,
        audit_tab,
    ) = st.tabs(
        [
            "Calculation",
            "Production impact",
            "Movements",
            "P‑VIN",
            "Supplier commitment",
            "Recommendation & audit",
        ]
    )
    with calculation_tab:
        evidence = pd.DataFrame(
            [
                ("Planned Part Consumption", selected["Planned Part Consumption"]),
                ("Consumed So Far", selected["Consumed So Far"]),
                ("Remaining Part Need", selected["Remaining Part Need"]),
                ("System Stock", selected["System Stock"]),
                ("Physical Stock", selected["Physical Stock"]),
                ("Supplier Required Qty", selected["Required Qty"]),
                ("Operational Shortage", selected["Operational Shortage"]),
            ],
            columns=["Stage", "Result"],
        )
        st.dataframe(evidence, width="stretch", hide_index=True)
    with impact_tab:
        variant_map = build_part_variant_map(
            sources.get("exploded_bom", pd.DataFrame()),
            sources.get("sku_map", pd.DataFrame()),
        )
        affected = variant_map.get(
            stock_part_key(selected["Part No."]),
            "",
        )
        daily_target = float(diagnostics.get("daily_target", 0))
        part_per_vehicle = (
            float(selected["Planned Part Consumption"]) / daily_target
            if daily_target > 0
            else 0
        )
        vehicle_risk = (
            int(float(selected["Operational Shortage"]) / part_per_vehicle)
            if part_per_vehicle > 0
            else 0
        )
        st.write(
            f"**Affected variants:** {affected or 'Variant mapping unavailable'}  \n"
            f"**Estimated vehicles exposed:** {vehicle_risk:,}  \n"
            f"**Required by:** {clean_text(selected['Required By']) or 'Not within the rolling horizon'}"
        )
    with movement_tab:
        movement_evidence = pd.DataFrame(
            [
                ("Today's OS", selected["Today's OS"]),
                ("Parts Inwarded", selected["Parts Inwarded"]),
                ("Production Outwarded", selected["Production Outwarded"]),
                ("Other Outwarded", selected["Other Outwarded"]),
                ("Parts Outwarded", selected["Parts Outwarded"]),
                ("Tomorrow's OS", selected["Tomorrow's OS"]),
            ],
            columns=["Movement", "Quantity"],
        )
        st.dataframe(movement_evidence, width="stretch", hide_index=True)
    with pvin_tab:
        pvin_evidence = pd.DataFrame(
            [
                ("Generated-PVIN consumption", selected["Generated Consumption"]),
                ("Produced-PVIN consumption", selected["Produced Consumption"]),
                ("COGI Qty", selected["COGI Qty"]),
                ("Stock Delta", selected["Stock Delta"]),
                ("Expected Delta", selected["Expected Delta"]),
                ("Unexplained Delta", selected["Unexplained Delta"]),
                ("Delta Flag", selected["Delta Flag"]),
            ],
            columns=["Control", "Result"],
        )
        st.dataframe(pvin_evidence, width="stretch", hide_index=True)
    with supplier_tab:
        st.write(
            f"**Supplier:** {clean_text(selected['Supplier']) or 'Unmapped'}  \n"
            f"**Buyer:** {clean_text(selected['Buyer']) or 'Unmapped'}  \n"
            f"**Action status:** {clean_text(selected['Action Status']) or 'Not started'}  \n"
            f"**Required by:** {clean_text(selected['Required By']) or 'Unavailable'}"
        )
        st.caption(
            "Open Action Centre to record expected quantity, ETA, follow-up and notes."
        )
    with audit_tab:
        part_cases = control_cases[
            control_cases["Part No."].eq(str(selected["Part No."]))
        ]
        if part_cases.empty:
            st.success("No active unexplained-delta case exists for this part.")
        else:
            st.dataframe(
                part_cases,
                width="stretch",
                hide_index=True,
            )
        recommendation = (
            "Recount and review missing postings."
            if selected["Delta Flag"] == "Review"
            else "Expedite supplier confirmation and protect the required-by date."
            if float(selected["Operational Shortage"]) > 0
            else "No immediate stock action is required."
        )
        st.info(f"**Agent recommendation:** {recommendation}")


def render_requirements_workspace() -> None:
    requirement_mode = st.radio(
        "Requirement view",
        ["Shortage requirements", "Potential excess"],
        horizontal=True,
        key="requirements_mode",
        help="Switch between supply required to protect production and possible overstock.",
    )
    if requirement_mode == "Potential excess":
        render_excess_prevention_agent()
        return
    inventory, sources, diagnostics = load_inventory_workspace_snapshot()
    st.header(
        "Requirements",
        help=(
            "Part requirements for today, the rolling seven-day plan and the "
            "remaining month, separated from supplier transaction controls."
        ),
    )
    if diagnostics.get("error") or inventory.empty:
        st.warning(
            str(
                diagnostics.get(
                    "error",
                    "No inventory snapshot is available. Refresh all sources once.",
                )
            )
        )
        return
    views, meta = build_rm_planning_views(inventory, sources)
    if not views:
        st.warning(str(meta.get("error", "No requirement view could be built.")))
        return
    horizon = st.radio(
        "Planning horizon",
        list(views),
        horizontal=True,
        key="requirements_horizon",
    )
    queue = views[horizon].copy()
    metrics = st.columns(4)
    with metrics[0]:
        render_metric("Parts requiring supply", f"{len(queue):,}", "warn")
    with metrics[1]:
        render_metric(
            "Critical today",
            f"{int(queue['Severity'].eq('Critical').sum()):,}",
            "bad",
        )
    with metrics[2]:
        render_metric(
            "Supplier required qty",
            display_qty(numeric(queue["RM Shortage"]).sum()),
            "warn",
        )
    with metrics[3]:
        render_metric(
            "Stock-data gaps",
            f"{int(meta.get('missing_stock_count', 0)):,}",
            "neutral",
        )
    if queue.empty:
        st.success(f"No supplier requirement exists for {horizon.lower()}.")
        return
    filters = st.columns([1.5, 1, 1])
    with filters[0]:
        search = st.text_input(
            "Search part",
            placeholder="part number, part name, or supplier",
            key="requirements_search",
        )
    buyers = sorted(
        queue["Buyer"].replace("", pd.NA).dropna().unique().tolist()
    )
    with filters[1]:
        buyer = st.selectbox(
            "Buyer",
            ["All buyers"] + buyers,
            key="requirements_buyer",
        )
    supplier_source = queue
    if buyer != "All buyers":
        supplier_source = supplier_source[supplier_source["Buyer"].eq(buyer)]
    suppliers = sorted(
        supplier_source["Supplier"].replace("", pd.NA).dropna().unique().tolist()
    )
    supplier_key = re.sub(r"[^a-z0-9]+", "_", buyer.lower()).strip("_")
    with filters[2]:
        supplier = st.selectbox(
            "Supplier",
            ["All suppliers"] + suppliers,
            key=f"requirements_supplier_{supplier_key}",
        )
    filtered = queue.copy()
    if buyer != "All buyers":
        filtered = filtered[filtered["Buyer"].eq(buyer)]
    if supplier != "All suppliers":
        filtered = filtered[filtered["Supplier"].eq(supplier)]
    if search.strip():
        term = search.strip()
        filtered = filtered[
            filtered[["Part No.", "Part Name", "Supplier"]]
            .astype(str)
            .apply(
                lambda column: column.str.contains(
                    term,
                    case=False,
                    na=False,
                    regex=False,
                )
            )
            .any(axis=1)
        ]
    table = filtered[
        [
            "Severity",
            "Part No.",
            "Part Name",
            "Buyer",
            "Supplier",
            "System Stock",
            "Physical Stock",
            "RM Shortage",
            "Required By",
        ]
    ].rename(columns={"RM Shortage": "Supplier Required Qty"})
    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        height=520,
    )
    st.caption(
        "Open Action Centre to assign supplier commitments or generate a PPC recovery response."
    )


def render_action_centre() -> None:
    action_mode = st.radio(
        "Action workspace",
        ["Buyer work queues", "Supplier & PPC actions"],
        horizontal=True,
        key="action_centre_mode",
    )
    if action_mode == "Buyer work queues":
        render_buyer_command_centre()
    else:
        render_rm_planning_agent(show_refresh=False)


def build_movement_reconciliation_queue(
    inventory: pd.DataFrame,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for _, row in inventory[
        inventory.get("Delta Flag", pd.Series("", index=inventory.index)).eq(
            "Review"
        )
    ].iterrows():
        records.append(
            {
                "Issue": "Unexplained stock delta",
                "Part No.": row.get("Part No.", ""),
                "Reference": "",
                "Quantity": row.get("Unexplained Delta", ""),
                "Evidence": "Physical vs System after expected P‑VIN timing and COGI",
                "Recommended Action": "Recount and review missing system/physical postings.",
            }
        )
    for _, row in inventory[
        numeric(inventory.get("COGI Qty", pd.Series(index=inventory.index))).gt(0)
    ].iterrows():
        records.append(
            {
                "Issue": "COGI posting",
                "Part No.": row.get("Part No.", ""),
                "Reference": "",
                "Quantity": row.get("COGI Qty", ""),
                "Evidence": "Generated consumption exceeded postable System Stock",
                "Recommended Action": "Resolve the failed system posting separately from physical shortage.",
            }
        )
    if INWARDING_SNAPSHOT_PATH.exists():
        inwarding = pd.read_csv(
            INWARDING_SNAPSHOT_PATH,
            dtype=str,
        ).fillna("")
        invoice = numeric(
            inwarding.get("Invoice Qty", pd.Series(index=inwarding.index))
        )
        receipt = numeric(
            inwarding.get("Receipt Qty", pd.Series(index=inwarding.index))
        )
        differences = inwarding[invoice.ne(receipt)].copy()
        for index, row in differences.head(500).iterrows():
            records.append(
                {
                    "Issue": "Invoice vs receipt",
                    "Part No.": row.get("Part Number", ""),
                    "Reference": row.get("Gate Entry No", ""),
                    "Quantity": float(invoice.loc[index] - receipt.loc[index]),
                    "Evidence": (
                        f"Invoice {display_qty(invoice.loc[index])} vs "
                        f"receipt {display_qty(receipt.loc[index])}"
                    ),
                    "Recommended Action": "Verify gate-entry receipt and supplier invoice evidence.",
                }
            )
        duplicate_columns = [
            column
            for column in ["Gate Entry No", "Part Number", "Invoice Number"]
            if column in inwarding
        ]
        if duplicate_columns:
            duplicates = inwarding[
                inwarding.duplicated(duplicate_columns, keep=False)
            ]
            for _, row in duplicates.head(200).iterrows():
                records.append(
                    {
                        "Issue": "Possible duplicate inwarding",
                        "Part No.": row.get("Part Number", ""),
                        "Reference": row.get("Gate Entry No", ""),
                        "Quantity": row.get("Invoice Qty", ""),
                        "Evidence": "Repeated gate-entry/part/invoice key",
                        "Recommended Action": "Verify whether the repeated source rows are legitimate.",
                    }
                )
    return pd.DataFrame(
        records,
        columns=[
            "Issue",
            "Part No.",
            "Reference",
            "Quantity",
            "Evidence",
            "Recommended Action",
        ],
    )


def render_movement_reconciliation_agent() -> None:
    inventory, _, diagnostics = load_inventory_workspace_snapshot()
    st.header(
        "Movement Reconciliation Agent",
        help=(
            "Reconciles inwarding controls, P‑VIN stock timing, COGI and possible "
            "duplicate movements into one evidence queue."
        ),
    )
    if diagnostics.get("error") or inventory.empty:
        st.warning(str(diagnostics.get("error", "No inventory snapshot is available.")))
        return
    queue = build_movement_reconciliation_queue(inventory)
    if queue.empty:
        st.success("No movement-reconciliation exceptions are present.")
        return
    counts = queue["Issue"].value_counts()
    metrics = st.columns(4)
    metric_labels = [
        "Unexplained stock delta",
        "COGI posting",
        "Invoice vs receipt",
        "Possible duplicate inwarding",
    ]
    for column, label in zip(metrics, metric_labels):
        with column:
            render_metric(label, f"{int(counts.get(label, 0)):,}", "warn")
    issue = st.selectbox(
        "Issue type",
        ["All issues"] + counts.index.tolist(),
        key="movement_reconciliation_issue",
    )
    filtered = queue if issue == "All issues" else queue[queue["Issue"].eq(issue)]
    st.dataframe(
        filtered,
        width="stretch",
        hide_index=True,
        height=520,
    )


def render_master_data_agent() -> None:
    inventory, _, diagnostics = load_inventory_workspace_snapshot()
    st.header(
        "Master Data Agent",
        help="Finds ownership, stock-master, part-number and description problems.",
    )
    if diagnostics.get("error") or inventory.empty:
        st.warning(str(diagnostics.get("error", "No inventory snapshot is available.")))
        return
    records: list[dict[str, object]] = []
    for _, row in inventory.iterrows():
        issues: list[tuple[str, str]] = []
        if clean_text(row.get("Buyer", "")) in {"", "Unmapped buyer"}:
            issues.append(
                (
                    "Buyer unmapped",
                    "Map the part first, then use supplier ownership as fallback.",
                )
            )
        if not clean_text(row.get("Supplier", "")):
            issues.append(
                ("Supplier unmapped", "Add the part-to-supplier master mapping.")
            )
        part_name = clean_text(row.get("Part Name", ""))
        if not part_name or "#REF!" in part_name.upper():
            issues.append(
                ("Invalid part description", "Correct the source master-data description.")
            )
        stock_match = clean_text(row.get("SCM Stock Match", ""))
        if stock_match and stock_match != "Exact SCM match":
            issues.append(
                (
                    stock_match,
                    "Verify the exact part revision against SCM Summary before using stock.",
                )
            )
        for issue, action in issues:
            records.append(
                {
                    "Issue": issue,
                    "Part No.": row.get("Part No.", ""),
                    "Part Name": part_name,
                    "Buyer": row.get("Buyer", ""),
                    "Supplier": row.get("Supplier", ""),
                    "Recommended Action": action,
                }
            )
    queue = pd.DataFrame(
        records,
        columns=[
            "Issue",
            "Part No.",
            "Part Name",
            "Buyer",
            "Supplier",
            "Recommended Action",
        ],
    )
    if queue.empty:
        st.success("No master-data issues are present in the current planned-part scope.")
        return
    counts = queue["Issue"].value_counts()
    st.caption(
        " · ".join(f"{issue}: {count:,}" for issue, count in counts.items())
    )
    issue = st.selectbox(
        "Master-data queue",
        ["All issues"] + counts.index.tolist(),
        key="master_data_issue",
    )
    filtered = queue if issue == "All issues" else queue[queue["Issue"].eq(issue)]
    st.dataframe(
        filtered,
        width="stretch",
        hide_index=True,
        height=520,
    )
    st.info(
        "Recommendations require human confirmation. Mapping edits and a mapping-"
        "change audit trail will be enabled when the authoritative master-write "
        "workflow is defined."
    )


def render_inventory_correction_log() -> None:
    inventory, _, diagnostics = load_inventory_workspace_snapshot()
    st.header(
        "Stock Correction Requests",
        help=(
            "Records proposed stock corrections with reason, requester, approver "
            "and decision history without silently overwriting source-controlled stock."
        ),
    )
    if diagnostics.get("error") or inventory.empty:
        st.warning(str(diagnostics.get("error", "No inventory snapshot is available.")))
        return
    inventory = inventory.drop_duplicates("Part No.", keep="first").copy()
    inventory["_label"] = (
        inventory["Part No."].astype(str)
        + " · "
        + inventory["Part Name"].astype(str)
    )
    with st.form("inventory_correction_request_form"):
        selected_label = st.selectbox(
            "Part",
            inventory["_label"].tolist(),
        )
        selected = inventory[
            inventory["_label"].eq(selected_label)
        ].iloc[0]
        stock_field = st.selectbox(
            "Stock field",
            ["Today's OS", "Physical Stock", "System Stock"],
            help=(
                "Physical and System Stock are calculated fields. Their requests "
                "are logged for investigation and are not directly overwritten."
            ),
        )
        current_value = pd.to_numeric(
            pd.Series([selected.get(stock_field, "")]),
            errors="coerce",
        ).iloc[0]
        proposed_value = st.number_input(
            "Proposed value",
            min_value=0.0,
            value=float(current_value) if pd.notna(current_value) else 0.0,
            step=1.0,
        )
        reason = st.text_area(
            "Reason",
            placeholder="State the count evidence, posting problem, or correction basis.",
        )
        identity_columns = st.columns(2)
        with identity_columns[0]:
            requested_by = st.text_input(
                "Requested by",
                placeholder="Name or Google email",
            )
        with identity_columns[1]:
            approver = st.text_input(
                "Approver",
                placeholder="Approver name or email",
            )
        submitted = st.form_submit_button(
            "Submit correction request",
            type="primary",
        )
    if submitted:
        missing = [
            label
            for label, value in [
                ("Reason", reason.strip()),
                ("Requested by", requested_by.strip()),
                ("Approver", approver.strip()),
            ]
            if not value
        ]
        if missing:
            st.error("Complete: " + ", ".join(missing) + ".")
        else:
            now_label = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            digest = hashlib.sha1(
                (
                    f"{selected['Part No.']}|{stock_field}|{now_label}|"
                    f"{requested_by}"
                ).encode("utf-8")
            ).hexdigest()[:10]
            request = {
                "Request ID": f"COR-{digest.upper()}",
                "Part No.": selected["Part No."],
                "Part Name": selected["Part Name"],
                "Stock Field": stock_field,
                "Current Value": (
                    float(current_value) if pd.notna(current_value) else ""
                ),
                "Proposed Value": proposed_value,
                "Reason": reason.strip(),
                "Requested By": requested_by.strip(),
                "Approver": approver.strip(),
                "Status": "Pending approval",
                "Requested At": now_label,
                "Decision At": "",
            }
            corrections = pd.concat(
                [
                    load_inventory_corrections(),
                    pd.DataFrame([request]),
                ],
                ignore_index=True,
            )
            save_inventory_corrections(corrections)
            st.success(
                "Correction request logged. No stock value was overwritten."
            )
            st.rerun()

    corrections = load_inventory_corrections()
    st.subheader(
        "Approval and audit log",
        help="Only Approver and Status are editable; original request evidence remains retained.",
    )
    if corrections.empty:
        st.info("No stock-correction request has been logged yet.")
        return
    edited = st.data_editor(
        corrections,
        width="stretch",
        hide_index=True,
        disabled=[
            column
            for column in INVENTORY_CORRECTION_COLUMNS
            if column not in {"Approver", "Status"}
        ],
        column_config={
            "Status": st.column_config.SelectboxColumn(
                options=[
                    "Pending approval",
                    "Approved",
                    "Rejected",
                    "Applied externally",
                ],
                required=True,
            ),
        },
        key="inventory_correction_audit_editor",
    )
    if st.button("Save correction decisions", type="primary"):
        original_status = corrections.set_index("Request ID")["Status"]
        changed = edited["Status"].ne(
            edited["Request ID"].map(original_status).fillna("")
        )
        edited.loc[changed, "Decision At"] = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        save_inventory_corrections(edited)
        st.success("Correction decisions saved to the audit log.")
        st.rerun()
    st.warning(
        "Approval records the decision only. Applying corrections to Google/ERP "
        "requires the authoritative write-back workflow and role permissions."
    )


def render_audit_evidence_workspace() -> None:
    audit_mode = st.radio(
        "Audit workspace",
        [
            "Data readiness",
            "Movement reconciliation",
            "Master data",
            "Correction requests",
            "Calculation evidence",
        ],
        horizontal=True,
        key="audit_evidence_mode",
    )
    if audit_mode == "Data readiness":
        render_inventory_data_audit()
    elif audit_mode == "Movement reconciliation":
        render_movement_reconciliation_agent()
    elif audit_mode == "Master data":
        render_master_data_agent()
    elif audit_mode == "Correction requests":
        render_inventory_correction_log()
    else:
        render_part_inventory(show_refresh=False)


def render_excess_prevention_agent() -> None:
    inventory, sources, diagnostics = load_inventory_workspace_snapshot()
    st.header(
        "Excess Prevention Agent",
        help=(
            "Screens physical stock against the selected planning horizon and "
            "creates a buyer-owned review queue for possible overstock."
        ),
    )
    st.write(
        "This Phase‑1 agent identifies **potential excess** using available stock "
        "and forecast demand. It does not cancel or reduce supply automatically."
    )
    if diagnostics.get("error") or inventory.empty:
        st.warning(
            str(
                diagnostics.get(
                    "error",
                    "No inventory snapshot is available. Refresh all sources once.",
                )
            )
        )
        return

    horizon = st.radio(
        "Planning horizon",
        ["Rolling 7 Days", "Remaining Month"],
        horizontal=True,
        key="excess_agent_horizon",
        help="Physical Stock is compared with projected part demand through this horizon.",
    )
    excess, meta = build_potential_excess_view(inventory, sources, horizon)
    no_demand_count = int(
        excess.get("Excess Signal", pd.Series(dtype=str))
        .eq("No demand in horizon")
        .sum()
    )
    high_coverage_count = int(
        excess.get("Excess Signal", pd.Series(dtype=str))
        .eq("More than 2× horizon demand")
        .sum()
    )
    metrics = st.columns(4)
    with metrics[0]:
        render_metric("Potential excess parts", f"{len(excess):,}", "warn")
    with metrics[1]:
        render_metric("No demand in horizon", f"{no_demand_count:,}", "bad")
    with metrics[2]:
        render_metric("More than 2× demand", f"{high_coverage_count:,}", "warn")
    with metrics[3]:
        render_metric(
            "Stock-data gaps",
            f"{int(meta.get('stock_data_gaps', 0)):,}",
            "neutral",
        )

    st.warning(
        "Confidence: **Indicative only**. Open purchase orders, confirmed incoming "
        "supply, safety stock, lead time, MOQ, shelf life and part value are not "
        "available, so every recommendation requires buyer validation."
    )
    if excess.empty:
        st.success("No potential excess was found for this horizon.")
        return

    buyer_options = sorted(
        excess["Buyer"].replace("", pd.NA).dropna().unique().tolist()
    )
    filters = st.columns([1.6, 1, 1, 1])
    with filters[0]:
        search = st.text_input(
            "Search part",
            placeholder="part number, part name, or supplier",
            key="excess_agent_search",
        )
    with filters[1]:
        buyer = st.selectbox(
            "Buyer",
            ["All buyers"] + buyer_options,
            key="excess_agent_buyer",
        )
    supplier_source = excess
    if buyer != "All buyers":
        supplier_source = supplier_source[supplier_source["Buyer"].eq(buyer)]
    supplier_options = sorted(
        supplier_source["Supplier"].replace("", pd.NA).dropna().unique().tolist()
    )
    supplier_key = re.sub(r"[^a-z0-9]+", "_", buyer.lower()).strip("_")
    with filters[2]:
        supplier = st.selectbox(
            "Supplier",
            ["All suppliers"] + supplier_options,
            key=f"excess_agent_supplier_{supplier_key}",
        )
    with filters[3]:
        signal = st.selectbox(
            "Signal",
            ["All signals"] + sorted(excess["Excess Signal"].unique().tolist()),
            key="excess_agent_signal",
        )

    filtered = excess.copy()
    if buyer != "All buyers":
        filtered = filtered[filtered["Buyer"].eq(buyer)]
    if supplier != "All suppliers":
        filtered = filtered[filtered["Supplier"].eq(supplier)]
    if signal != "All signals":
        filtered = filtered[filtered["Excess Signal"].eq(signal)]
    if search.strip():
        term = search.strip()
        filtered = filtered[
            filtered[["Part No.", "Part Name", "Supplier"]]
            .astype(str)
            .apply(
                lambda column: column.str.contains(
                    term,
                    case=False,
                    na=False,
                    regex=False,
                )
            )
            .any(axis=1)
        ]

    st.caption(
        f"{len(filtered):,} of {len(excess):,} potential excess signals shown. "
        "Select a row to open the recommended review action."
    )
    queue_columns = [
        "Part No.",
        "Part Name",
        "Buyer",
        "Supplier",
        "Physical Stock",
        "Horizon Demand",
        "Potential Excess Qty",
        "Coverage Multiple",
        "Excess Signal",
    ]
    selection = st.dataframe(
        filtered[queue_columns],
        width="stretch",
        hide_index=True,
        height=min(520, 42 + len(filtered.head(100)) * 35),
        on_select="rerun",
        selection_mode="single-row",
        key=f"excess_agent_queue_{normalize_column_name(horizon)}",
        column_config={
            "Coverage Multiple": st.column_config.NumberColumn(format="%.1f×"),
        },
    )
    selected_rows = (
        selection.selection.rows
        if hasattr(selection, "selection")
        else selection.get("selection", {}).get("rows", [])
    )
    if not selected_rows:
        st.info("Select a row to review the signal and recommended buyer action.")
        st.download_button(
            "Download potential excess queue",
            filtered.to_csv(index=False),
            file_name=f"potential_excess_{normalize_column_name(horizon)}.csv",
            mime="text/csv",
        )
        return

    selected = filtered.iloc[selected_rows[0]]
    st.subheader(
        "Agent review",
        help="Evidence and the next safe action for the selected potential excess signal.",
    )
    evidence = st.columns(4)
    with evidence[0]:
        render_metric("Physical stock", display_qty(selected["Physical Stock"]), "neutral")
    with evidence[1]:
        render_metric("Horizon demand", display_qty(selected["Horizon Demand"]), "neutral")
    with evidence[2]:
        render_metric("Potential excess", display_qty(selected["Potential Excess Qty"]), "warn")
    with evidence[3]:
        render_metric("Owner", clean_text(selected["Buyer"]) or "Unmapped", "neutral")
    st.info(
        "**Recommended review**\n\n"
        f"- {clean_text(selected['Recommended Action'])}\n"
        f"- Confirm open POs, incoming quantity and safety stock with "
        f"**{clean_text(selected['Buyer']) or 'the responsible buyer'}**.\n"
        "- Record a supply change only after the missing inputs are validated."
    )


def render_part_inventory(show_refresh: bool = True) -> None:
    st.header(
        "Stock Control",
        help=(
            "Calculates part-level demand for the selected production day, "
            "compares it with current physical stock, and identifies shortages."
        ),
    )
    st.write(
        "Part requirement for the selected production day. Actual production means "
        "production completed **so far**, while Physical Stock means stock available now."
    )

    if show_refresh:
        credentials = load_google_credentials()
        refresh_col, note_col = st.columns([1, 4])
        with refresh_col:
            refresh_clicked = st.button(
                "Refresh production plan",
                type="primary",
                disabled=credentials is None,
                help="Pulls a new saved copy of the production-plan, actual-production, and BOM source tabs.",
            )
        with note_col:
            st.caption(
                "The page keeps showing the previous saved source copies until Refresh is clicked."
            )
        if credentials is None:
            st.info("Connect Google in Setup once to refresh. Existing saved data remains available.")
        if refresh_clicked:
            try:
                with st.spinner("Refreshing daily plan, production so far, variant mix, and BOM..."):
                    for source in SOURCE_SHEETS.values():
                        source_df, _ = load_google_sheet_oauth(source["url"], credentials)
                        save_source_cache(source["cache"], source_df)
                st.success("Production planning data refreshed.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not refresh production planning data: {exc}")

    sources: dict[str, pd.DataFrame] = {}
    missing_sources = [
        source["cache"] for source in SOURCE_SHEETS.values() if not source["cache"].exists()
    ]
    if missing_sources:
        st.warning(
            "Planning data has not been saved yet. Click Refresh production plan once."
        )
        df = build_inventory_status(load_table("part_inventory"))
        diagnostics: dict[str, object] = {}
    else:
        sources = {
            key: load_source_cache(source["cache"])
            for key, source in SOURCE_SHEETS.items()
        }
        df, diagnostics = build_part_inventory_plan(
            load_table("part_inventory"),
            sources,
            delta_threshold=float(
                st.session_state.get("pvin_delta_threshold", 10.0)
            ),
        )
        if diagnostics.get("error"):
            st.warning(str(diagnostics["error"]))

    cols = st.columns(6)

    if diagnostics:
        plan_date = diagnostics.get("fallback_mix_date")
        message = (
            f"Daily target: {display_qty(diagnostics.get('daily_target', 0))} vehicles · "
            f"Total production so far: "
            f"{display_qty(diagnostics.get('produced_target', 0))} vehicles."
        )
        if pd.notna(plan_date):
            message += (
                f" Current-day colour mix was unavailable, so the latest saved mix "
                f"from {pd.Timestamp(plan_date):%d %b %Y} was used to distribute the model plan."
            )
        st.info(message)
        if diagnostics.get("missing_models"):
            st.warning(
                "No usable variant/colour mix was found for: "
                + ", ".join(diagnostics["missing_models"])
                + ". Their parts are excluded until the source mapping is available."
            )
        scm_mapped = int(diagnostics.get("scm_stock_rows_mapped", 0))
        if scm_mapped:
            stock_label = clean_text(diagnostics.get("scm_stock_label", ""))
            st.success(
                f"Today's OS synced for {scm_mapped:,} parts from Summary → "
                f"{stock_label or 'System Opening Stock'}."
            )

    if diagnostics and sources:
        st.subheader(
            "PVIN Stock Controls",
            help=(
                "Enter variant-level generated P-VIN totals. Produced P-VIN is fetched "
                "only from the explicit P-VIN column in Production Plan Breakup. "
                "Total Production/Visibility is kept separate. Generated P-VINs "
                "reduce System Stock; produced P-VINs reduce Physical Stock."
            ),
        )
        pvin_plan_date = pd.to_datetime(
            df.get("Plan Date", pd.Series(dtype=str)),
            errors="coerce",
        ).max()
        if pd.notna(pvin_plan_date):
            pvin_template = pvin_input_template(
                sources,
                pd.Timestamp(pvin_plan_date).normalize(),
            )
            with st.expander(
                "Enter or review variant-wise P-VIN figures",
                expanded=bool(diagnostics.get("pvin_inputs_active")),
            ):
                st.caption(
                    "Produced P-VIN comes only from Production Plan Breakup → P-VIN. "
                    "Visibility is total production and is not copied into this field. "
                    "Enter only Generated P-VIN until its source is integrated."
                )
                edited_pvin = st.data_editor(
                    pvin_template,
                    use_container_width=True,
                    hide_index=True,
                    disabled=["Plan Date", "Variant", "Produced P-VIN"],
                    key="pvin_variant_inputs_editor",
                    column_config={
                        "Generated P-VIN": st.column_config.NumberColumn(
                            min_value=0,
                            step=1,
                            help="Reduces System Stock through the variant BOM.",
                        ),
                        "Produced P-VIN": st.column_config.NumberColumn(
                            min_value=0,
                            step=1,
                            help=(
                                "Source-controlled from the explicit P-VIN column in "
                                "Production Plan Breakup. It does not represent total "
                                "production. Reduces Physical Stock through the BOM."
                            ),
                        ),
                    },
                )
                control_columns = st.columns([1, 1.2, 3.8])
                with control_columns[0]:
                    if st.button(
                        "Save P-VIN figures",
                        type="primary",
                        key="save_pvin_variant_inputs",
                    ):
                        all_inputs = load_pvin_inputs()
                        date_label = pd.Timestamp(pvin_plan_date).strftime(
                            "%Y-%m-%d"
                        )
                        all_inputs = all_inputs[
                            ~all_inputs["Plan Date"].eq(date_label)
                        ]
                        save_pvin_inputs(
                            pd.concat(
                                [all_inputs, edited_pvin],
                                ignore_index=True,
                            )
                        )
                        st.success("P-VIN figures saved and stock positions recalculated.")
                        st.rerun()
                with control_columns[1]:
                    st.number_input(
                        "Delta alert threshold",
                        min_value=0.0,
                        value=float(
                            st.session_state.get(
                                "pvin_delta_threshold",
                                10.0,
                            )
                        ),
                        step=1.0,
                        key="pvin_delta_threshold",
                        help=(
                            "Flag a part when its absolute unexplained System-versus-"
                            "Physical delta exceeds this quantity."
                        ),
                    )
                with control_columns[2]:
                    generated_total = display_qty(
                        diagnostics.get("generated_pvin_total", 0)
                    )
                    produced_total = display_qty(
                        diagnostics.get("produced_pvin_total", 0)
                    )
                    total_production = display_qty(
                        diagnostics.get("produced_target", 0)
                    )
                    st.info(
                        f"PVIN controls: **{generated_total} generated P-VIN** · "
                        f"**{produced_total} produced P-VIN**. Separately, total "
                        f"production is **{total_production} vehicles**. System Stock "
                        "is floored at zero; excess generated consumption moves to COGI."
                    )
                    if not diagnostics.get("produced_pvin_source_available"):
                        st.warning(
                            "Produced P-VIN is unavailable in the production source. "
                            "No value has been inferred from total production."
                        )
                if diagnostics.get("pvin_missing_variants"):
                    st.warning(
                        "No usable FG/colour mix was found for: "
                        + ", ".join(diagnostics["pvin_missing_variants"])
                    )
        else:
            st.info("A production-plan date is required before entering P-VIN figures.")

    st.subheader(
        "Part Requirement Table",
        help=(
            "Search or filter the complete part list, review ownership and stock "
            "health, and update permitted stock fields."
        ),
    )
    st.caption(
        "Supplier Required Qty uses System Stock. Operational Shortage and stock "
        "health use Physical Stock. The two stock positions are intentionally independent."
    )
    filter_columns = st.columns([1.8, 1.1, 1.3, 1.1, 1.1])
    with filter_columns[0]:
        search = st.text_input(
            "Search part",
            placeholder="part number, part name, or supplier",
            key="part_inventory_search",
        )
    buyers = sorted(
        df.get("Buyer", pd.Series(dtype=str))
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    with filter_columns[1]:
        buyer_filter = st.selectbox(
            "Buyer",
            ["All buyers"] + buyers,
            key="part_inventory_buyer",
        )
    supplier_source = df
    if buyer_filter != "All buyers":
        supplier_source = supplier_source[
            supplier_source["Buyer"].eq(buyer_filter)
        ]
    suppliers = sorted(
        supplier_source.get("Supplier", pd.Series(dtype=str))
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    supplier_options = ["All suppliers"] + suppliers
    if st.session_state.get("part_inventory_supplier") not in supplier_options:
        st.session_state["part_inventory_supplier"] = "All suppliers"
    with filter_columns[2]:
        supplier_filter = st.selectbox(
            "Supplier",
            supplier_options,
            key="part_inventory_supplier",
        )
    stock_health_options = [
        "All stock health",
        "Stock data missing",
        "Healthy",
        "Below required",
        "Critical",
    ]
    with filter_columns[3]:
        stock_health_filter = st.selectbox(
            "Stock health",
            stock_health_options,
            key="part_inventory_stock_health",
            help=(
                "Show parts by their current stock position. Critical means "
                "required quantity is positive and no usable physical stock is available."
            ),
        )
    with filter_columns[4]:
        delta_filter = st.selectbox(
            "Stock delta",
            ["All delta states", "Review", "Within expected"],
            key="part_inventory_delta_filter",
            help=(
                "Review shows parts whose unexplained Physical-versus-System "
                "difference exceeds the selected alert threshold."
            ),
        )
    filtered = df.copy()
    if search.strip():
        term = search.strip().lower()
        searchable = ["Part No.", "Part Name", "Supplier"]
        filtered = filtered[
            filtered[searchable]
            .astype(str)
            .apply(lambda column: column.str.lower().str.contains(term, na=False))
            .any(axis=1)
        ]
    if buyer_filter != "All buyers":
        filtered = filtered[filtered["Buyer"].eq(buyer_filter)]
    if supplier_filter != "All suppliers":
        filtered = filtered[filtered["Supplier"].eq(supplier_filter)]
    if stock_health_filter != "All stock health":
        filtered = filtered[filtered["Status"].eq(stock_health_filter)]
    if delta_filter != "All delta states":
        filtered = filtered[filtered["Delta Flag"].eq(delta_filter)]

    stock_input_columns = [
        "Part No.",
        "Part Name",
        "Buyer",
        "Supplier",
        "Today's OS",
        "Parts Inwarded",
        "Parts Outwarded",
        "Tomorrow's OS",
        "System Stock",
        "Physical Stock",
        "COGI Qty",
        "Delta Flag",
        "Remarks",
    ]
    st.subheader(
        "1. Update current stock",
        help=(
            "Review the stock currently available for each part. System-controlled "
            "values come from SCM Summary; editable values must be saved explicitly."
        ),
    )
    scm_stock_active = int(diagnostics.get("scm_stock_rows_mapped", 0)) > 0
    if scm_stock_active:
        st.caption(
            "Today's OS comes from SCM Summary. System Stock is reduced by generated "
            "P-VINs; Physical Stock is reduced by produced P-VINs. Tomorrow's OS = "
            "Today's OS + Invoice Qty inwarded − total outwarded."
        )
    else:
        st.caption(
            "Enter today's OS where SCM stock is unavailable. Tomorrow's OS is then "
            "calculated from today's OS and the saved inward/outward movements."
        )
    st.caption(f"{len(filtered):,} of {len(df):,} parts shown.")
    edited_stock = st.data_editor(
        filtered[stock_input_columns],
        use_container_width=True,
        hide_index=True,
        disabled=(
            [
                "Part No.",
                "Part Name",
                "Buyer",
                "Supplier",
                "Today's OS",
                "Parts Inwarded",
                "Parts Outwarded",
                "Tomorrow's OS",
                "System Stock",
                "Physical Stock",
                "COGI Qty",
                "Delta Flag",
            ]
            if scm_stock_active
            else [
                "Part No.",
                "Part Name",
                "Buyer",
                "Supplier",
                "Parts Inwarded",
                "Parts Outwarded",
                "Tomorrow's OS",
                "System Stock",
                "Physical Stock",
                "COGI Qty",
                "Delta Flag",
            ]
        ),
        key=(
            "part_inventory_editor_scm"
            if scm_stock_active
            else "part_inventory_editor"
        ),
        column_config={
            "Today's OS": st.column_config.NumberColumn(
                "Today's OS",
                help="Opening-stock position for today.",
                min_value=0.0,
            ),
            "Parts Inwarded": st.column_config.NumberColumn(
                help=(
                    "Total supplier Invoice Qty into HS01 plus any recorded "
                    "CPW/HS02 and rework returns."
                ),
            ),
            "Parts Outwarded": st.column_config.NumberColumn(
                help=(
                    "Produced-PVIN BOM consumption plus recorded servicing/CPW "
                    "and rework issues."
                ),
            ),
            "Tomorrow's OS": st.column_config.NumberColumn(
                "Tomorrow's OS",
                help=(
                    "Calculated as Today's OS + Parts Inwarded − Parts Outwarded."
                ),
            ),
            "Physical Stock": st.column_config.NumberColumn(
                "Physical Stock",
                help="Today's OS minus BOM consumption from produced P-VINs.",
            ),
            "System Stock": st.column_config.NumberColumn(
                help="Today's OS minus generated-P-VIN consumption, floored at zero."
            ),
            "COGI Qty": st.column_config.NumberColumn(
                help="Generated consumption that could not be posted because System Stock reached zero."
            ),
        },
        height=330,
    )

    recalculated = filtered.set_index("Part No.", drop=False)
    stock_updates = edited_stock.set_index("Part No.", drop=False)
    for column in ["Today's OS", "Remarks"]:
        recalculated.loc[stock_updates.index, column] = stock_updates[column]
    live_today_os_raw = (
        recalculated["Today's OS"].fillna("").astype(str).str.strip()
    )
    live_today_os_available = live_today_os_raw.ne("") & pd.to_numeric(
        live_today_os_raw,
        errors="coerce",
    ).notna()
    live_today_os = pd.to_numeric(
        live_today_os_raw,
        errors="coerce",
    ).fillna(0)
    live_generated = numeric(recalculated["Generated Consumption"])
    live_produced = numeric(recalculated["Produced Consumption"])
    recalculated["System Stock"] = (
        live_today_os - live_generated
    ).clip(lower=0)
    recalculated["Physical Stock"] = live_today_os - live_produced
    recalculated["COGI Qty"] = (
        live_generated - live_today_os
    ).clip(lower=0)
    recalculated["Tomorrow's OS"] = (
        live_today_os
        + numeric(recalculated["Parts Inwarded"])
        - numeric(recalculated["Parts Outwarded"])
    )
    recalculated.loc[~live_today_os_available, "Tomorrow's OS"] = pd.NA
    live_physical_raw = recalculated["Physical Stock"].fillna("").astype(str).str.strip()
    live_stock_available = live_physical_raw.ne("") & pd.to_numeric(
        live_physical_raw,
        errors="coerce",
    ).notna()
    current_physical = pd.to_numeric(
        live_physical_raw,
        errors="coerce",
    ).fillna(0)
    current_system = numeric(recalculated["System Stock"])
    recalculated["Required Qty"] = (
        numeric(recalculated["Remaining Part Need"]) - current_system
    ).clip(lower=0).apply(lambda value: int(-(-value // 1)))
    recalculated["Operational Shortage"] = (
        numeric(recalculated["Remaining Part Need"]) - current_physical
    ).clip(lower=0).apply(lambda value: int(-(-value // 1)))
    recalculated["Stock Delta"] = current_physical - current_system
    recalculated["Expected Delta"] = (
        live_generated
        - live_produced
        - numeric(recalculated["COGI Qty"])
    )
    recalculated["Unexplained Delta"] = (
        recalculated["Stock Delta"] - recalculated["Expected Delta"]
    )
    delta_threshold = float(
        st.session_state.get("pvin_delta_threshold", 10.0)
    )
    recalculated["Delta Flag"] = "Within expected"
    recalculated.loc[
        recalculated["Unexplained Delta"].abs().gt(delta_threshold),
        "Delta Flag",
    ] = "Review"
    recalculated["Status"] = "Healthy"
    recalculated.loc[
        recalculated["Operational Shortage"].gt(0),
        "Status",
    ] = "Below required"
    recalculated.loc[
        recalculated["Operational Shortage"].gt(0) & current_physical.le(0),
        "Status",
    ] = "Critical"
    recalculated["Stock Data Status"] = "Available"
    valid_stock = live_today_os_available & live_stock_available
    recalculated.loc[~valid_stock, "Stock Data Status"] = "Missing"
    recalculated.loc[~valid_stock, "Required Qty"] = pd.NA
    recalculated.loc[~valid_stock, "Operational Shortage"] = pd.NA
    recalculated.loc[~valid_stock, "Stock Delta"] = pd.NA
    recalculated.loc[~valid_stock, "Expected Delta"] = pd.NA
    recalculated.loc[~valid_stock, "Unexplained Delta"] = pd.NA
    recalculated.loc[~valid_stock, "Delta Flag"] = "Stock data missing"
    recalculated.loc[~valid_stock, "Status"] = "Stock data missing"
    recalculated = recalculated.reset_index(drop=True)

    live_full = df.set_index("Part No.", drop=False)
    live_updates = recalculated.set_index("Part No.", drop=False)
    for column in [
        "Physical Stock",
        "Today's OS",
        "Tomorrow's OS",
        "System Stock",
        "Remarks",
        "Required Qty",
        "Operational Shortage",
        "COGI Qty",
        "Stock Delta",
        "Expected Delta",
        "Unexplained Delta",
        "Delta Flag",
        "Stock Data Status",
        "Status",
    ]:
        live_full.loc[live_updates.index, column] = live_updates[column]
    live_full = live_full.reset_index(drop=True)
    total = len(live_full)
    healthy = int(live_full["Status"].eq("Healthy").sum()) if total else 0
    below = int(live_full["Status"].eq("Below required").sum()) if total else 0
    critical = int(live_full["Status"].eq("Critical").sum()) if total else 0
    stock_missing = int(live_full["Status"].eq("Stock data missing").sum()) if total else 0
    delta_review = int(live_full["Delta Flag"].eq("Review").sum()) if total else 0
    with cols[0]:
        render_metric("Parts tracked", total, "neutral")
    with cols[1]:
        render_metric("Stock data missing", stock_missing, "warn")
    with cols[2]:
        render_metric("Healthy", healthy, "ok")
    with cols[3]:
        render_metric("Below required", below, "warn")
    with cols[4]:
        render_metric("Critical", critical, "bad")
    with cols[5]:
        render_metric("Delta review", delta_review, "warn")

    st.subheader(
        "2. Live recalculated requirement",
        help=(
            "Shows the immediate result after applying the current stock values: "
            "supplier requirement, operational shortage, COGI, stock delta, and health."
        ),
    )
    st.dataframe(
        recalculated,
        use_container_width=True,
        hide_index=True,
        height=430,
        column_config={
            "Physical Stock": st.column_config.NumberColumn(
                help="Today's OS minus produced-P-VIN BOM consumption."
            ),
            "System Stock": st.column_config.NumberColumn(
                help="Today's OS minus generated-P-VIN BOM consumption, floored at zero."
            ),
            "Required Qty": st.column_config.NumberColumn(
                "Supplier Required Qty",
                help="max(Remaining Part Need − System Stock, 0)."
            ),
            "Operational Shortage": st.column_config.NumberColumn(
                help="max(Remaining Part Need − Physical Stock, 0)."
            ),
            "Unexplained Delta": st.column_config.NumberColumn(
                help="Raw Physical-minus-System delta after removing the expected PVIN timing difference."
            ),
        },
    )

    show_calculation_trace = st.toggle(
        "Show end-to-end calculation trace",
        value=False,
        key="show_inventory_calculation_trace",
        help=(
            "Turn on only when you want to audit every source value and "
            "intermediate stock/requirement calculation for a Klassic Wheels part."
        ),
    )
    if show_calculation_trace:
        st.subheader(
            "3. End-to-end calculation trace",
            help=(
                "Select a Klassic Wheels part to see every source value, movement, "
                "intermediate calculation, and final stock/requirement result."
            ),
        )
        klassic_parts = recalculated[
            recalculated["Supplier"]
            .astype(str)
            .str.contains("klassic", case=False, na=False)
        ].copy()
        if klassic_parts.empty:
            st.info("No Klassic Wheels part is available in the current filtered view.")
        else:
            klassic_parts = klassic_parts.drop_duplicates("Part No.").copy()
            klassic_parts["_label"] = (
                klassic_parts["Part No."].astype(str)
                + " · "
                + klassic_parts["Part Name"].astype(str)
            )
            preferred_part = "2W000000019646"
            labels = klassic_parts["_label"].tolist()
            default_index = next(
                (
                    index
                    for index, label in enumerate(labels)
                    if label.startswith(preferred_part)
                ),
                0,
            )
            selected_label = st.selectbox(
                "Klassic Wheels part",
                labels,
                index=default_index,
                key="klassic_calculation_trace_part",
            )
            trace = klassic_parts[
                klassic_parts["_label"].eq(selected_label)
            ].iloc[0]

            def trace_number(column: str) -> float:
                return float(
                    pd.to_numeric(
                        pd.Series([trace.get(column, 0)]),
                        errors="coerce",
                    ).fillna(0).iloc[0]
                )

            today_os_value = trace_number("Today's OS")
            inwarded_value = trace_number("Parts Inwarded")
            production_outward_value = trace_number("Production Outwarded")
            other_outward_value = trace_number("Other Outwarded")
            outwarded_value = trace_number("Parts Outwarded")
            tomorrow_os_value = trace_number("Tomorrow's OS")
            planned_consumption_value = trace_number("Planned Part Consumption")
            consumed_so_far_value = trace_number("Consumed So Far")
            remaining_need_value = trace_number("Remaining Part Need")
            generated_consumption_value = trace_number("Generated Consumption")
            produced_consumption_value = trace_number("Produced Consumption")
            system_stock_value = trace_number("System Stock")
            physical_stock_value = trace_number("Physical Stock")
            cogi_value = trace_number("COGI Qty")
            required_qty_value = trace_number("Required Qty")
            operational_shortage_value = trace_number("Operational Shortage")

            trace_metrics = st.columns(5)
            with trace_metrics[0]:
                st.metric("Today's OS", display_qty(today_os_value))
            with trace_metrics[1]:
                st.metric("Inwarded", display_qty(inwarded_value))
            with trace_metrics[2]:
                st.metric("Outwarded", display_qty(outwarded_value))
            with trace_metrics[3]:
                st.metric("Tomorrow's OS", display_qty(tomorrow_os_value))
            with trace_metrics[4]:
                st.metric("Supplier required", display_qty(required_qty_value))

            st.markdown(
                f"""
                **Tomorrow's OS calculation**

                `{display_qty(today_os_value)} + {display_qty(inwarded_value)}
                − {display_qty(outwarded_value)} = {display_qty(tomorrow_os_value)}`
                """
            )
            calculation_ledger = pd.DataFrame(
                [
                    {
                        "Stage": "Production plan",
                        "Formula / source": "Daily vehicle target from Production Plan Breakup",
                        "Result": trace_number("Daily Production Plan"),
                    },
                    {
                    "Stage": "Total production completed",
                    "Formula / source": (
                        "Variant-wise Visibility (P-VIN + VNA + Free VIN); "
                        "not Produced P-VIN alone"
                    ),
                        "Result": trace_number("Produced So Far"),
                    },
                    {
                        "Stage": "Planned part demand",
                        "Formula / source": "Vehicle plan by variant × BOM quantity",
                        "Result": planned_consumption_value,
                    },
                    {
                        "Stage": "Consumed so far",
                        "Formula / source": "Produced vehicles by variant × BOM quantity",
                        "Result": consumed_so_far_value,
                    },
                    {
                        "Stage": "Remaining part need",
                        "Formula / source": "max(Planned part demand − Consumed so far, 0)",
                        "Result": remaining_need_value,
                    },
                    {
                        "Stage": "Supplier inwarding",
                        "Formula / source": "Sum of Invoice Qty for this date and part",
                        "Result": inwarded_value,
                    },
                    {
                        "Stage": "Production outwarding",
                        "Formula / source": "Produced P-VINs × part BOM quantity",
                        "Result": production_outward_value,
                    },
                    {
                        "Stage": "Other outwarding",
                        "Formula / source": "Servicing/CPW and rework issues recorded for the date",
                        "Result": other_outward_value,
                    },
                    {
                        "Stage": "Total outwarding",
                        "Formula / source": "Production outwarding + Other outwarding",
                        "Result": outwarded_value,
                    },
                    {
                        "Stage": "Tomorrow's OS",
                        "Formula / source": "Today's OS + Total inwarding − Total outwarding",
                        "Result": tomorrow_os_value,
                    },
                    {
                        "Stage": "System Stock",
                        "Formula / source": "max(Today's OS − Generated-PVIN consumption, 0)",
                        "Result": system_stock_value,
                    },
                    {
                        "Stage": "COGI",
                        "Formula / source": "max(Generated-PVIN consumption − Today's OS, 0)",
                        "Result": cogi_value,
                    },
                    {
                        "Stage": "Physical Stock",
                        "Formula / source": "Today's OS − Produced-PVIN consumption",
                        "Result": physical_stock_value,
                    },
                    {
                        "Stage": "Supplier Required Qty",
                        "Formula / source": "max(Remaining part need − System Stock, 0)",
                        "Result": required_qty_value,
                    },
                    {
                        "Stage": "Operational Shortage",
                        "Formula / source": "max(Remaining part need − Physical Stock, 0)",
                        "Result": operational_shortage_value,
                    },
                ]
            )
            calculation_ledger["Result"] = calculation_ledger["Result"].map(
                display_qty
            )
            st.dataframe(
                calculation_ledger,
                use_container_width=True,
                hide_index=True,
                height=565,
            )

            trace_plan_date = pd.to_datetime(
                trace.get("Plan Date", ""),
                errors="coerce",
            )
            if INWARDING_SNAPSHOT_PATH.exists() and pd.notna(trace_plan_date):
                inwarding_evidence = pd.read_csv(
                    INWARDING_SNAPSHOT_PATH,
                    dtype=str,
                ).fillna("")
                evidence_dates = pd.to_datetime(
                    inwarding_evidence.get("Date", pd.Series(dtype=str)),
                    errors="coerce",
                    dayfirst=True,
                ).dt.normalize()
                part_keys = inwarding_evidence.get(
                    "Part Number",
                    pd.Series("", index=inwarding_evidence.index),
                ).map(stock_part_key)
                inwarding_evidence = inwarding_evidence[
                    evidence_dates.eq(trace_plan_date.normalize())
                    & part_keys.eq(stock_part_key(trace.get("Part No.", "")))
                ]
                evidence_columns = [
                    column
                    for column in [
                        "Gate Entry No",
                        "Date",
                        "Supplier Name",
                        "Invoice Number",
                        "Invoice Qty",
                        "Receipt Qty",
                        "Discrepancy",
                        "Unloading Status",
                    ]
                    if column in inwarding_evidence
                ]
                with st.expander(
                    f"Inwarding evidence ({len(inwarding_evidence):,} row(s))",
                    expanded=not inwarding_evidence.empty,
                ):
                    if inwarding_evidence.empty:
                        st.caption(
                            "No inwarding invoice row exists for this part on the plan date."
                        )
                    else:
                        st.dataframe(
                            inwarding_evidence[evidence_columns],
                            use_container_width=True,
                            hide_index=True,
                        )

    action_columns = st.columns([1, 1, 4])
    with action_columns[0]:
        if st.button("Save stock values", type="primary"):
            merged = df.set_index("Part No.", drop=False)
            updates = edited_stock.set_index("Part No.", drop=False)
            editable_columns = [
                "Today's OS",
                "Remarks",
            ]
            for column in editable_columns:
                merged.loc[updates.index, column] = updates[column]
            save_table("part_inventory", merged.reset_index(drop=True))
            st.success("Current stock values saved.")
            st.rerun()
    with action_columns[1]:
        st.download_button(
            "Download CSV",
            recalculated.to_csv(index=False),
            file_name="part_inventory_requirements.csv",
            mime="text/csv",
        )


def rm_owner_cards_html(frame: pd.DataFrame, limit: int = 8) -> str:
    if frame.empty:
        return "<div class='rm-empty'>No buyer-owned shortages in this queue.</div>"
    summary = (
        frame.groupby("Buyer", as_index=False)
        .agg(
            Issues=("Part No.", "nunique"),
            Critical=("Severity", lambda values: values.eq("Critical").sum()),
            Suppliers=("Supplier", "nunique"),
            Shortage=("RM Shortage", "sum"),
        )
        .sort_values(["Critical", "Issues"], ascending=[False, False])
    )
    cards = []
    for _, row in summary.head(limit).iterrows():
        tone = "critical" if int(row["Critical"]) else "attention"
        cards.append(
            f'<div class="rm-owner-card {tone}">'
            f'<div class="rm-owner-name">{escape(str(row["Buyer"]))}</div>'
            '<div class="rm-owner-grid">'
            f'<div><b>{int(row["Issues"]):,}</b><span>parts</span></div>'
            f'<div><b>{int(row["Critical"]):,}</b><span>critical</span></div>'
            f'<div><b>{int(row["Suppliers"]):,}</b><span>suppliers</span></div>'
            "</div></div>"
        )
    return f"<div class='rm-owner-cards'>{''.join(cards)}</div>"


def save_rm_followup_record(
    part_no: str,
    supplier_status: str,
    next_expected_qty: float,
    expected_delivery: str,
    next_followup: str,
    owner: str,
    notes: str,
) -> None:
    existing = load_rm_followups().set_index("Part No.", drop=False)
    existing.loc[part_no, "Part No."] = part_no
    existing.loc[part_no, "Supplier Status"] = supplier_status
    existing.loc[part_no, "Next Expected Qty"] = next_expected_qty
    existing.loc[part_no, "Expected Delivery"] = expected_delivery
    existing.loc[part_no, "Next Follow-up"] = next_followup
    existing.loc[part_no, "Follow-up Owner"] = owner
    existing.loc[part_no, "Follow-up Notes"] = notes
    save_rm_followups(existing.reset_index(drop=True))


def render_rm_planning_agent(show_refresh: bool = True) -> None:
    st.header(
        "Shortage Prevention & Supplier Actions",
        help=(
            "Prioritizes material shortages across today, the rolling seven-day "
            "plan, and the remaining month, then records supplier follow-up actions."
        ),
    )
    st.write(
        "A decision workspace for PPC and SCM: see the parts that can constrain the "
        "plan, understand why, and assign the next supplier action."
    )

    if show_refresh:
        credentials = load_google_credentials()
        action_col, context_col = st.columns([1, 4])
        with action_col:
            refresh_clicked = st.button(
                "Refresh RM plan",
                type="primary",
                disabled=credentials is None,
                help="Pull the latest plan, production-so-far, SKU mapping, and BOM.",
            )
        with context_col:
            st.caption(
                "The last saved source copies remain visible until Refresh is clicked. "
                "Supplier requirements use System Stock; operational risk uses Physical Stock."
            )
        if refresh_clicked:
            try:
                with st.spinner("Refreshing RM planning sources..."):
                    for source in SOURCE_SHEETS.values():
                        source_df, _ = load_google_sheet_oauth(source["url"], credentials)
                        save_source_cache(source["cache"], source_df)
                st.success("RM planning sources refreshed.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not refresh RM planning sources: {exc}")

    missing_sources = [
        source["cache"] for source in SOURCE_SHEETS.values() if not source["cache"].exists()
    ]
    if missing_sources:
        st.warning("Refresh once to create the first RM planning snapshot.")
        return

    sources = {
        key: load_source_cache(source["cache"])
        for key, source in SOURCE_SHEETS.items()
    }
    inventory, inventory_diagnostics = build_part_inventory_plan(
        load_table("part_inventory"),
        sources,
    )
    if inventory_diagnostics.get("error"):
        st.warning(str(inventory_diagnostics["error"]))
        return
    views, meta = build_rm_planning_views(inventory, sources)
    if not views:
        st.warning(str(meta.get("error", "No RM planning view could be built.")))
        return

    today_view = views["Today"]
    followup_dates = pd.to_datetime(
        today_view.get("Next Follow-up", pd.Series(dtype=str)),
        errors="coerce",
    )
    open_followup = ~today_view.get(
        "Supplier Status",
        pd.Series("", index=today_view.index),
    ).isin(["Received"])
    followups_due = int(
        (followup_dates.le(pd.Timestamp(meta["plan_date"])) & open_followup).sum()
    )
    suppliers_due = int(
        today_view.loc[
            followup_dates.le(pd.Timestamp(meta["plan_date"])) & open_followup,
            "Supplier",
        ].nunique()
    )
    vehicle_risk = 0
    if not today_view.empty:
        per_vehicle = numeric(today_view["Part per Planned Vehicle"]).replace(0, pd.NA)
        risk_estimates = (
            numeric(today_view["RM Shortage"]) / per_vehicle
        ).replace([float("inf"), -float("inf")], pd.NA).dropna()
        maximum_risk = float(risk_estimates.max()) if not risk_estimates.empty else 0
        vehicle_risk = int(
            min(float(meta["daily_target"]), maximum_risk)
        )
    missing_stock_count = int(meta.get("missing_stock_count", 0))

    st.subheader(
        "Management cockpit",
        help=(
            "A summary of immediate line risks, missing stock data, affected "
            "suppliers, and open supplier commitments."
        ),
    )
    metric_columns = st.columns(5)
    with metric_columns[0]:
        render_metric("Immediate line-risk parts", f"{len(today_view):,}", "bad")
    with metric_columns[1]:
        render_metric("Vehicles potentially at risk", f"{vehicle_risk:,}", "warn")
    with metric_columns[2]:
        render_metric("Suppliers due today", f"{suppliers_due:,}", "warn")
    with metric_columns[3]:
        render_metric("Follow-ups due", f"{followups_due:,}", "neutral")
    with metric_columns[4]:
        render_metric("Stock counts missing", f"{missing_stock_count:,}", "neutral")

    if missing_stock_count:
        st.warning(
            f"{missing_stock_count:,} parts are excluded from shortage alerts because "
            "verified stock is unavailable. They are separated by root cause in the "
            "stock-data queues."
        )
        missing_reasons = (
            meta.get("missing_stock", pd.DataFrame())
            .get("Data Issue", pd.Series(dtype=str))
            .value_counts()
        )
        if not missing_reasons.empty:
            st.caption(
                "Stock-data flags: "
                + " · ".join(
                    f"{reason}: {count:,}"
                    for reason, count in missing_reasons.items()
                )
            )
    scm_mapped = int(inventory_diagnostics.get("scm_stock_rows_mapped", 0))
    if scm_mapped:
        st.success(
            f"{scm_mapped:,} parts use SCM Summary → "
            f"{clean_text(inventory_diagnostics.get('scm_stock_label', '')) or 'System Opening Stock'} "
            "as today's opening-stock baseline."
        )
    if int(meta.get("unmapped_buyer_count", 0)):
        st.caption(
            f"Data quality: {int(meta['unmapped_buyer_count']):,} parts still have no buyer mapping."
        )

    coverage_end = pd.Timestamp(meta["seven_day_coverage_end"])
    month_coverage_end = pd.Timestamp(meta["month_coverage_end"])
    plan_summary = st.columns(3)
    with plan_summary[0]:
        st.info(
            f"**Today**  \n{display_qty(meta['daily_target'])} planned · "
            f"{display_qty(meta['produced_so_far'])} produced so far"
        )
    with plan_summary[1]:
        st.info(
            f"**Rolling 7 days**  \n{display_qty(meta['seven_day_plan'])} remaining "
            f"through {coverage_end:%d %b}"
        )
    with plan_summary[2]:
        st.info(
            f"**Remaining month**  \n{display_qty(meta['month_plan'])} vehicles "
            f"through {month_coverage_end:%d %b}"
        )

    fallback_mix_date = inventory_diagnostics.get("fallback_mix_date")
    with st.expander("Planning assumptions and data confidence"):
        st.markdown(
            "- Known System Stock is required before a supplier requirement is raised.\n"
            "- Physical Stock is used separately for operational line-risk checks.\n"
            "- Future total vehicle plans use the current saved part-per-vehicle mix "
            "when a detailed future mix is unavailable.\n"
            "- Supplier messages are scheduled and tracked here but are not sent automatically."
        )
        if pd.notna(fallback_mix_date):
            st.write(
                f"Current variant-colour mix fallback: "
                f"**{pd.Timestamp(fallback_mix_date):%d %b %Y}**."
            )

    st.subheader(
        "Priority workspace",
        help=(
            "Choose a planning horizon and filter the shortage queue by buyer, "
            "supplier, severity, or part."
        ),
    )
    horizon_labels = {
        name: f"{name} ({len(frame):,})"
        for name, frame in views.items()
    }
    horizon_name = st.radio(
        "Planning horizon",
        list(views),
        format_func=lambda value: horizon_labels[value],
        horizontal=True,
        key="rm_agent_horizon",
    )
    horizon_frame = views[horizon_name].copy()
    missing_stock = meta.get("missing_stock", pd.DataFrame()).copy()
    possible_revision = missing_stock[
        missing_stock.get("Data Issue", pd.Series("", index=missing_stock.index))
        .astype(str)
        .str.startswith("Possible revision mismatch")
    ]
    absent_from_scm = missing_stock[
        missing_stock.get("Data Issue", pd.Series("", index=missing_stock.index))
        .astype(str)
        .eq("Part not found in SCM Summary")
    ]
    invalid_or_blank_stock = missing_stock[
        missing_stock.get("Data Issue", pd.Series("", index=missing_stock.index))
        .astype(str)
        .str.contains(
            r"System Opening Stock blank|Invalid System Opening Stock",
            regex=True,
        )
    ]
    followup_due_mask = pd.to_datetime(
        horizon_frame.get("Next Follow-up", pd.Series(dtype=str)),
        errors="coerce",
    ).le(pd.Timestamp(meta["plan_date"]))
    queue_frames = {
        "All actionable": horizon_frame,
        "Critical today": horizon_frame[horizon_frame["Severity"].eq("Critical")],
        "High · 1–2 days": horizon_frame[horizon_frame["Severity"].eq("High")],
        "Upcoming": horizon_frame[horizon_frame["Severity"].eq("Medium")],
        "Follow-ups due": horizon_frame[followup_due_mask.fillna(False)],
        "Supplier delayed": horizon_frame[
            horizon_frame["Supplier Status"].eq("Delayed")
        ],
        "All stock-data gaps": missing_stock,
        "Possible revision mismatch": possible_revision,
        "Not found in SCM Summary": absent_from_scm,
        "Blank / invalid SCM stock": invalid_or_blank_stock,
    }
    queue_labels = {
        name: f"{name} ({len(frame):,})"
        for name, frame in queue_frames.items()
    }
    queue_name = st.selectbox(
        "Work queue",
        list(queue_frames),
        format_func=lambda value: queue_labels[value],
        index=(
            list(queue_frames).index("All stock-data gaps")
            if horizon_frame.empty and not missing_stock.empty
            else 0
        ),
        key="rm_agent_queue",
        help="Choose one focused queue instead of scanning a single giant table.",
    )
    queue = queue_frames[queue_name].copy()

    is_stock_data_queue = "Data Issue" in queue.columns
    if not is_stock_data_queue:
        st.markdown(rm_owner_cards_html(queue), unsafe_allow_html=True)

    buyers = sorted(
        queue.get("Buyer", pd.Series(dtype=str))
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    filters = st.columns([1.5, 1, 1, 0.7])
    with filters[0]:
        search = st.text_input(
            "Search",
            placeholder="part number, part name, supplier",
            key="rm_agent_search",
        )
    with filters[1]:
        selected_buyer = st.selectbox(
            "Buyer",
            ["All buyers"] + buyers,
            key="rm_agent_buyer",
        )
    supplier_source = queue
    if selected_buyer != "All buyers":
        supplier_source = supplier_source[
            supplier_source["Buyer"].eq(selected_buyer)
        ]
    suppliers = sorted(
        supplier_source.get("Supplier", pd.Series(dtype=str))
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    buyer_supplier_key = re.sub(
        r"[^a-z0-9]+",
        "_",
        selected_buyer.lower(),
    ).strip("_")
    with filters[2]:
        selected_supplier = st.selectbox(
            "Supplier",
            ["All suppliers"] + suppliers,
            key=f"rm_agent_supplier_{buyer_supplier_key}",
            help="Shows only suppliers assigned to the selected buyer.",
        )
    with filters[3]:
        page_size = st.selectbox(
            "Rows",
            [25, 50, 100],
            key="rm_agent_page_size",
        )

    filtered = queue.copy()
    if selected_buyer != "All buyers":
        filtered = filtered[filtered["Buyer"].eq(selected_buyer)]
    if selected_supplier != "All suppliers":
        filtered = filtered[filtered["Supplier"].eq(selected_supplier)]
    if search.strip():
        term = search.strip().lower()
        search_columns = ["Part No.", "Part Name", "Supplier", "Buyer"]
        filtered = filtered[
            filtered[search_columns]
            .astype(str)
            .apply(lambda column: column.str.lower().str.contains(term, na=False))
            .any(axis=1)
        ]
    if filtered.empty:
        st.success("No items match this queue and filter combination.")
        return

    total_pages = max((len(filtered) + page_size - 1) // page_size, 1)
    page_columns = st.columns([1, 4])
    with page_columns[0]:
        page_number = st.number_input(
            "Page",
            min_value=1,
            max_value=total_pages,
            value=1,
            step=1,
            key=f"rm_page_{normalize_column_name(queue_name)}",
        )
    with page_columns[1]:
        st.caption(
            f"{len(filtered):,} items · page {page_number} of {total_pages}. "
            "Select one row to open its evidence and action controls."
        )
    start = (int(page_number) - 1) * page_size
    page_frame = filtered.iloc[start : start + page_size].reset_index(drop=True)

    if is_stock_data_queue:
        compact = page_frame[
            ["Buyer", "Supplier", "Part No.", "Part Name", "Data Issue"]
        ].copy()
    else:
        compact = page_frame[
            [
                "Severity",
                "Part No.",
                "Part Name",
                "Supplier",
                "Buyer",
                "System Stock",
                "RM Shortage",
                "Required By",
                "Supplier Status",
            ]
        ].copy()
        compact["Severity"] = compact["Severity"].map(
            {"Critical": "🔴 Critical", "High": "🟠 High", "Medium": "🟡 Medium"}
        )
    selection = st.dataframe(
        compact,
        use_container_width=True,
        hide_index=True,
        height=min(510, 42 + len(compact) * 35),
        on_select="rerun",
        selection_mode="single-row",
        key=f"rm_queue_{normalize_column_name(horizon_name)}_{normalize_column_name(queue_name)}_{page_number}",
    )
    if hasattr(selection, "selection"):
        selected_rows = selection.selection.rows
    else:
        selected_rows = selection.get("selection", {}).get("rows", [])
    if not selected_rows:
        st.info("Select a row above to inspect the calculation and take action.")
        st.download_button(
            "Download this filtered queue",
            filtered.to_csv(index=False),
            file_name=f"rm_{normalize_column_name(queue_name)}.csv",
            mime="text/csv",
        )
        return

    selected = page_frame.iloc[selected_rows[0]].copy()
    st.subheader(
        "Selected issue",
        help=(
            "Explains the selected shortage calculation, production impact, "
            "required-by date, and the supplier action that must be recorded."
        ),
    )
    st.markdown(
        f"### {escape(clean_text(selected['Part No.']))} · "
        f"{escape(clean_text(selected['Part Name']) or 'Part name unavailable')}"
    )

    if is_stock_data_queue:
        info_columns = st.columns([2, 1])
        with info_columns[0]:
            st.warning(
                "No shortage decision is made for this part until its stock mapping "
                "is verified. This prevents missing data from becoming a false Critical alert."
            )
            st.write(
                f"**Supplier:** {clean_text(selected['Supplier']) or 'Unmapped'}  \n"
                f"**Buyer:** {clean_text(selected['Buyer']) or 'Unmapped'}  \n"
                f"**Why unmatched:** {clean_text(selected['Data Issue'])}  \n"
                f"**Recommended action:** "
                f"{clean_text(selected['Recommended Data Action'])}  \n"
                f"**Remaining part need today:** "
                f"{display_qty(selected['Remaining Part Need'])}"
            )
        with info_columns[1]:
            opening_stock_entry = st.number_input(
                "Today's opening stock",
                min_value=0.0,
                value=0.0,
                key=f"rm_missing_stock_{stock_part_key(selected['Part No.'])}",
                help="Enter today's independent opening-stock baseline for this part.",
            )
            if st.button("Save today's OS", type="primary"):
                updated = inventory.copy()
                updated.loc[
                    updated["Part No."].eq(selected["Part No."]),
                    "Today's OS",
                ] = opening_stock_entry
                save_table("part_inventory", updated)
                st.success("Today's OS saved. The agent will recalculate this part.")
                st.rerun()
        return

    evidence_columns = st.columns(4)
    with evidence_columns[0]:
        render_metric("System stock", display_qty(selected["System Stock"]), "neutral")
    with evidence_columns[1]:
        render_metric("RM needed", display_qty(selected["Gross RM Need"]), "neutral")
    with evidence_columns[2]:
        render_metric("Shortage", display_qty(selected["RM Shortage"]), "bad")
    with evidence_columns[3]:
        render_metric("Required by", clean_text(selected["Required By"]) or "—", "warn")

    details, actions = st.columns([1.25, 1])
    with details:
        st.markdown("#### Why the agent flagged it")
        st.write(
            f"The {horizon_name.lower()} plan needs "
            f"**{display_qty(selected['Gross RM Need'])}** units. Current System Stock "
            f"is **{display_qty(selected['System Stock'])}**, leaving a supplier requirement of "
            f"**{display_qty(selected['RM Shortage'])}**."
        )
        st.markdown("#### Production impact")
        st.write(
            f"**Affected variants:** "
            f"{clean_text(selected['Affected Variants']) or 'Variant mapping unavailable'}"
        )
        part_per_vehicle = float(
            numeric(
                pd.Series([selected.get("Part per Planned Vehicle", 0)])
            ).iloc[0]
        )
        physical_stock = float(
            numeric(pd.Series([selected.get("Physical Stock", 0)])).iloc[0]
        )
        achievable_vehicles = (
            int(max(physical_stock, 0) // part_per_vehicle)
            if part_per_vehicle > 0
            else 0
        )
        horizon_vehicles = int(
            float(
                numeric(
                    pd.Series([selected.get("Horizon Vehicle Plan", 0)])
                ).iloc[0]
            )
        )
        impacted_vehicles = max(horizon_vehicles - achievable_vehicles, 0)
        confidence = (
            "High — system stock and plan are available."
            if horizon_name == "Today"
            else "Planning estimate — future totals use the current saved variant mix."
        )
        st.caption(f"Data confidence: {confidence}")
        st.markdown("#### PPC recovery scenarios")
        st.dataframe(
            pd.DataFrame(
                [
                    (
                        "Protect full plan",
                        f"Expedite {display_qty(selected['RM Shortage'])} parts by "
                        f"{clean_text(selected['Required By']) or 'the required date'}.",
                        "Full selected-horizon plan remains protected if supply arrives.",
                    ),
                    (
                        "Cap affected production",
                        f"Limit affected variants to approximately "
                        f"{achievable_vehicles:,} vehicles until replenishment.",
                        f"Approximately {impacted_vehicles:,} planned vehicles may move.",
                    ),
                    (
                        "Resequence",
                        "Run unaffected variants first and hold the constrained family.",
                        "Buys time until the supplier ETA without inventing additional stock.",
                    ),
                ],
                columns=["Scenario", "Action", "Estimated impact"],
            ),
            width="stretch",
            hide_index=True,
        )

    with actions:
        st.markdown("#### Supplier action")
        statuses = [
            "Awaiting confirmation",
            "Confirmed",
            "In transit",
            "Delayed",
            "Received",
        ]
        current_status = clean_text(selected["Supplier Status"]) or statuses[0]
        supplier_status = st.selectbox(
            "Supplier status *",
            statuses,
            index=statuses.index(current_status)
            if current_status in statuses
            else 0,
            key=f"rm_detail_status_{stock_part_key(selected['Part No.'])}",
        )
        saved_qty = pd.to_numeric(
            pd.Series([selected.get("Next Expected Qty", "")]),
            errors="coerce",
        ).iloc[0]
        default_qty = (
            float(saved_qty)
            if pd.notna(saved_qty) and float(saved_qty) > 0
            else float(numeric(pd.Series([selected["RM Shortage"]])).iloc[0])
        )
        next_expected_qty = st.number_input(
            "Next expected qty *",
            min_value=0.0,
            value=max(default_qty, 0.0),
            step=1.0,
            help="Quantity the supplier is expected to deliver in the next receipt.",
            key=f"rm_detail_qty_{stock_part_key(selected['Part No.'])}",
        )
        saved_expected = pd.to_datetime(
            selected["Expected Delivery"],
            errors="coerce",
        )
        default_expected = (
            saved_expected
            if pd.notna(saved_expected)
            else pd.to_datetime(selected["Required By"], errors="coerce")
        )
        if pd.isna(default_expected):
            default_expected = pd.Timestamp(meta["plan_date"])
        expected_delivery_date = st.date_input(
            "Expected delivery *",
            value=pd.Timestamp(default_expected).date(),
            key=f"rm_detail_eta_{stock_part_key(selected['Part No.'])}",
        )
        saved_followup = pd.to_datetime(
            selected["Next Follow-up"],
            errors="coerce",
        )
        if pd.isna(saved_followup):
            saved_followup = pd.Timestamp(meta["plan_date"])
        next_followup_date = st.date_input(
            "Next follow-up *",
            value=pd.Timestamp(saved_followup).date(),
            key=f"rm_detail_followup_{stock_part_key(selected['Part No.'])}",
        )
        expected_delivery = expected_delivery_date.isoformat()
        next_followup = next_followup_date.isoformat()
        owner_value = clean_text(selected["Buyer"])
        owner = st.text_input(
            "Follow-up owner *",
            value=owner_value,
            disabled=True,
            help="Locked to the buyer mapped to this part.",
            key=f"rm_detail_owner_{stock_part_key(selected['Part No.'])}",
        )
        notes = st.text_area(
            "Notes *",
            value=clean_text(selected["Follow-up Notes"]),
            placeholder="Record supplier commitment, escalation, or next action.",
            key=f"rm_detail_notes_{stock_part_key(selected['Part No.'])}",
        )
        recommendation_row = selected.copy()
        recommendation_row["Supplier Status"] = supplier_status
        recommendation_row["Next Expected Qty"] = next_expected_qty
        recommendation_row["Expected Delivery"] = expected_delivery
        recommendation_row["Next Follow-up"] = next_followup
        recommendation_row["Follow-up Owner"] = owner
        st.info(
            "**Agent recommendation**\n\n"
            + rm_recommendation(recommendation_row)
        )
        recorded_inwarding = float(
            numeric(
                pd.Series([selected.get("Parts Inwarded", 0)])
            ).iloc[0]
        )
        verified_receipt = (
            supplier_status == "Received"
            and recorded_inwarding >= next_expected_qty
            and next_expected_qty > 0
        )
        if verified_receipt:
            st.success(
                f"Commitment verified against {display_qty(recorded_inwarding)} "
                "recorded inwarded units."
            )
        elif supplier_status == "Received":
            st.warning(
                f"Supplier is marked Received, but only "
                f"{display_qty(recorded_inwarding)} inwarded units are recorded "
                f"against {display_qty(next_expected_qty)} expected. Keep the action open."
            )
        supplier_message = (
            f"Subject: Material required for {clean_text(selected['Part No.'])}\n\n"
            f"Please confirm supply of {display_qty(next_expected_qty)} units of "
            f"{clean_text(selected['Part Name'])} by {expected_delivery}. "
            f"The material is required by {clean_text(selected['Required By']) or 'the production requirement date'}. "
            f"Please share dispatch status and ETA before {next_followup}.\n\n"
            f"Owner: {owner}"
        )
        with st.expander("Human-approved supplier message draft"):
            st.text_area(
                "Draft",
                value=supplier_message,
                height=180,
                disabled=True,
                key=f"rm_supplier_draft_{stock_part_key(selected['Part No.'])}",
            )
            st.caption(
                "Draft only. The app does not send supplier communication automatically."
            )
        missing_fields = []
        if next_expected_qty <= 0:
            missing_fields.append("Next expected qty")
        if not expected_delivery:
            missing_fields.append("Expected delivery")
        if not next_followup:
            missing_fields.append("Next follow-up")
        if not owner or owner in {"Unmapped buyer", "Not mapped"}:
            missing_fields.append("Mapped follow-up owner")
        if not notes.strip():
            missing_fields.append("Notes")
        if missing_fields:
            st.caption(
                "Complete before saving: " + ", ".join(missing_fields) + "."
            )
        if st.button(
            "Save supplier action",
            type="primary",
            disabled=bool(missing_fields),
        ):
            save_rm_followup_record(
                clean_text(selected["Part No."]),
                supplier_status,
                next_expected_qty,
                expected_delivery,
                next_followup,
                owner,
                notes,
            )
            st.success("Supplier action saved.")
            st.rerun()


def render_live_google_sheet() -> None:
    st.header(
        "Live Google Sheet",
        help=(
            "Loads a Google Sheet link into a filterable saved snapshot without "
            "editing the source sheet."
        ),
    )
    st.write("This page shows the saved copy of your Google Sheet. Press the button only when you want to pull the latest sheet into the app.")
    source_label = "Google Sheets API" if google_sheets_credentials_configured() else "CSV export link"

    sheet_url = st.text_input(
        "Google Sheet link",
        value=DEFAULT_GOOGLE_SHEET_URL,
        help="With API credentials, the sheet can stay private. Without credentials, it must be shared as Anyone with link can view.",
    )
    left, right = st.columns([1.4, 4.6])
    with left:
        refresh_clicked = st.button("Create / update sheet copy", type="primary")
    with right:
        st.caption(
            f"Current read method: {source_label}. "
            f"Saved copy: `{LIVE_GOOGLE_SHEET_SNAPSHOT_CSV.relative_to(APP_DIR)}`. "
            f"Last copied: {snapshot_age_label(LIVE_GOOGLE_SHEET_SNAPSHOT_CSV)}."
        )
    if not google_sheets_credentials_configured():
        st.info("No Google Sheets API credentials found. This button can read only sheets shared as Anyone with the link can view.")

    if refresh_clicked:
        try:
            create_sheet_snapshot(sheet_url, LIVE_GOOGLE_SHEET_SNAPSHOT_CSV, LIVE_GOOGLE_SHEET_SNAPSHOT_META)
            st.success("Created a fresh copy of the Google Sheet.")
            st.rerun()
        except Exception as exc:
            st.error("Could not create the sheet copy.")
            show_google_sheet_access_help(exc)
            return

    raw = load_sheet_snapshot(LIVE_GOOGLE_SHEET_SNAPSHOT_CSV)
    if raw.empty:
        st.warning("No saved copy exists yet.")
        st.write("Click **Create / update sheet copy** once. After that, the app will keep showing that saved copy until you click the button again.")
        return
    meta = load_snapshot_meta(LIVE_GOOGLE_SHEET_SNAPSHOT_META)
    df = raw_sheet_to_table(raw)

    cols = st.columns(3)
    with cols[0]:
        render_metric("Rows", f"{len(df):,}", "neutral")
    with cols[1]:
        render_metric("Columns", f"{len(df.columns):,}", "neutral")
    with cols[2]:
        copied_at = str(meta.get("copied_at", "")) or snapshot_age_label(LIVE_GOOGLE_SHEET_SNAPSHOT_CSV)
        render_metric("Copied", copied_at, "ok")

    filtered = filter_frame(df, "live_google_sheet")
    st.caption(f"{len(filtered):,} rows shown from the saved sheet copy.")
    st.dataframe(filtered, use_container_width=True, hide_index=True)
    st.download_button(
        "Download saved copy as CSV",
        filtered.to_csv(index=False),
        file_name="google_sheet_snapshot.csv",
        mime="text/csv",
    )


def supplier_cards_html(summary: pd.DataFrame, limit: int = 24) -> str:
    if summary.empty:
        return "<div class='supplier-empty'>No supplier mapping found for the selected filters.</div>"
    cards = []
    for _, row in summary.head(limit).iterrows():
        risk_parts = int(row.get("Below Required", 0) or 0)
        critical_parts = int(row.get("Critical", 0) or 0)
        tone = "bad" if critical_parts else "warn" if risk_parts else "ok"
        cards.append(
            f"""
            <div class="supplier-card {tone}">
                <div class="supplier-card-title">{escape(str(row.get("Supplier", "Unmapped supplier")))}</div>
                <div class="supplier-card-owner">{escape(str(row.get("Buyer", "Unmapped buyer")))}</div>
                <div class="supplier-card-kpis">
                    <div><span>Parts</span><b>{int(row.get("Parts", 0) or 0):,}</b></div>
                    <div><span>Low</span><b>{risk_parts:,}</b></div>
                    <div><span>Stock</span><b>{escape(display_qty(row.get("Closing Stock", 0)))}</b></div>
                </div>
            </div>
            """
        )
    return f"<div class='supplier-grid'>{''.join(cards)}</div>"


def render_supplier_buyer_map() -> None:
    st.header(
        "Supplier Buyer Map",
        help=(
            "Maps each supplier and part to the buyer responsible for follow-up, "
            "using the saved SPOC Summary copy."
        ),
    )
    st.write("Buyer-supplier ownership from the saved SPOC Summary copy.")
    source_label = "Google Sheets API" if google_sheets_credentials_configured() else "CSV export link"

    sheet_url = st.text_input(
        "SPOC Summary Sheet link",
        value=DEFAULT_SPOC_SUMMARY_SHEET_URL,
        help="Paste the exact Google Sheet tab URL for the SPOC/SCM Summary sheet.",
    )
    action_col, info_col = st.columns([1.4, 4.6])
    with action_col:
        refresh_clicked = st.button("Create / update SPOC copy", type="primary")
    with info_col:
        st.caption(
            f"Current fetch method: {source_label}. "
            f"Saved copy: `{SPOC_SUMMARY_SNAPSHOT_CSV.relative_to(APP_DIR)}`. "
            f"Last copied: {snapshot_age_label(SPOC_SUMMARY_SNAPSHOT_CSV)}."
        )
    if not google_sheets_credentials_configured():
        st.info("No Google Sheets API credentials found. This button can read only sheets shared as Anyone with the link can view.")

    if refresh_clicked:
        try:
            create_sheet_snapshot(sheet_url, SPOC_SUMMARY_SNAPSHOT_CSV, SPOC_SUMMARY_SNAPSHOT_META)
            st.success("Created a fresh SPOC Summary copy.")
            st.rerun()
        except Exception as exc:
            st.error("Could not create the SPOC Summary copy.")
            show_google_sheet_access_help(exc)
            return

    try:
        raw = load_sheet_snapshot(SPOC_SUMMARY_SNAPSHOT_CSV)
        if raw.empty:
            st.warning("No saved SPOC Summary copy exists yet.")
            st.write(
                "Click **Create / update SPOC copy** once. "
                "After that, this page will keep showing that saved copy until you click the button again."
            )
            return
        snapshot_meta = load_snapshot_meta(SPOC_SUMMARY_SNAPSHOT_META)
        parts, meta = parse_spoc_summary_raw(raw)
    except Exception as exc:
        st.error("Could not read the saved SPOC Summary copy.")
        st.code(str(exc))
        return

    if parts.empty:
        st.warning("No supplier-buyer mapping could be built from this sheet.")
        if meta.get("error"):
            st.code(meta["error"])
        return

    summary = build_supplier_buyer_summary(parts)
    buyers = sorted(parts["Buyer"].replace("", pd.NA).dropna().unique().tolist())
    supplier_values = sorted(parts["Supplier"].replace("", pd.NA).dropna().unique().tolist())

    metric_cols = st.columns(5)
    with metric_cols[0]:
        render_metric("Parts mapped", f"{parts['Part No.'].nunique():,}", "neutral")
    with metric_cols[1]:
        render_metric("Buyers", f"{len(buyers):,}", "neutral")
    with metric_cols[2]:
        render_metric("Suppliers", f"{len(supplier_values):,}", "ok")
    with metric_cols[3]:
        below_count = int(parts["Status"].isin(["Below required", "Critical"]).sum())
        render_metric("Below required", f"{below_count:,}", "warn")
    with metric_cols[4]:
        critical_count = int(parts["Status"].eq("Critical").sum())
        render_metric("Critical", f"{critical_count:,}", "bad")

    labels = [label for label in [meta.get("requirement_label"), meta.get("commitment_label"), meta.get("closing_label")] if label]
    if labels:
        st.caption("Snapshot date columns used: " + " | ".join(dict.fromkeys(labels)))
    copied_at = str(snapshot_meta.get("copied_at", "") or "")
    if copied_at:
        st.caption(f"Saved Google Sheet copy created at: {copied_at}. Source rows copied: {snapshot_meta.get('rows', 0):,}.")

    filter_cols = st.columns([1.2, 1.2, 1.2, 1.6])
    with filter_cols[0]:
        selected_buyer = st.selectbox(
            "Buyer view",
            ["All buyers"] + buyers,
            index=0,
            key="supplier_map_buyer",
        )
    with filter_cols[1]:
        selected_statuses = st.multiselect(
            "Status",
            sorted(parts["Status"].unique().tolist()),
            default=[],
            key="supplier_map_status",
        )
    supplier_filter_source = parts
    if selected_buyer != "All buyers":
        supplier_filter_source = supplier_filter_source[
            supplier_filter_source["Buyer"].eq(selected_buyer)
        ]
    buyer_supplier_values = sorted(
        supplier_filter_source["Supplier"]
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    buyer_supplier_key = re.sub(
        r"[^a-z0-9]+",
        "_",
        selected_buyer.lower(),
    ).strip("_")
    with filter_cols[2]:
        selected_suppliers = st.multiselect(
            "Supplier",
            buyer_supplier_values,
            default=[],
            key=f"supplier_map_suppliers_{buyer_supplier_key}",
            help="Shows only suppliers assigned to the selected buyer.",
        )
    with filter_cols[3]:
        search = st.text_input("Search part or supplier", placeholder="part no., part name, supplier")

    filtered_parts = parts.copy()
    if selected_buyer != "All buyers":
        filtered_parts = filtered_parts[filtered_parts["Buyer"].eq(selected_buyer)]
    if selected_statuses:
        filtered_parts = filtered_parts[filtered_parts["Status"].isin(selected_statuses)]
    if selected_suppliers:
        filtered_parts = filtered_parts[filtered_parts["Supplier"].isin(selected_suppliers)]
    if search.strip():
        term = search.strip().lower()
        search_cols = ["Part No.", "Part Name", "Supplier", "Buyer"]
        filtered_parts = filtered_parts[
            filtered_parts[search_cols]
            .astype(str)
            .apply(lambda col: col.str.lower().str.contains(term, na=False))
            .any(axis=1)
        ]

    filtered_summary = build_supplier_buyer_summary(filtered_parts)
    st.subheader(
        "Supplier Ownership Snapshot",
        help=(
            "Summarizes how many suppliers and parts belong to each buyer and "
            "highlights incomplete ownership mappings."
        ),
    )
    st.markdown(supplier_cards_html(filtered_summary), unsafe_allow_html=True)
    if len(filtered_summary) > 24:
        st.caption(f"Showing first 24 supplier cards out of {len(filtered_summary):,}. Use filters to narrow the view.")

    st.subheader(
        "Part-Level Mapping",
        help=(
            "Shows the detailed part-to-supplier-to-buyer records behind the "
            "ownership summary."
        ),
    )
    table = filtered_parts.sort_values(["Status", "Buyer", "Supplier", "Part No."]).reset_index(drop=True)
    st.caption(f"{len(table):,} part rows shown after filters.")
    st.dataframe(table, use_container_width=True, hide_index=True, height=520)
    st.download_button(
        "Download mapping CSV",
        table.to_csv(index=False),
        file_name="spoc_supplier_buyer_mapping.csv",
        mime="text/csv",
    )


def render_superset_inwarding() -> None:
    st.header(
        "Inwarding Parts",
        help=(
            "Reviews material receipts and gate-entry records used to validate "
            "incoming quantities and unloading progress."
        ),
    )
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

    st.subheader(
        "Live GRN Inwarding Table",
        help=(
            "Displays the filtered goods-receipt records pulled from the connected "
            "inwarding source."
        ),
    )
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


def clean_inwarding_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    renamed = df.rename(
        columns={
            "Suplier Name": "Supplier Name",
            "Invoice QTY": "Invoice Qty",
        }
    )
    preferred_columns = [
        "Gate Entry No",
        "Date",
        "Shift",
        "In Time",
        "Vehicle No",
        "Invoice Number",
        "Invoice Date",
        "PO Number",
        "Supplier Name",
        "Part Number",
        "Part Name",
        "Invoice Qty",
        "Receipt Qty",
        "Discrepancy",
        "Unloading Status",
        "Model",
        "Remarks",
    ]
    available_columns = [
        column for column in preferred_columns if column in renamed.columns
    ]
    result = renamed[available_columns].copy().fillna("")
    supplier_values = result.get(
        "Supplier Name",
        pd.Series("", index=result.index),
    ).map(clean_text)
    part_values = result.get(
        "Part Number",
        pd.Series("", index=result.index),
    ).map(clean_text)
    placeholder_rows = (
        supplier_values.str.lower().str.startswith("enter ")
        | part_values.str.lower().str.startswith("enter ")
    )
    result = result[~placeholder_rows]
    if "Date" in result.columns:
        parsed_dates = pd.to_datetime(
            result["Date"],
            errors="coerce",
            format="mixed",
        )
        result = (
            result.assign(_parsed_date=parsed_dates)
            .sort_values(
                ["_parsed_date", "Gate Entry No"],
                ascending=[False, False],
                na_position="last",
            )
            .drop(columns="_parsed_date")
        )
    return result.reset_index(drop=True)


def supplier_match_key(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", clean_text(value).upper())


def canonical_supplier_key(value: object) -> str:
    ignored_words = {
        "CO",
        "COMPANY",
        "INC",
        "INDIA",
        "INDIAN",
        "LIMITED",
        "LLP",
        "LTD",
        "PRIVATE",
        "PVT",
        "UNIT",
    }
    words = [
        word
        for word in re.findall(r"[A-Z0-9]+", clean_text(value).upper())
        if word not in ignored_words and not word.isdigit()
    ]
    normalized_words: list[str] = []
    for word in words:
        if word.endswith("IES") and len(word) > 4:
            word = f"{word[:-3]}Y"
        elif word.endswith("S") and len(word) > 5:
            word = word[:-1]
        normalized_words.append(word)
    return "".join(normalized_words)


def clean_buyer_mapping_source(df: pd.DataFrame) -> pd.DataFrame:
    output_columns = ["Part Number", "Mapped Supplier", "Buyer Name"]
    if df.empty:
        return pd.DataFrame(columns=output_columns)
    if set(output_columns).issubset(df.columns):
        result = df[output_columns].copy()
    else:
        rows = df.astype(str).to_numpy().tolist()
        header_index = next(
            (
                index
                for index, row in enumerate(rows)
                if {"Component", "Supplier", "SCM Buyer"}.issubset(
                    {str(value).strip() for value in row}
                )
            ),
            None,
        )
        if header_index is None:
            return pd.DataFrame(columns=output_columns)
        width = len(df.columns)
        headers = unique_headers(rows[header_index], width)
        data_rows = [
            row + [""] * (width - len(row))
            for row in rows[header_index + 1 :]
        ]
        table = pd.DataFrame(data_rows, columns=headers).fillna("")
        result = table[["Component", "Supplier", "SCM Buyer"]].copy()
        result.columns = output_columns

    result["Part Number"] = result["Part Number"].map(stock_part_key)
    result["Mapped Supplier"] = result["Mapped Supplier"].map(clean_text)
    result["Buyer Name"] = result["Buyer Name"].map(normalize_buyer_name)
    return result[
        result["Buyer Name"].ne("")
        & (
            result["Part Number"].ne("")
            | result["Mapped Supplier"].ne("")
        )
    ].drop_duplicates()


def enrich_inwarding_buyers(
    inwarding: pd.DataFrame,
    buyer_mapping: pd.DataFrame,
) -> pd.DataFrame:
    result = inwarding.copy()
    if result.empty:
        return result

    mapping = clean_buyer_mapping_source(buyer_mapping)
    if mapping.empty:
        result["Buyer Name"] = "Not mapped"
    else:
        mapping["Part Key"] = mapping["Part Number"].map(stock_part_key)
        mapping["Supplier Key"] = mapping["Mapped Supplier"].map(
            supplier_match_key
        )
        mapping["Supplier Prefix"] = mapping["Supplier Key"].str[:20]
        mapping["Canonical Supplier Key"] = mapping["Mapped Supplier"].map(
            canonical_supplier_key
        )

        part_map = (
            mapping[mapping["Part Key"].ne("")]
            .groupby("Part Key")["Buyer Name"]
            .agg(joined_text)
        )
        supplier_map = (
            mapping[mapping["Supplier Key"].ne("")]
            .groupby("Supplier Key")["Buyer Name"]
            .agg(joined_text)
        )
        supplier_prefix_map = (
            mapping[mapping["Supplier Prefix"].ne("")]
            .groupby("Supplier Prefix")["Buyer Name"]
            .agg(joined_text)
        )
        canonical_supplier_map = (
            mapping[mapping["Canonical Supplier Key"].ne("")]
            .groupby("Canonical Supplier Key")["Buyer Name"]
            .agg(joined_text)
        )

        part_keys = result.get(
            "Part Number",
            pd.Series("", index=result.index),
        ).map(stock_part_key)
        supplier_keys = result.get(
            "Supplier Name",
            pd.Series("", index=result.index),
        ).map(supplier_match_key)
        buyers = part_keys.map(part_map).fillna("")
        buyers = buyers.where(
            buyers.ne(""),
            supplier_keys.map(supplier_map).fillna(""),
        )
        buyers = buyers.where(
            buyers.ne(""),
            supplier_keys.str[:20].map(supplier_prefix_map).fillna(""),
        )
        canonical_supplier_keys = result.get(
            "Supplier Name",
            pd.Series("", index=result.index),
        ).map(canonical_supplier_key)
        buyers = buyers.where(
            buyers.ne(""),
            canonical_supplier_keys.map(canonical_supplier_map).fillna(""),
        )
        result["Buyer Name"] = buyers.replace("", "Not mapped")

    if "Supplier Name" in result.columns:
        columns = list(result.columns)
        columns.remove("Buyer Name")
        supplier_index = columns.index("Supplier Name")
        columns.insert(supplier_index + 1, "Buyer Name")
        result = result[columns]
    return result


def save_inwarding_snapshot(df: pd.DataFrame, tab_name: str) -> None:
    save_source_cache(INWARDING_SNAPSHOT_PATH, df)
    metadata = {
        "source_url": INWARDING_SHEET_URL,
        "tab": tab_name,
        "rows": int(len(df)),
        "refreshed_at": datetime.now().isoformat(timespec="seconds"),
    }
    tmp_path = INWARDING_SNAPSHOT_META_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    tmp_path.replace(INWARDING_SNAPSHOT_META_PATH)


def load_inwarding_snapshot_meta() -> dict[str, object]:
    if not INWARDING_SNAPSHOT_META_PATH.exists():
        return {}
    try:
        return json.loads(
            INWARDING_SNAPSHOT_META_PATH.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError):
        return {}


def render_inwarding() -> None:
    st.header(
        "Inwarding Parts",
        help=(
            "Shows the last saved Direct Gate Entry snapshot, supports gate-entry "
            "fact-checking, and runs the buyer-owned discrepancy agent below."
        ),
    )
    st.write(
        "This page shows the last saved copy of the Direct Gate Entry sheet. "
        "Press Refresh only when you want to replace it with the latest version."
    )

    settings = google_oauth_settings()
    credentials = load_google_credentials() if settings is not None else None
    if settings is None:
        st.warning("Google OAuth is not configured yet.")
    elif credentials is None:
        authorization_url = begin_google_oauth(settings)
        st.link_button(
            "Connect Google account",
            authorization_url,
            type="primary",
        )
        st.caption("Use an account that can view the inwarding Google Sheet.")
    else:
        st.success("Google connected with read-only Sheets access.")

    refresh_clicked = st.button(
        "Refresh",
        type="primary",
        disabled=credentials is None,
    )
    if refresh_clicked:
        try:
            with st.spinner("Reading the latest Direct Gate Entry sheet..."):
                source_df, tab_name = load_google_sheet_oauth(
                    INWARDING_SHEET_URL,
                    credentials,
                )
                buyer_source_df, buyer_tab_name = load_google_sheet_oauth(
                    BUYER_MAPPING_SHEET_URL,
                    credentials,
                )
                cleaned_df = clean_inwarding_snapshot(source_df)
                cleaned_buyer_mapping = clean_buyer_mapping_source(
                    buyer_source_df
                )
                save_inwarding_snapshot(cleaned_df, tab_name)
                save_source_cache(
                    BUYER_MAPPING_CACHE_PATH,
                    cleaned_buyer_mapping,
                )
                refreshed_snapshot = enrich_inwarding_buyers(
                    cleaned_df,
                    cleaned_buyer_mapping,
                )
                refreshed_actions = reconcile_agent_actions(
                    build_agent_issues(refreshed_snapshot)
                )
                open_action_count = int(
                    (
                        refreshed_actions["Active"].eq("Yes")
                        & ~refreshed_actions["Status"].isin(
                            ["Resolved", "Auto-resolved"]
                        )
                    ).sum()
                )
            st.success(
                f"Saved the latest '{tab_name}' snapshot with "
                f"{len(cleaned_df):,} rows and buyer mapping from "
                f"'{buyer_tab_name}'. The agent found "
                f"{open_action_count:,} open action(s)."
            )
        except Exception as exc:
            st.error(
                "Refresh failed. The previous saved snapshot is still being shown. "
                f"Details: {exc}"
            )

    snapshot = enrich_inwarding_buyers(
        clean_inwarding_snapshot(
            load_source_cache(INWARDING_SNAPSHOT_PATH)
        ),
        load_source_cache(BUYER_MAPPING_CACHE_PATH),
    )
    if snapshot.empty:
        st.info(
            "No saved inwarding snapshot exists yet. Connect Google and press "
            "Refresh inwarding from Google Sheet once."
        )
        return

    metadata = load_inwarding_snapshot_meta()
    refreshed_at = str(metadata.get("refreshed_at", "")).replace("T", " ")
    tab_name = str(metadata.get("tab", "DIRECT GATE ENTRY"))
    st.caption(
        f"Showing saved tab: {tab_name}. Last refreshed: "
        f"{refreshed_at or snapshot_age_label(INWARDING_SNAPSHOT_PATH)}."
    )

    filtered = snapshot.copy()
    parsed_dates = pd.to_datetime(
        filtered.get("Date", pd.Series(index=filtered.index, dtype=str)),
        errors="coerce",
        format="mixed",
    )
    valid_dates = parsed_dates.dropna()
    filter_columns = st.columns([1.5, 1.2, 1.5, 1.7, 1.4, 1.3])
    with filter_columns[0]:
        if valid_dates.empty:
            selected_dates = ()
            st.caption("No valid dates found")
        else:
            min_date = valid_dates.min().date()
            max_date = valid_dates.max().date()
            selected_dates = st.date_input(
                "Entry date range",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
                key="inwarding_snapshot_dates",
            )
    with filter_columns[1]:
        gate_search = st.text_input(
            "Gate entry number",
            placeholder="Search gate entry",
            key="inwarding_snapshot_gate_entry",
            help="Enter a full or partial gate entry number to fact-check a flagged issue.",
        )
    with filter_columns[2]:
        part_search = st.text_input(
            "Part number",
            placeholder="Search part number",
            key="inwarding_snapshot_part",
        )
    with filter_columns[3]:
        buyer_options = sorted(
            value
            for value in filtered.get(
                "Buyer Name",
                pd.Series(dtype=str),
            ).astype(str).unique()
            if value
        )
        selected_buyers = st.multiselect(
            "Buyer",
            buyer_options,
            placeholder="All buyers",
            key="inwarding_snapshot_buyers",
        )
    supplier_filter_source = filtered
    if selected_buyers:
        supplier_filter_source = supplier_filter_source[
            supplier_filter_source["Buyer Name"].isin(selected_buyers)
        ]
    supplier_options = sorted(
        value
        for value in supplier_filter_source.get(
            "Supplier Name",
            pd.Series(dtype=str),
        ).astype(str).unique()
        if value
    )
    selected_buyers_key = "_".join(
        sorted(
            re.sub(r"[^a-z0-9]+", "_", buyer.lower()).strip("_")
            for buyer in selected_buyers
        )
    ) or "all_buyers"
    with filter_columns[4]:
        selected_suppliers = st.multiselect(
            "Supplier",
            supplier_options,
            placeholder="All suppliers",
            key=f"inwarding_snapshot_suppliers_{selected_buyers_key}",
            help="Shows only suppliers assigned to the selected buyer selection.",
        )
    with filter_columns[5]:
        status_options = sorted(
            value
            for value in filtered.get(
                "Unloading Status",
                pd.Series(dtype=str),
            ).astype(str).unique()
            if value
        )
        selected_statuses = st.multiselect(
            "Unloading status",
            status_options,
            placeholder="All statuses",
            key="inwarding_snapshot_statuses",
        )

    if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
        start_date, end_date = selected_dates
        if start_date != min_date or end_date != max_date:
            filtered = filtered[
                parsed_dates.dt.date.between(start_date, end_date)
            ]
    if part_search.strip() and "Part Number" in filtered.columns:
        filtered = filtered[
            filtered["Part Number"].astype(str).str.contains(
                part_search.strip(),
                case=False,
                na=False,
                regex=False,
            )
        ]
    if gate_search.strip() and "Gate Entry No" in filtered.columns:
        filtered = filtered[
            filtered["Gate Entry No"].astype(str).str.contains(
                gate_search.strip(),
                case=False,
                na=False,
                regex=False,
            )
        ]
    if selected_suppliers and "Supplier Name" in filtered.columns:
        filtered = filtered[
            filtered["Supplier Name"].isin(selected_suppliers)
        ]
    if selected_buyers and "Buyer Name" in filtered.columns:
        filtered = filtered[filtered["Buyer Name"].isin(selected_buyers)]
    if selected_statuses and "Unloading Status" in filtered.columns:
        filtered = filtered[
            filtered["Unloading Status"].isin(selected_statuses)
        ]

    receipt_total = numeric(
        filtered.get("Receipt Qty", pd.Series(dtype=str))
    ).sum()
    mapped_rows = int(
        filtered.get("Buyer Name", pd.Series(dtype=str))
        .astype(str)
        .ne("Not mapped")
        .sum()
    )
    mapping_coverage = (
        mapped_rows / len(filtered) * 100
        if len(filtered)
        else 0
    )
    metric_columns = st.columns(4)
    with metric_columns[0]:
        render_metric("Snapshot rows", f"{len(filtered):,}", "neutral")
    with metric_columns[1]:
        render_metric("Receipt qty", f"{receipt_total:,.0f}", "ok")
    with metric_columns[2]:
        render_metric(
            "Unique parts",
            f"{filtered.get('Part Number', pd.Series(dtype=str)).replace('', pd.NA).dropna().nunique():,}",
            "neutral",
        )
    with metric_columns[3]:
        latest_date = pd.to_datetime(
            filtered.get("Date", pd.Series(dtype=str)),
            errors="coerce",
            format="mixed",
        ).max()
        render_metric(
            "Latest entry",
            latest_date.strftime("%d %b %Y")
            if pd.notna(latest_date)
            else "Not available",
            "neutral",
        )
    st.caption(
        f"Buyer mapping coverage: {mapped_rows:,} of {len(filtered):,} rows "
        f"({mapping_coverage:.1f}%). Part-number mapping is used first; "
        "supplier mapping is the fallback."
    )

    st.dataframe(
        filtered,
        use_container_width=True,
        hide_index=True,
        height=600,
    )
    st.download_button(
        "Download filtered inwarding CSV",
        data=filtered.to_csv(index=False).encode("utf-8"),
        file_name="inwarding_snapshot_filtered.csv",
        mime="text/csv",
        key="inwarding_snapshot_download",
    )
    st.divider()
    render_agentic_flow()


def render_outwarding_sources(manual_outwarding: pd.DataFrame) -> None:
    st.subheader(
        "Computed Daily Part Usage",
        help=(
            "Multiplies actual production by BOM quantities to calculate how many "
            "units of every component were consumed each day."
        ),
    )
    st.write(
        "Daily production is P-VIN actual + VNA actual + Free VIN actual. "
        "The result is multiplied by the exploded BOM and grouped by part number."
    )

    settings = google_oauth_settings()
    credentials = None
    if settings is None:
        st.warning("Google OAuth is not configured yet.")
        st.code(
            '[google_oauth]\n'
            'client_id = "YOUR_CLIENT_ID"\n'
            'client_secret = "YOUR_CLIENT_SECRET"\n'
            'redirect_uri = "http://localhost:8501/"',
            language="toml",
        )
    else:
        credentials = load_google_credentials()
        if credentials is None:
            authorization_url = begin_google_oauth(settings)
            st.link_button(
                "Connect Google account",
                authorization_url,
                type="primary",
            )
            st.caption("Use an account that has Viewer access to both source sheets.")
        else:
            st.success("Google connected with read-only Sheets access.")

    refresh_clicked = st.button(
        "Refresh calculation from Google Sheets",
        type="primary",
        disabled=credentials is None,
    )
    if refresh_clicked:
        try:
            with st.spinner("Reading production, FG mapping, and exploded BOM..."):
                for source in SOURCE_SHEETS.values():
                    source_df, _ = load_google_sheet_oauth(
                        source["url"],
                        credentials,
                    )
                    save_source_cache(source["cache"], source_df)
            st.success(
                "Latest source data loaded and the part-usage calculation was refreshed."
            )
        except Exception as exc:
            st.error(f"Could not load the Google Sheets data: {exc}")

    missing_sources = [
        source["cache"]
        for source in SOURCE_SHEETS.values()
        if not source["cache"].exists()
    ]
    if missing_sources:
        st.info(
            "Click “Refresh calculation from Google Sheets” to create the first "
            "computed part-usage view."
        )
        return

    sources = {
        key: load_source_cache(source["cache"])
        for key, source in SOURCE_SHEETS.items()
    }
    production, unmatched = build_daily_production(
        sources["vin_details"],
        sources["sku_map"],
    )
    production_usage, missing_bom_fgs = compute_production_part_usage(
        production,
        sources["exploded_bom"],
        sources["raw_bom"],
        sources["part_types"],
        sources["suppliers"],
    )
    combined = combine_manual_outwarding(production_usage, manual_outwarding)
    if combined.empty:
        st.warning("No computable production or manual outwarding rows were found.")
        return

    cache_copy = combined.copy()
    cache_copy["Usage Date"] = cache_copy["Usage Date"].dt.strftime("%Y-%m-%d")
    save_source_cache(COMPUTED_USAGE_CACHE_PATH, cache_copy)

    vehicle_total = production["Produced Qty"].sum()
    latest_production_date = production["Usage Date"].max()
    latest_production_total = production.loc[
        production["Usage Date"].eq(latest_production_date),
        "Produced Qty",
    ].sum()
    metric_columns = st.columns(4)
    with metric_columns[0]:
        render_metric(
            "Production days",
            f"{production['Usage Date'].nunique():,}",
            "neutral",
        )
    with metric_columns[1]:
        render_metric("Vehicles produced", f"{vehicle_total:,.0f}", "ok")
    with metric_columns[2]:
        render_metric(
            "Unique parts consumed",
            f"{combined['Part No.'].nunique():,}",
            "neutral",
        )
    with metric_columns[3]:
        render_metric(
            f"Latest production ({latest_production_date:%d %b})",
            f"{latest_production_total:,.0f}",
            "ok",
        )

    filtered = combined.copy()
    min_date = filtered["Usage Date"].min().date()
    max_date = filtered["Usage Date"].max().date()
    filter_columns = st.columns([1.7, 2, 2, 1.3])
    with filter_columns[0]:
        selected_dates = st.date_input(
            "Usage date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            key="computed_usage_dates",
        )
    with filter_columns[1]:
        part_search = st.text_input(
            "Search by part number",
            placeholder="Enter full or partial part number",
            key="computed_usage_part_search",
        )
    with filter_columns[2]:
        supplier_options = sorted(
            {
                supplier.strip()
                for value in filtered["Supplier"].astype(str)
                for supplier in value.split(",")
                if supplier.strip()
            }
        )
        selected_suppliers = st.multiselect(
            "Supplier",
            supplier_options,
            placeholder="All suppliers",
            key="computed_usage_suppliers",
        )
    with filter_columns[3]:
        material_options = sorted(
            value
            for value in filtered["Material Type"].astype(str).unique()
            if value
        )
        selected_materials = st.multiselect(
            "Material type",
            material_options,
            placeholder="All types",
            key="computed_usage_material_types",
        )

    if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
        start_date, end_date = selected_dates
        filtered = filtered[
            filtered["Usage Date"].dt.date.between(start_date, end_date)
        ]
    if part_search.strip():
        filtered = filtered[
            filtered["Part No."]
            .astype(str)
            .str.contains(part_search.strip(), case=False, na=False, regex=False)
        ]
    if selected_suppliers:
        selected_supplier_set = set(selected_suppliers)
        filtered = filtered[
            filtered["Supplier"].astype(str).apply(
                lambda value: bool(
                    selected_supplier_set
                    & {
                        supplier.strip()
                        for supplier in value.split(",")
                        if supplier.strip()
                    }
                )
            )
        ]
    if selected_materials:
        filtered = filtered[filtered["Material Type"].isin(selected_materials)]

    st.caption(
        f"Showing {len(filtered):,} daily part rows. Exact FG/color production "
        "records are used; aggregate model-only days are not estimated."
    )
    display = filtered.copy()
    display["Usage Date"] = display["Usage Date"].dt.strftime("%Y-%m-%d")
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Daily Total Production": st.column_config.NumberColumn(format="%.0f"),
            "Production Used Qty": st.column_config.NumberColumn(format="%.3f"),
            "Servicing Used Qty": st.column_config.NumberColumn(format="%.3f"),
            "Total Outwarding Qty": st.column_config.NumberColumn(format="%.3f"),
        },
    )
    st.download_button(
        "Download filtered part usage CSV",
        data=display.to_csv(index=False).encode("utf-8"),
        file_name="computed_daily_part_usage.csv",
        mime="text/csv",
        key="computed_usage_download",
    )

    if not unmatched.empty:
        unmatched_qty = unmatched["Produced Qty"].sum()
        st.warning(
            f"{unmatched_qty:,.0f} produced units could not be mapped to an exact "
            "FG code and were excluded."
        )
        with st.expander("Unmapped production diagnostics"):
            st.dataframe(unmatched, use_container_width=True, hide_index=True)
    if missing_bom_fgs:
        st.warning(
            f"{len(missing_bom_fgs)} produced FG code(s) have no exploded BOM and "
            "were excluded: " + ", ".join(missing_bom_fgs)
        )

    with st.expander("Daily finished-goods production used in calculation"):
        production_display = production.copy()
        production_display["Usage Date"] = production_display[
            "Usage Date"
        ].dt.strftime("%Y-%m-%d")
        st.dataframe(
            production_display,
            use_container_width=True,
            hide_index=True,
        )


def render_outwarding() -> None:
    st.header(
        "Outwarding Parts",
        help=(
            "Calculates production consumption from daily output and BOM data, "
            "with the latest date shown first."
        ),
    )
    st.write("Production consumption is calculated from daily production × BOM.")
    empty_manual_outwarding = pd.DataFrame(
        columns=TABLES["outwarding_parts"]["columns"]
    )
    render_outwarding_sources(empty_manual_outwarding)


def agent_action_id(
    issue_type: str,
    gate_entry: str,
    part_number: str,
    supplier: str,
    invoice_number: str,
) -> str:
    identity = "|".join(
        [
            issue_type,
            gate_entry,
            part_number,
            supplier,
            invoice_number,
        ]
    )
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12].upper()


def load_agent_actions() -> pd.DataFrame:
    if not AGENT_ACTIONS_PATH.exists():
        return pd.DataFrame(columns=AGENT_ACTION_COLUMNS)
    actions = pd.read_csv(AGENT_ACTIONS_PATH, dtype=str).fillna("")
    for column in AGENT_ACTION_COLUMNS:
        if column not in actions.columns:
            actions[column] = ""
    return actions[AGENT_ACTION_COLUMNS]


def save_agent_actions(actions: pd.DataFrame) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output = actions.copy().fillna("")
    for column in AGENT_ACTION_COLUMNS:
        if column not in output.columns:
            output[column] = ""
    tmp_path = AGENT_ACTIONS_PATH.with_suffix(".tmp")
    output[AGENT_ACTION_COLUMNS].to_csv(tmp_path, index=False)
    tmp_path.replace(AGENT_ACTIONS_PATH)


def latest_part_demand() -> dict[str, float]:
    usage = load_source_cache(COMPUTED_USAGE_CACHE_PATH)
    required_columns = {"Usage Date", "Part No.", "Total Outwarding Qty"}
    if usage.empty or not required_columns.issubset(usage.columns):
        return {}
    usage_dates = pd.to_datetime(
        usage["Usage Date"],
        errors="coerce",
        format="mixed",
    )
    if usage_dates.dropna().empty:
        return {}
    latest_date = usage_dates.max()
    latest = usage[usage_dates.eq(latest_date)].copy()
    latest["_demand"] = numeric(latest["Total Outwarding Qty"])
    return (
        latest.assign(
            _part_key=latest["Part No."].map(stock_part_key)
        )
        .groupby("_part_key")["_demand"]
        .sum()
        .to_dict()
    )


def discrepancy_severity(
    difference: float,
    invoice_qty: float,
    production_demand: float,
) -> str:
    magnitude = abs(difference)
    ratio = magnitude / abs(invoice_qty) if invoice_qty else 0
    if magnitude >= 100 or ratio >= 0.20:
        severity = "Critical"
    elif magnitude >= 20 or ratio >= 0.05:
        severity = "High"
    else:
        severity = "Medium"
    if difference > 0 and production_demand > 0:
        if difference >= production_demand:
            return "Critical"
        if severity == "Medium":
            return "High"
    return severity


def build_agent_issues(snapshot: pd.DataFrame) -> pd.DataFrame:
    if snapshot.empty:
        return pd.DataFrame(columns=AGENT_ACTION_COLUMNS)

    now = datetime.now()
    now_text = now.isoformat(timespec="seconds")
    demand_by_part = latest_part_demand()
    issues: list[dict[str, object]] = []

    def add_issue(
        row: pd.Series,
        issue_type: str,
        severity: str,
        reason: str,
        difference: float = 0,
        invoice_qty: float = 0,
        receipt_qty: float = 0,
    ) -> None:
        buyer = clean_text(row.get("Buyer Name", ""))
        if not buyer or buyer == "Not mapped":
            buyer = "SCM Admin"
        part_number = clean_text(row.get("Part Number", ""))
        supplier = clean_text(row.get("Supplier Name", ""))
        gate_entry = clean_text(row.get("Gate Entry No", ""))
        invoice_number = clean_text(row.get("Invoice Number", ""))
        entry_date_text = clean_text(row.get("Date", ""))
        entry_date = pd.to_datetime(
            entry_date_text,
            errors="coerce",
            dayfirst=True,
        )
        age_days = (
            max((now.date() - entry_date.date()).days, 0)
            if not pd.isna(entry_date)
            else 0
        )
        demand = float(demand_by_part.get(stock_part_key(part_number), 0))
        production_impact = "No latest-day demand"
        if difference > 0 and demand > 0:
            production_impact = (
                f"At risk: shortage {display_qty(difference)} vs "
                f"latest demand {display_qty(demand)}"
            )
        escalation = "None"
        if severity == "Critical" and age_days >= 1:
            escalation = "Escalate now"
        elif severity == "High" and age_days >= 2:
            escalation = "Escalate now"
        elif age_days >= 3:
            escalation = "Buyer follow-up due"
        issues.append(
            {
                "Action ID": agent_action_id(
                    issue_type,
                    gate_entry,
                    part_number,
                    supplier,
                    invoice_number,
                ),
                "Active": "Yes",
                "Issue Type": issue_type,
                "Severity": severity,
                "Buyer Name": buyer,
                "Supplier Name": supplier,
                "Part Number": part_number,
                "Part Name": clean_text(row.get("Part Name", "")),
                "Gate Entry No": gate_entry,
                "Entry Date": entry_date_text,
                "Invoice Qty": invoice_qty,
                "Receipt Qty": receipt_qty,
                "Difference Qty": difference,
                "Latest Production Demand": demand,
                "Production Impact": production_impact,
                "Reason": reason,
                "Status": "New",
                "Age (days)": age_days,
                "Escalation": escalation,
                "First Detected": now_text,
                "Last Checked": now_text,
                "Acknowledged At": "",
                "Resolved At": "",
                "Notes": "",
            }
        )

    invoice_numbers = pd.to_numeric(
        snapshot.get("Invoice Qty", pd.Series(index=snapshot.index)),
        errors="coerce",
    )
    receipt_numbers = pd.to_numeric(
        snapshot.get("Receipt Qty", pd.Series(index=snapshot.index)),
        errors="coerce",
    )
    differences = invoice_numbers - receipt_numbers
    quantity_issue_mask = (
        invoice_numbers.notna()
        & receipt_numbers.notna()
        & differences.abs().gt(0.000001)
    )
    for index, row in snapshot[quantity_issue_mask].iterrows():
        invoice_number = float(invoice_numbers.loc[index])
        receipt_number = float(receipt_numbers.loc[index])
        difference = float(differences.loc[index])
        demand = float(
            demand_by_part.get(
                stock_part_key(row.get("Part Number", "")),
                0,
            )
        )
        severity = discrepancy_severity(
            difference,
            invoice_number,
            demand,
        )
        direction = "short" if difference > 0 else "excess"
        add_issue(
            row,
            "Quantity discrepancy",
            severity,
            f"Receipt is {display_qty(abs(difference))} {direction} "
            "against the invoice quantity.",
            difference,
            invoice_number,
            receipt_number,
        )

    buyer_values = snapshot.get(
        "Buyer Name",
        pd.Series("", index=snapshot.index),
    ).map(clean_text)
    for _, row in snapshot[
        buyer_values.isin(["", "Not mapped"])
    ].iterrows():
        add_issue(
            row,
            "Buyer not mapped",
            "High",
            "No unambiguous buyer exists in the current buyer mapping.",
        )

    critical_fields = [
        "PO Number",
        "Invoice Number",
        "Part Number",
        "Supplier Name",
    ]
    missing_masks = {
        field: snapshot.get(
            field,
            pd.Series("", index=snapshot.index),
        ).map(clean_text).eq("")
        for field in critical_fields
    }
    missing_any = pd.concat(missing_masks, axis=1).any(axis=1)
    for index, row in snapshot[missing_any].iterrows():
        missing_fields = [
            field
            for field in critical_fields
            if bool(missing_masks[field].loc[index])
        ]
        severity = (
            "High"
            if {"Part Number", "Supplier Name"} & set(missing_fields)
            else "Medium"
        )
        add_issue(
            row,
            "Missing critical data",
            severity,
            "Missing: " + ", ".join(missing_fields) + ".",
        )

    unloading_statuses = snapshot.get(
        "Unloading Status",
        pd.Series("", index=snapshot.index),
    ).map(clean_text).str.lower()
    entry_dates = pd.to_datetime(
        snapshot.get("Date", pd.Series("", index=snapshot.index)),
        errors="coerce",
        dayfirst=True,
    )
    waiting_mask = (
        unloading_statuses.str.contains("waiting", regex=False)
        | unloading_statuses.eq("")
    ) & entry_dates.notna()
    for index, row in snapshot[waiting_mask].iterrows():
        waiting_days = max((now.date() - entry_dates.loc[index].date()).days, 0)
        if waiting_days >= 1:
            add_issue(
                row,
                "Unloading overdue",
                "Critical" if waiting_days >= 3 else "High",
                f"Material has been waiting for unloading for "
                f"{waiting_days} day(s).",
            )

    duplicate_columns = [
        "Gate Entry No",
        "Invoice Number",
        "Part Number",
        "Supplier Name",
        "Invoice Qty",
        "Receipt Qty",
    ]
    if set(duplicate_columns).issubset(snapshot.columns):
        duplicate_rows = snapshot[
            snapshot.duplicated(duplicate_columns, keep=False)
        ]
        for _, group in duplicate_rows.groupby(
            duplicate_columns,
            dropna=False,
            sort=False,
        ):
            if len(group) > 1:
                add_issue(
                    group.iloc[0],
                    "Possible duplicate entry",
                    "Medium",
                    f"{len(group)} identical inwarding rows were found.",
                )

    if not issues:
        return pd.DataFrame(columns=AGENT_ACTION_COLUMNS)
    return (
        pd.DataFrame(issues)
        .drop_duplicates("Action ID", keep="last")
        .reindex(columns=AGENT_ACTION_COLUMNS)
    )


def reconcile_agent_actions(current_issues: pd.DataFrame) -> pd.DataFrame:
    previous = load_agent_actions()
    now_text = datetime.now().isoformat(timespec="seconds")
    if previous.empty:
        output = current_issues.copy()
        save_agent_actions(output)
        return output

    previous_by_id = previous.set_index("Action ID", drop=False)
    reconciled_rows: list[dict[str, object]] = []
    current_ids: set[str] = set()
    for _, issue in current_issues.iterrows():
        row = issue.to_dict()
        action_id = str(row["Action ID"])
        current_ids.add(action_id)
        if action_id in previous_by_id.index:
            old = previous_by_id.loc[action_id]
            if isinstance(old, pd.DataFrame):
                old = old.iloc[-1]
            for field in [
                "Status",
                "First Detected",
                "Acknowledged At",
                "Resolved At",
                "Notes",
            ]:
                row[field] = clean_text(old.get(field, row[field]))
            if row["Status"] in {"Resolved", "Auto-resolved"}:
                row["Status"] = "Reopened"
                row["Resolved At"] = ""
        row["Active"] = "Yes"
        row["Last Checked"] = now_text
        reconciled_rows.append(row)

    for _, old in previous.iterrows():
        action_id = clean_text(old.get("Action ID", ""))
        if action_id in current_ids:
            continue
        row = old.to_dict()
        row["Active"] = "No"
        row["Last Checked"] = now_text
        if clean_text(row.get("Status", "")) != "Auto-resolved":
            row["Status"] = "Auto-resolved"
            row["Resolved At"] = now_text
        reconciled_rows.append(row)

    output = (
        pd.DataFrame(reconciled_rows)
        .drop_duplicates("Action ID", keep="first")
        .reindex(columns=AGENT_ACTION_COLUMNS)
        .fillna("")
    )
    save_agent_actions(output)
    return output


def save_agent_followup(action_id: str) -> None:
    actions = load_agent_actions()
    action_mask = actions["Action ID"].eq(action_id)
    if not action_mask.any():
        return
    status_key = f"agent_status_{action_id}"
    notes_key = f"agent_notes_{action_id}"
    new_status = clean_text(st.session_state.get(status_key, "New"))
    allowed_statuses = {
        "New",
        "Reopened",
        "Acknowledged",
        "Investigating",
        "Awaiting source correction",
    }
    if new_status not in allowed_statuses:
        new_status = "Reopened"
    now_text = datetime.now().isoformat(timespec="seconds")
    previous = actions.loc[action_mask].iloc[0]
    actions.loc[action_mask, "Status"] = new_status
    actions.loc[action_mask, "Notes"] = clean_text(
        st.session_state.get(notes_key, "")
    )
    if (
        new_status
        in {
            "Acknowledged",
            "Investigating",
            "Awaiting source correction",
        }
        and not clean_text(previous["Acknowledged At"])
    ):
        actions.loc[action_mask, "Acknowledged At"] = now_text
    if new_status != clean_text(previous["Status"]):
        actions.loc[action_mask, "Resolved At"] = ""
    save_agent_actions(actions)
    st.session_state["agent_followup_notice"] = (
        "Follow-up saved. The agent will close this action only after the "
        "source discrepancy is corrected."
    )


def render_agent_action_detail(
    selected: pd.Series,
    actions: pd.DataFrame,
) -> None:
    selected_action_id = clean_text(selected["Action ID"])
    severity_class = clean_text(selected["Severity"]).lower()
    st.markdown(
        f"<div class='agent-review-heading'>"
        f"<span class='agent-chip {escape(severity_class)}'>"
        f"{escape(clean_text(selected['Severity']))}</span>"
        f"<b>{escape(clean_text(selected['Issue Type']))}</b>"
        f"<span>Action {escape(selected_action_id)}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    detail_columns = st.columns(3)
    with detail_columns[0]:
        with st.container(border=True):
            st.markdown("**Owner and source**")
            st.markdown(
                f"Buyer: **{escape(clean_text(selected['Buyer Name']))}**  \n"
                f"Supplier: {escape(clean_text(selected['Supplier Name']) or '—')}  \n"
                f"Gate entry: {escape(clean_text(selected['Gate Entry No']) or '—')}  \n"
                f"Entry date: {escape(clean_text(selected['Entry Date']) or '—')}"
            )
    with detail_columns[1]:
        with st.container(border=True):
            st.markdown("**Material**")
            st.markdown(
                f"Part: **{escape(clean_text(selected['Part Number']) or '—')}**  \n"
                f"Name: {escape(clean_text(selected['Part Name']) or '—')}  \n"
                f"Age: {escape(clean_text(selected['Age (days)']) or '0')} day(s)  \n"
                f"Escalation: **{escape(clean_text(selected['Escalation']))}**"
            )
    with detail_columns[2]:
        with st.container(border=True):
            st.markdown("**Quantity and production**")
            st.markdown(
                f"Invoice: **{display_qty(selected['Invoice Qty'])}**  \n"
                f"Received: **{display_qty(selected['Receipt Qty'])}**  \n"
                f"Difference: **{display_qty(selected['Difference Qty'])}**  \n"
                f"{escape(clean_text(selected['Production Impact']))}"
            )

    if selected["Severity"] == "Critical":
        st.error(f"Why it was flagged: {selected['Reason']}", icon="🔴")
    elif selected["Severity"] == "High":
        st.warning(f"Why it was flagged: {selected['Reason']}", icon="🟠")
    else:
        st.info(f"Why it was flagged: {selected['Reason']}", icon="🟡")

    st.markdown("**Buyer follow-up**")
    if clean_text(selected["Active"]) == "No":
        st.success(
            "Verified resolved: the latest agent check could no longer "
            "find this discrepancy in the source data."
        )
        st.caption(
            f"Resolved at: {clean_text(selected['Resolved At']) or 'Not recorded'}"
        )
        return

    workflow_options = [
        "New",
        "Reopened",
        "Acknowledged",
        "Investigating",
        "Awaiting source correction",
    ]
    current_status = clean_text(selected["Status"])
    if current_status not in workflow_options:
        current_status = "Reopened"
    with st.form(
        key=f"agent_followup_form_{selected_action_id}",
        border=True,
    ):
        workflow_columns = st.columns([1, 2])
        with workflow_columns[0]:
            st.selectbox(
                "Workflow status",
                workflow_options,
                index=workflow_options.index(current_status),
                key=f"agent_status_{selected_action_id}",
                help="Buyers can progress the work, but cannot mark it resolved. Resolution is system-verified from refreshed source data.",
            )
        with workflow_columns[1]:
            st.text_area(
                "Follow-up notes",
                value=clean_text(selected["Notes"]),
                placeholder="Add supplier follow-up, expected correction date, or investigation details.",
                key=f"agent_notes_{selected_action_id}",
                help="Notes are retained in the audit history for management review.",
            )
        st.form_submit_button(
            "Save follow-up",
            type="primary",
            on_click=save_agent_followup,
            args=(selected_action_id,),
        )


def render_agentic_flow_legacy() -> None:
    st.header(
        "Inwarding Discrepancy Agent",
        help=(
            "Checks inwarding records for quantity, timing, and control issues, "
            "assigns them to buyers, and keeps an auditable resolution history."
        ),
    )
    st.caption(
        "A buyer-owned action queue generated from the latest saved inwarding "
        "snapshot. The agent verifies corrections before closing an issue."
    )
    with st.expander("How this page works", expanded=False):
        st.markdown(
            """
            1. Refresh **Inwarding Parts** to read the newest Google Sheet data.
            2. The agent checks quantities, ownership, required fields, unloading
               delays, duplicate rows, and possible production impact.
            3. Buyers acknowledge and investigate their assigned actions here.
            4. An action becomes **Auto-resolved** only after a later agent check
               confirms that the source discrepancy no longer exists.

            Hover over the small **ⓘ** icons beside labels for a quick definition.
            """
        )
    snapshot = enrich_inwarding_buyers(
        clean_inwarding_snapshot(
            load_source_cache(INWARDING_SNAPSHOT_PATH)
        ),
        load_source_cache(BUYER_MAPPING_CACHE_PATH),
    )
    if snapshot.empty:
        st.info(
            "Refresh the Inwarding Parts sheet once before running the agent."
        )
        return

    with st.spinner("Agent is checking inwarding data..."):
        actions = reconcile_agent_actions(build_agent_issues(snapshot))
    followup_notice = st.session_state.pop("agent_followup_notice", "")
    if followup_notice:
        st.success(followup_notice)

    active = actions[actions["Active"].eq("Yes")].copy()
    active_open = active[
        ~active["Status"].isin(["Resolved", "Auto-resolved"])
    ].copy()
    critical = active_open[
        active_open["Severity"].eq("Critical")
    ]
    escalations = active_open[
        active_open["Escalation"].ne("None")
    ]
    production_risk = active_open[
        active_open["Production Impact"].str.startswith("At risk", na=False)
    ]

    st.subheader(
        "Current position",
        help="A quick view of unresolved issues in the current saved snapshot.",
    )
    metric_columns = st.columns(4)
    metric_columns[0].metric(
        "Open actions",
        f"{len(active_open):,}",
        help="Active discrepancies that have not yet been verified as corrected.",
        border=True,
    )
    metric_columns[1].metric(
        "Critical",
        f"{len(critical):,}",
        help="High-impact quantity differences or unloading delays requiring immediate attention.",
        border=True,
    )
    metric_columns[2].metric(
        "Escalations due",
        f"{len(escalations):,}",
        help="Critical items older than one day, High items older than two days, or other overdue follow-ups.",
        border=True,
    )
    metric_columns[3].metric(
        "Production risks",
        f"{len(production_risk):,}",
        help="Short receipts for parts also required by the latest production/BOM calculation.",
        border=True,
    )
    st.markdown(
        """
        <div class="agent-legend">
            <span class="agent-chip critical">Critical</span>
            <span class="agent-chip high">High</span>
            <span class="agent-chip medium">Medium</span>
            <span class="agent-chip resolved">Verified resolved</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if active_open.empty:
        st.success("No active discrepancies are currently open.")
    else:
        st.subheader(
            "Priority overview",
            help="Workload grouped by owner and by the type of problem detected.",
        )
        overview_columns = st.columns([1.35, 1])
        buyer_summary = active_open.pivot_table(
            index="Buyer Name",
            columns="Severity",
            values="Action ID",
            aggfunc="count",
            fill_value=0,
        )
        for severity in ["Critical", "High", "Medium"]:
            if severity not in buyer_summary.columns:
                buyer_summary[severity] = 0
        buyer_summary = buyer_summary[["Critical", "High", "Medium"]]
        buyer_summary["Total"] = buyer_summary.sum(axis=1)
        buyer_summary = (
            buyer_summary.sort_values(
                ["Critical", "Total"],
                ascending=False,
            )
            .reset_index()
        )
        issue_summary = (
            active_open.groupby("Issue Type")
            .agg(
                Actions=("Action ID", "count"),
                Critical=(
                    "Severity",
                    lambda values: int((values == "Critical").sum()),
                ),
            )
            .sort_values(["Critical", "Actions"], ascending=False)
            .reset_index()
        )
        with overview_columns[0]:
            with st.container(border=True):
                st.markdown("**Buyer workload**")
                st.caption(
                    f"{active_open['Buyer Name'].nunique():,} owners currently "
                    "have open actions."
                )
                st.dataframe(
                    buyer_summary,
                    width="stretch",
                    hide_index=True,
                    height=min(260, 36 + len(buyer_summary) * 35),
                )
        with overview_columns[1]:
            with st.container(border=True):
                st.markdown("**Problems detected**")
                st.caption(
                    "Use this to see which control is creating the most work."
                )
                st.dataframe(
                    issue_summary,
                    width="stretch",
                    hide_index=True,
                    height=min(260, 36 + len(issue_summary) * 35),
                )

    st.subheader(
        "Action queue",
        help="Filter the queue, then choose one action below to review its evidence and update its workflow status.",
    )
    filter_columns = st.columns(4)
    with filter_columns[0]:
        buyer_filter = st.multiselect(
            "Buyer",
            sorted(actions["Buyer Name"].dropna().unique()),
            placeholder="All buyers",
            key="agent_buyer_filter",
            help="The buyer accountable for following up. Unmapped ownership is routed to SCM Admin.",
        )
    with filter_columns[1]:
        severity_filter = st.multiselect(
            "Severity",
            ["Critical", "High", "Medium"],
            placeholder="All severities",
            key="agent_severity_filter",
            help="Critical needs immediate attention; High needs prompt follow-up; Medium is a control or data-quality warning.",
        )
    with filter_columns[2]:
        status_filter = st.multiselect(
            "Status",
            [
                "New",
                "Reopened",
                "Acknowledged",
                "Investigating",
                "Awaiting source correction",
                "Auto-resolved",
            ],
            default=[
                "New",
                "Reopened",
                "Acknowledged",
                "Investigating",
                "Awaiting source correction",
            ],
            key="agent_status_filter",
            help="Auto-resolved is system-controlled and appears only after the source data passes the next check.",
        )
    with filter_columns[3]:
        issue_filter = st.multiselect(
            "Issue type",
            sorted(actions["Issue Type"].dropna().unique()),
            placeholder="All issue types",
            key="agent_issue_filter",
            help="The specific rule that caused the agent to create an action.",
        )

    filtered = actions.copy()
    if buyer_filter:
        filtered = filtered[filtered["Buyer Name"].isin(buyer_filter)]
    if severity_filter:
        filtered = filtered[filtered["Severity"].isin(severity_filter)]
    if status_filter:
        filtered = filtered[filtered["Status"].isin(status_filter)]
    if issue_filter:
        filtered = filtered[filtered["Issue Type"].isin(issue_filter)]

    severity_order = {"Critical": 0, "High": 1, "Medium": 2}
    filtered["_severity_order"] = (
        filtered["Severity"].map(severity_order).fillna(9)
    )
    filtered["_age_numeric"] = pd.to_numeric(
        filtered["Age (days)"],
        errors="coerce",
    ).fillna(0)
    filtered = filtered.sort_values(
        ["_severity_order", "_age_numeric", "Buyer Name"],
        ascending=[True, False, True],
    ).drop(columns=["_severity_order", "_age_numeric"])

    queue_columns = [
        "Action ID",
        "Severity",
        "Buyer Name",
        "Issue Type",
        "Supplier Name",
        "Part Number",
        "Difference Qty",
        "Age (days)",
        "Status",
    ]
    queue = filtered[queue_columns].copy()
    queue["Difference Qty"] = pd.to_numeric(
        queue["Difference Qty"],
        errors="coerce",
    ).fillna(0)
    queue["Age (days)"] = pd.to_numeric(
        queue["Age (days)"],
        errors="coerce",
    ).fillna(0).astype(int)

    def severity_style(value: object) -> str:
        styles = {
            "Critical": "background-color:#fee2e2;color:#991b1b;font-weight:700",
            "High": "background-color:#ffedd5;color:#9a3412;font-weight:700",
            "Medium": "background-color:#fef9c3;color:#854d0e;font-weight:700",
        }
        return styles.get(str(value), "")

    def status_style(value: object) -> str:
        styles = {
            "Auto-resolved": "background-color:#dcfce7;color:#166534;font-weight:700",
            "Reopened": "background-color:#fce7f3;color:#9d174d;font-weight:700",
            "Investigating": "background-color:#dbeafe;color:#1d4ed8;font-weight:700",
            "Awaiting source correction": "background-color:#ede9fe;color:#6d28d9;font-weight:700",
        }
        return styles.get(str(value), "")

    queue_styler = (
        queue.style.map(severity_style, subset=["Severity"])
        .map(status_style, subset=["Status"])
        .format({"Difference Qty": "{:,.2f}", "Age (days)": "{:,.0f}"})
    )
    st.dataframe(
        queue_styler,
        width="stretch",
        hide_index=True,
        height=min(430, 38 + max(len(queue), 1) * 35),
        column_config={
            "Difference Qty": st.column_config.NumberColumn(format="%.2f"),
            "Age (days)": st.column_config.NumberColumn(format="%d"),
        },
    )
    st.caption(
        f"Showing {len(queue):,} action(s). Select an action below for the full "
        "reason, quantities, production impact, and workflow controls."
    )

    if filtered.empty:
        st.info("No actions match the selected filters.")
    else:
        action_lookup = filtered.set_index("Action ID", drop=False)
        selected_action_id = st.selectbox(
            "Review one action",
            filtered["Action ID"].tolist(),
            format_func=lambda action_id: (
                f"{action_lookup.loc[action_id, 'Severity']} · "
                f"{action_lookup.loc[action_id, 'Buyer Name']} · "
                f"{action_lookup.loc[action_id, 'Issue Type']} · "
                f"{action_lookup.loc[action_id, 'Part Number'] or 'No part number'}"
            ),
            key="agent_selected_action",
            help="Choose an action to see all evidence without scrolling through a very wide table.",
        )
        selected = action_lookup.loc[selected_action_id]
        if isinstance(selected, pd.DataFrame):
            selected = selected.iloc[0]

        severity_class = clean_text(selected["Severity"]).lower()
        st.markdown(
            f"<div class='agent-review-heading'>"
            f"<span class='agent-chip {escape(severity_class)}'>"
            f"{escape(clean_text(selected['Severity']))}</span>"
            f"<b>{escape(clean_text(selected['Issue Type']))}</b>"
            f"<span>Action {escape(clean_text(selected['Action ID']))}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        detail_columns = st.columns(3)
        with detail_columns[0]:
            with st.container(border=True):
                st.markdown("**Owner and source**")
                st.markdown(
                    f"Buyer: **{escape(clean_text(selected['Buyer Name']))}**  \n"
                    f"Supplier: {escape(clean_text(selected['Supplier Name']) or '—')}  \n"
                    f"Gate entry: {escape(clean_text(selected['Gate Entry No']) or '—')}  \n"
                    f"Entry date: {escape(clean_text(selected['Entry Date']) or '—')}"
                )
        with detail_columns[1]:
            with st.container(border=True):
                st.markdown("**Material**")
                st.markdown(
                    f"Part: **{escape(clean_text(selected['Part Number']) or '—')}**  \n"
                    f"Name: {escape(clean_text(selected['Part Name']) or '—')}  \n"
                    f"Age: {escape(clean_text(selected['Age (days)']) or '0')} day(s)  \n"
                    f"Escalation: **{escape(clean_text(selected['Escalation']))}**"
                )
        with detail_columns[2]:
            with st.container(border=True):
                st.markdown("**Quantity and production**")
                st.markdown(
                    f"Invoice: **{display_qty(selected['Invoice Qty'])}**  \n"
                    f"Received: **{display_qty(selected['Receipt Qty'])}**  \n"
                    f"Difference: **{display_qty(selected['Difference Qty'])}**  \n"
                    f"{escape(clean_text(selected['Production Impact']))}"
                )

        if selected["Severity"] == "Critical":
            st.error(f"Why it was flagged: {selected['Reason']}", icon="🔴")
        elif selected["Severity"] == "High":
            st.warning(f"Why it was flagged: {selected['Reason']}", icon="🟠")
        else:
            st.info(f"Why it was flagged: {selected['Reason']}", icon="🟡")

        st.markdown("**Buyer follow-up**")
        if clean_text(selected["Active"]) == "No":
            st.success(
                "Verified resolved: the latest agent check could no longer "
                "find this discrepancy in the source data."
            )
            st.caption(
                f"Resolved at: {clean_text(selected['Resolved At']) or 'Not recorded'}"
            )
        else:
            workflow_options = [
                "New",
                "Reopened",
                "Acknowledged",
                "Investigating",
                "Awaiting source correction",
            ]
            current_status = clean_text(selected["Status"])
            if current_status not in workflow_options:
                current_status = "Reopened"
            with st.form(
                key=f"agent_followup_form_{selected_action_id}",
                border=True,
            ):
                workflow_columns = st.columns([1, 2])
                with workflow_columns[0]:
                    new_status = st.selectbox(
                        "Workflow status",
                        workflow_options,
                        index=workflow_options.index(current_status),
                        key=f"agent_status_{selected_action_id}",
                        help="Buyers can progress the work, but cannot mark it resolved. Resolution is system-verified from refreshed source data.",
                    )
                with workflow_columns[1]:
                    new_notes = st.text_area(
                        "Follow-up notes",
                        value=clean_text(selected["Notes"]),
                        placeholder="Add supplier follow-up, expected correction date, or investigation details.",
                        key=f"agent_notes_{selected_action_id}",
                        help="Notes are retained in the audit history for management review.",
                    )
                save_followup = st.form_submit_button(
                    "Save follow-up",
                    type="primary",
                    on_click=save_agent_followup,
                    args=(selected_action_id,),
                )
    with st.expander("Agent rules and complete audit history"):
        st.markdown(
            """
            - Quantity mismatch: invoice quantity differs from receipt quantity.
            - Buyer ownership: part mapping first, then normalized supplier mapping.
            - Data quality: missing PO, invoice, part, or supplier information.
            - Delay: material remains waiting for unloading beyond one day.
            - Duplicate control: identical inwarding rows are flagged once.
            - Escalation: Critical items after one day and High items after two days.
            - Production impact: shortages are compared with the latest calculated
              daily BOM requirement.
            - Verified resolution: buyers cannot manually close an issue. The agent
              sets `Auto-resolved` only when the discrepancy disappears from the
              refreshed source snapshot.
            """
        )
        st.dataframe(
            actions,
            width="stretch",
            hide_index=True,
        )
        st.download_button(
            "Download complete action audit CSV",
            data=actions.to_csv(index=False).encode("utf-8"),
            file_name="inwarding_agent_action_audit.csv",
            mime="text/csv",
            key="agent_audit_download",
        )


def render_agentic_flow() -> None:
    st.header(
        "Inwarding Discrepancy Agent",
        help=(
            "Checks inwarding records for quantity, timing, and control issues, "
            "assigns them to buyers, and verifies corrections after refresh."
        ),
    )
    st.caption(
        "Each buyer gets one workspace containing all assigned issues, grouped "
        "by severity and ordered by age."
    )
    with st.expander("How to use this page", expanded=False):
        st.markdown(
            """
            1. Choose your name under **Buyer workspace**.
            2. Open the **Critical**, **High**, or **Medium** tab.
            3. Click any row to see its evidence and record follow-up.
            4. The **Verified resolved** tab contains only issues the agent
               confirmed were corrected in refreshed source data.
            """
        )

    snapshot = enrich_inwarding_buyers(
        clean_inwarding_snapshot(
            load_source_cache(INWARDING_SNAPSHOT_PATH)
        ),
        load_source_cache(BUYER_MAPPING_CACHE_PATH),
    )
    if snapshot.empty:
        st.info(
            "Refresh the Inwarding Parts sheet once before running the agent."
        )
        return

    with st.spinner("Agent is checking inwarding data..."):
        actions = reconcile_agent_actions(build_agent_issues(snapshot))
    followup_notice = st.session_state.pop("agent_followup_notice", "")
    if followup_notice:
        st.success(followup_notice)

    active_open = actions[
        actions["Active"].eq("Yes")
        & ~actions["Status"].isin(["Resolved", "Auto-resolved"])
    ].copy()
    critical = active_open[active_open["Severity"].eq("Critical")]
    escalations = active_open[active_open["Escalation"].ne("None")]
    production_risk = active_open[
        active_open["Production Impact"].str.startswith("At risk", na=False)
    ]

    metric_columns = st.columns(4)
    metric_columns[0].metric(
        "Open actions",
        f"{len(active_open):,}",
        help="All currently active discrepancies across buyers.",
        border=True,
    )
    metric_columns[1].metric(
        "Critical",
        f"{len(critical):,}",
        help="Issues requiring immediate attention.",
        border=True,
    )
    metric_columns[2].metric(
        "Escalations due",
        f"{len(escalations):,}",
        help="Issues old enough to require buyer or management follow-up.",
        border=True,
    )
    metric_columns[3].metric(
        "Production risks",
        f"{len(production_risk):,}",
        help="Short receipts linked to the latest production/BOM demand.",
        border=True,
    )

    st.subheader(
        "Buyer workspace",
        help="Select one buyer to see only their assigned issues.",
    )
    open_counts = active_open.groupby("Buyer Name").size().to_dict()
    buyer_options = sorted(
        actions["Buyer Name"].dropna().unique(),
        key=lambda buyer: (-int(open_counts.get(buyer, 0)), buyer),
    )
    if not buyer_options:
        st.info("No buyer assignments are available yet.")
        return
    selected_buyer = st.selectbox(
        "Choose buyer workspace",
        buyer_options,
        index=0,
        format_func=lambda buyer: (
            f"{buyer} ({int(open_counts.get(buyer, 0))})"
        ),
        key="agent_buyer_workspace",
        help="The number beside each name is that buyer's open-action count.",
        width="stretch",
    )
    if not selected_buyer:
        st.info("Choose a buyer to open their issue lists.")
        return

    buyer_actions = actions[
        actions["Buyer Name"].eq(selected_buyer)
    ].copy()
    buyer_open = buyer_actions[
        buyer_actions["Active"].eq("Yes")
        & ~buyer_actions["Status"].isin(["Resolved", "Auto-resolved"])
    ]
    buyer_metrics = st.columns(4)
    buyer_metrics[0].metric(
        "Total open",
        f"{len(buyer_open):,}",
        border=True,
    )
    for metric_column, severity, icon in zip(
        buyer_metrics[1:],
        ["Critical", "High", "Medium"],
        ["🔴", "🟠", "🟡"],
    ):
        metric_column.metric(
            f"{icon} {severity}",
            f"{int(buyer_open['Severity'].eq(severity).sum()):,}",
            border=True,
        )

    filter_columns = st.columns([1.35, 1, 1])
    with filter_columns[0]:
        buyer_search = st.text_input(
            "Search this buyer's issues",
            placeholder="Part number, part name, or gate entry",
            key="agent_buyer_issue_search",
            help="Search only inside the selected buyer's workspace.",
        )
    with filter_columns[1]:
        supplier_options = sorted(
            supplier
            for supplier in buyer_actions[
                "Supplier Name"
            ].dropna().unique()
            if clean_text(supplier)
        )
        selected_agent_supplier = st.selectbox(
            "Supplier",
            ["All suppliers", *supplier_options],
            key=(
                "agent_buyer_supplier_"
                + re.sub(
                    r"[^a-z0-9]+",
                    "_",
                    str(selected_buyer).lower(),
                ).strip("_")
            ),
            help="Choose one supplier within the selected buyer's workspace.",
        )
    with filter_columns[2]:
        buyer_issue_types = st.multiselect(
            "Problem type",
            sorted(buyer_actions["Issue Type"].dropna().unique()),
            placeholder="All problem types",
            key="agent_buyer_issue_types",
            help="Limit the lists to selected control failures.",
        )
    if buyer_search.strip():
        search_text = buyer_search.strip()
        search_mask = pd.Series(False, index=buyer_actions.index)
        for column in [
            "Part Number",
            "Part Name",
            "Gate Entry No",
        ]:
            search_mask |= buyer_actions[column].astype(str).str.contains(
                search_text,
                case=False,
                na=False,
                regex=False,
            )
        buyer_actions = buyer_actions[search_mask]
    if selected_agent_supplier != "All suppliers":
        buyer_actions = buyer_actions[
            buyer_actions["Supplier Name"].eq(selected_agent_supplier)
        ]
    if buyer_issue_types:
        buyer_actions = buyer_actions[
            buyer_actions["Issue Type"].isin(buyer_issue_types)
        ]

    severity_groups = [
        (
            "Critical",
            buyer_actions[
                buyer_actions["Active"].eq("Yes")
                & buyer_actions["Severity"].eq("Critical")
            ],
        ),
        (
            "High",
            buyer_actions[
                buyer_actions["Active"].eq("Yes")
                & buyer_actions["Severity"].eq("High")
            ],
        ),
        (
            "Medium",
            buyer_actions[
                buyer_actions["Active"].eq("Yes")
                & buyer_actions["Severity"].eq("Medium")
            ],
        ),
        (
            "Verified resolved",
            buyer_actions[
                buyer_actions["Active"].eq("No")
                & buyer_actions["Status"].eq("Auto-resolved")
            ],
        ),
    ]
    tab_labels = [
        f"🔴 Critical ({len(severity_groups[0][1])})",
        f"🟠 High ({len(severity_groups[1][1])})",
        f"🟡 Medium ({len(severity_groups[2][1])})",
        f"🟢 Verified resolved ({len(severity_groups[3][1])})",
    ]
    severity_tabs = st.tabs(tab_labels)
    for tab, (group_name, group) in zip(
        severity_tabs,
        severity_groups,
    ):
        with tab:
            if group.empty:
                if group_name == "Verified resolved":
                    st.info("No verified resolved issues match these filters.")
                else:
                    st.success(
                        f"No {group_name.lower()} issues match these filters."
                    )
                continue

            group = group.copy()
            group["_age_numeric"] = pd.to_numeric(
                group["Age (days)"],
                errors="coerce",
            ).fillna(0)
            group = group.sort_values(
                ["_age_numeric", "Escalation", "Part Number"],
                ascending=[False, True, True],
            ).drop(columns="_age_numeric").reset_index(drop=True)
            group["Production Risk"] = group["Production Impact"].map(
                lambda value: (
                    "At risk"
                    if clean_text(value).startswith("At risk")
                    else "—"
                )
            )
            visible_columns = [
                "Issue Type",
                "Gate Entry No",
                "Supplier Name",
                "Part Number",
                "Part Name",
                "Difference Qty",
                "Production Risk",
                "Age (days)",
                "Escalation",
                "Status",
            ]
            queue = group[visible_columns].copy()
            queue["Difference Qty"] = pd.to_numeric(
                queue["Difference Qty"],
                errors="coerce",
            ).fillna(0)
            queue["Age (days)"] = pd.to_numeric(
                queue["Age (days)"],
                errors="coerce",
            ).fillna(0).astype(int)
            st.caption(
                f"{selected_buyer} has {len(group):,} "
                f"{group_name.lower()} issue(s). Click a row for evidence "
                "and follow-up controls."
            )
            workspace_key = re.sub(
                r"[^a-z0-9]+",
                "_",
                f"{selected_buyer}_{group_name}".lower(),
            ).strip("_")
            selection = st.dataframe(
                queue,
                width="stretch",
                hide_index=True,
                height=min(460, 38 + len(queue) * 35),
                on_select="rerun",
                selection_mode="single-row",
                key=f"agent_workspace_{workspace_key}",
                column_config={
                    "Difference Qty": st.column_config.NumberColumn(
                        format="%.2f"
                    ),
                    "Age (days)": st.column_config.NumberColumn(
                        format="%d"
                    ),
                },
            )
            selected_rows = selection.selection.rows
            if selected_rows:
                render_agent_action_detail(
                    group.iloc[selected_rows[0]],
                    actions,
                )

    with st.expander("Agent rules and complete audit history"):
        st.markdown(
            """
            - Buyers see all assigned issues separated into Critical, High,
              Medium, and Verified Resolved lists.
            - Click a row to review the invoice, receipt, source evidence,
              production impact, and follow-up workflow.
            - Buyers cannot manually close an issue. The agent sets
              `Auto-resolved` only after the discrepancy disappears from the
              refreshed source snapshot.
            """
        )
        st.dataframe(actions, width="stretch", hide_index=True)
        st.download_button(
            "Download complete action audit CSV",
            data=actions.to_csv(index=False).encode("utf-8"),
            file_name="inwarding_agent_action_audit.csv",
            mime="text/csv",
            key="agent_workspace_audit_download",
        )


def render_setup() -> None:
    st.header(
        "Setup",
        help=(
            "Connects read-only Google Sheets access and explains the shared app "
            "configuration required before refresh controls can be used."
        ),
    )
    st.write(
        "The app uses saved Google Sheet snapshots for inwarding and "
        "read-only Google data for production consumption."
    )
    st.markdown(
        """
        For two people working together:

        - Code changes should happen through GitHub branches.
        - App usage can happen through one shared Streamlit URL.
        - The master refresh maintains the saved buyer-supplier ownership mapping used across the app.
        - Inwarding Parts keeps showing its previous Direct Gate Entry snapshot until you press Refresh.
        - For private Google Sheets, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`, paste the service-account JSON values, and share the sheet with that service-account email.
        - Configure `[google_oauth]` for the private inwarding, production, and BOM sheets.
        """
    )


def render_documentation() -> None:
    st.header(
        "Documentation",
        help=(
            "A plain-language reference for source data, calculation rules, "
            "status definitions, refresh behaviour, and agent workflows."
        ),
    )
    source_rows = [
        {
            "Purpose": "Daily plan and total production (Visibility)",
            "Sheet / tab": "Weekly_Plan & Results_Rev.1",
            "Link": sheet_url(PRODUCTION_SHEET_ID, 1380714334),
        },
        {
            "Purpose": "Variant plan, Visibility, explicit P-VIN, VNA and Free VIN",
            "Sheet / tab": "Production Plan Breakup_Rev.1",
            "Link": sheet_url(PRODUCTION_SHEET_ID, 643919697),
        },
        {
            "Purpose": "Model/colour mix used to allocate plan and production",
            "Sheet / tab": "VIN_Details_Daily",
            "Link": sheet_url(PRODUCTION_SHEET_ID, 1559707768),
        },
        {
            "Purpose": "Model + colour to FG",
            "Sheet / tab": "Daywise SKU Plan",
            "Link": sheet_url(PRODUCTION_SHEET_ID, 514997806),
        },
        {
            "Purpose": "FG to part quantity",
            "Sheet / tab": "Exploded BOM",
            "Link": sheet_url(BOM_SHEET_ID, 1116146509),
        },
        {
            "Purpose": "Today's opening-stock baseline",
            "Sheet / tab": "SCM Plan Working Revision 1 · Summary · System Opening Stock",
            "Link": sheet_url(SCM_REV_SHEET_ID, 0),
        },
        {
            "Purpose": "Inwarding / direct gate entry",
            "Sheet / tab": "Inwarding snapshot",
            "Link": INWARDING_SHEET_URL,
        },
        {
            "Purpose": "Part/supplier to buyer ownership",
            "Sheet / tab": "Buyer mapping",
            "Link": BUYER_MAPPING_SHEET_URL,
        },
    ]
    glossary = pd.DataFrame(
        [
            ("Daily Production Plan", "Vehicle target for the selected production date."),
            (
                "Total Production So Far",
                "Variant-wise Visibility: P-VIN + VNA + Free VIN. Some internal "
                "tables still label this field Produced So Far; it is total production, "
                "not Produced P-VIN.",
            ),
            (
                "Produced P-VIN",
                "Explicit P-VIN quantity from the production source. It alone drives "
                "Produced-PVIN BOM consumption and the calculated Physical Stock.",
            ),
            (
                "Generated P-VIN",
                "Variant-wise generated quantity entered in the app until a generated-"
                "P-VIN source is integrated. It drives System Stock and COGI.",
            ),
            ("Planned Part Consumption", "Total part units needed for the complete daily variant plan."),
            (
                "Consumed So Far",
                "BOM demand attributed to total production so far. It is used only to "
                "calculate how much of the daily plan remains.",
            ),
            ("Remaining Part Need", "Part units still needed to finish the plan before considering current stock."),
            (
                "Today's OS",
                "Opening-stock baseline for the selected day, currently sourced from "
                "SCM Summary → System Opening Stock when an exact part match exists.",
            ),
            (
                "Parts Inwarded",
                "Current implementation: qualifying Invoice Qty recorded for the part "
                "on the selected date in the saved inwarding snapshot.",
            ),
            (
                "Parts Outwarded",
                "Produced-PVIN BOM consumption plus any saved additional outwarding records.",
            ),
            (
                "Tomorrow's OS",
                "Today's OS + total inwarding based on Invoice Qty − total "
                "production/servicing/rework outwarding.",
            ),
            ("System Stock", "Today's OS less BOM consumption from generated P-VINs, floored at zero."),
            ("Physical Stock", "Today's OS less BOM consumption from produced P-VINs."),
            (
                "Supplier Required Qty",
                "max(Remaining Part Need − System Stock, 0). This is the supplier/MRP action quantity.",
            ),
            (
                "Operational Shortage",
                "max(Remaining Part Need − Physical Stock, 0). This is the production-line risk quantity.",
            ),
            ("COGI Qty", "Generated consumption that could not post because System Stock reached zero."),
            ("Stock Delta", "Physical Stock − System Stock. A difference is not automatically an error."),
            (
                "Expected Delta",
                "Generated-PVIN consumption − Produced-PVIN consumption − COGI. "
                "This is the expected timing difference between the two stock views.",
            ),
            ("Unexplained Delta", "Physical-minus-System difference after removing expected P-VIN timing and COGI."),
            (
                "Delta Flag",
                "Review when the absolute Unexplained Delta exceeds the selected threshold; "
                "otherwise Within expected.",
            ),
            (
                "Horizon Demand",
                "Remaining part need today plus estimated BOM demand from positive "
                "vehicle plans through the selected seven-day or month-end horizon.",
            ),
            (
                "Potential Excess Qty",
                "max(Physical Stock − Horizon Demand, 0). This is a screening signal, "
                "not confirmed excess.",
            ),
            (
                "Coverage Multiple",
                "Physical Stock divided by Horizon Demand. It does not yet include "
                "safety stock, open orders, lead time or MOQ.",
            ),
            (
                "Plan / Produced",
                "Today's total vehicle plan versus Total Production completed so far. "
                "The produced figure is not Produced P-VIN.",
            ),
            (
                "Line-risk Parts",
                "Count of parts with known Physical Stock where remaining production "
                "need is greater than physically available stock.",
            ),
            (
                "Unmapped / Missing Stock",
                "Unique parts with either no mapped buyer or no usable stock data. "
                "They require data correction before reliable assignment or assessment.",
            ),
            (
                "Overdue Commitments",
                "Saved supplier follow-ups due on or before the plan date that are "
                "not marked Received.",
            ),
            (
                "Data Freshness",
                "Age of the oldest required saved source used by the control cycle.",
            ),
            (
                "Data Health",
                "Ready only when the required snapshots are saved and the current "
                "inventory view has no stock-data gaps; otherwise Attention.",
            ),
        ],
        columns=["Column", "Meaning"],
    )

    st.caption(
        "Choose a topic below. Only one guide is shown at a time, so you can "
        "find an answer without scrolling through the complete manual."
    )
    st.info(
        "New here? Start with **Quick start**, then use the ⓘ icons beside "
        "headings anywhere in the app for a short explanation."
    )

    (
        quick_start_tab,
        inventory_tab,
        data_tab,
        inwarding_tab,
        planning_tab,
        glossary_tab,
    ) = st.tabs(
        [
            "Start here",
            "Inventory maths",
            "Data & mapping",
            "Inwarding agent",
            "Shortage & excess",
            "Glossary",
        ]
    )

    with quick_start_tab:
        st.subheader(
            "Six-stage daily workflow",
            help="The shortest path from refreshed source data to assigned action.",
        )
        workflow_steps = [
            (
                "1 · Overview",
                "Check source freshness and required-agent status before trusting decisions.",
            ),
            (
                "2 · Live Flow",
                "Review variant plan, total production and separate Generated/Produced P‑VIN controls.",
            ),
            (
                "3 · Stock",
                "Use **Stock Health** for critical, short, missing, and delta-review queues.",
            ),
            (
                "4 · Requirements",
                "Review today, seven-day, month and potential-excess requirements.",
            ),
            (
                "5 · Action",
                "Use **Action Centre** for buyer queues, commitments, and PPC recovery.",
            ),
            (
                "6 · Verify",
                "Use **Audit & Evidence** to reconcile movements and verify resolution.",
            ),
        ]
        for start in range(0, len(workflow_steps), 3):
            workflow_columns = st.columns(3)
            for column, (title, description) in zip(
                workflow_columns,
                workflow_steps[start : start + 3],
            ):
                with column:
                    with st.container(border=True):
                        st.markdown(f"**{title}**")
                        st.caption(description)

        st.subheader(
            "Where should I go?",
            help="Use this table to choose the correct page for the task you are performing.",
        )
        st.dataframe(
            pd.DataFrame(
                [
                    (
                        "Inventory Management Agent · Overview",
                        "Control-cycle readiness, today's assigned agent actions, "
                        "headline production, shortage, mapping, and commitment indicators",
                    ),
                    (
                        "Inventory Management Agent · Live Flow",
                        "Variant plan, total production, Generated/Produced P‑VIN, BOM impact and end-to-end part evidence",
                    ),
                    (
                        "Inventory Management Agent · Stock Health",
                        "Healthy, below-required, critical, missing-stock and delta-review queues",
                    ),
                    (
                        "Inventory Management Agent · Requirements",
                        "Today, seven-day, month and potential-excess requirements",
                    ),
                    (
                        "Inventory Management Agent · Action Centre",
                        "Buyer queues, supplier commitments, message drafts, and PPC recovery scenarios",
                    ),
                    (
                        "Inventory Management Agent · Audit & Evidence",
                        "Readiness, movement reconciliation, master data, calculation evidence and resolution history",
                    ),
                    ("Inwarding Parts", "Check gate entries and buyer-owned discrepancies"),
                    ("Outwarding Parts", "Review calculated daily production consumption"),
                    ("Setup", "Connect Google and confirm refresh access"),
                ],
                columns=["Page", "Use it for"],
            ),
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("How refresh and saved copies work"):
            st.markdown(
                """
                - The app keeps showing the **last saved copy** until Refresh is pressed.
                - **Refresh all sources** updates production, BOM, SCM stock, outwarding,
                  inwarding, buyer mapping, and discrepancy checks.
                - **Auto-refresh every 15 minutes** runs that same complete workflow
                  while this app session is open and Google remains connected.
                - A manual master refresh resets the 15-minute countdown.
                - A failed source keeps its previous saved copy.
                - Google access is **read-only**; this app does not edit the source sheets.
                - **Total production so far** is Visibility: P-VIN + VNA + Free
                  VIN at the source's latest update.
                - **Produced P-VIN** is read only from the explicit P-VIN
                  column. It is never inferred from total production.
                """
            )
        st.subheader(
            "Overview KPI guide",
            help=(
                "The exact meaning of the five decision indicators shown on the "
                "Overview page. Hover over the ⓘ beside a card for the same summary."
            ),
        )
        st.dataframe(
            pd.DataFrame(
                [
                    (
                        "Plan / produced",
                        "Today's vehicle target / total vehicles completed so far",
                        "Requirements",
                    ),
                    (
                        "Line-risk parts",
                        "Parts with known Physical Stock and a positive operational shortage",
                        "Stock Health",
                    ),
                    (
                        "Supplier quantity required",
                        "Sum of positive remaining need after System Stock",
                        "Requirements",
                    ),
                    (
                        "Unmapped / missing stock",
                        "Parts with no buyer mapping or no usable stock value",
                        "Audit & Evidence",
                    ),
                    (
                        "Overdue commitments",
                        "Supplier follow-ups due by the plan date and not marked Received",
                        "Action Centre",
                    ),
                ],
                columns=["Indicator", "What it signifies", "Button opens"],
            ),
            width="stretch",
            hide_index=True,
        )

    with inventory_tab:
        st.subheader(
            "How the two requirements are calculated",
            help="System Stock drives suppliers; Physical Stock drives operational line risk.",
        )
        st.info(
            "**Generated P-VINs reduce System Stock. Only the explicit Produced "
            "P-VIN quantity reduces Physical Stock. Total production is reported "
            "separately and is never substituted for Produced P-VIN.**"
        )
        formula_columns = st.columns(2)
        with formula_columns[0]:
            with st.container(border=True):
                st.markdown("**System position**")
                st.code("max(Today's OS − generated-PVIN consumption, 0)")
            with st.container(border=True):
                st.markdown("**Supplier Required Qty**")
                st.code("max(remaining part need − System Stock, 0)")
        with formula_columns[1]:
            with st.container(border=True):
                st.markdown("**Physical position**")
                st.code("Today's OS − produced-PVIN consumption")
            with st.container(border=True):
                st.markdown("**Operational Shortage**")
                st.code("max(remaining part need − physical stock, 0)")
        st.caption(
            "Tomorrow's OS is calculated as Today's OS + Parts Inwarded − Parts "
            "Outwarded. Supplier inwarding uses Invoice Qty; Receipt Qty remains "
            "visible for discrepancy control."
        )
        st.subheader(
            "Why the two shortage quantities differ",
            help=(
                "Supplier Required Qty uses the system position, while Operational "
                "Shortage uses the physical position."
            ),
        )
        difference_columns = st.columns(2)
        with difference_columns[0]:
            with st.container(border=True):
                st.markdown("**Supplier / MRP view**")
                st.caption(
                    "Use Supplier Required Qty to arrange supply. It subtracts "
                    "System Stock from the remaining part demand."
                )
        with difference_columns[1]:
            with st.container(border=True):
                st.markdown("**Production-line view**")
                st.caption(
                    "Use Operational Shortage to assess line risk. It subtracts "
                    "Physical Stock from the same remaining part demand."
                )
        st.markdown(
            """
            - If **Operational Shortage is higher**, Physical Stock is below
              System Stock for the uncovered quantity.
            - If **Supplier Required Qty is higher**, System Stock is below
              Physical Stock for the uncovered quantity.
            - When both results are above zero:
              `Operational Shortage − Supplier Required Qty = System Stock − Physical Stock`.
            - The difference is not automatically a discrepancy. The app flags
              only the **Unexplained Delta** after allowing for P-VIN timing and COGI.
            """
        )
        with st.expander("Show a worked example"):
            st.markdown(
                """
                One part is used per vehicle. Today's OS is **50**, **50 P-VINs**
                are generated, and **30 P-VINs** are produced.

                | Calculation | Result |
                |---|---:|
                | System Stock = max(50 − 50, 0) | 0 |
                | Physical Stock = 50 − 30 | 20 |
                | Raw Stock Delta | 20 |
                | Expected timing delta | 20 |
                | Unexplained Delta | **0** |

                The 20-unit System-versus-Physical difference is expected and is not flagged.
                """
            )
        with st.expander("Current stock and movement limitations"):
            st.markdown(
                """
                - For an exact SCM Summary match, Today's OS, System Stock, and
                  Physical Stock are source/calculation-controlled and are not
                  directly editable. Remarks remain editable.
                - If SCM stock is unavailable, Today's OS can be entered manually.
                - Audit & Evidence → Correction requests records the proposed
                  value, reason, requester, approver and decision. It does not
                  overwrite source-controlled stock; Google identity autofill and
                  ERP/Sheet write-back still require the future access-control workflow.
                - Separate CPW/HS02-return and rework-return feeds are **not
                  independently integrated yet**. The current inwarding total
                  comes from qualifying Invoice Qty rows in the saved inwarding snapshot.
                - Tomorrow's OS is a movement calculation, not a physical count.
                  A negative result signals that the opening stock or recorded
                  movements need review; it must not be interpreted as real negative stock.
                """
            )

    with data_tab:
        st.subheader(
            "From vehicle plan to part requirement",
            help="The source-to-output path used for every part-level calculation.",
        )
        st.markdown(
            "**Vehicle plan & actuals** → **model + colour** → **finished-good "
            "number** → **exploded BOM** → **part demand** → **SCM stock match**"
        )
        rule_columns = st.columns(2)
        with rule_columns[0]:
            with st.container(border=True):
                st.markdown("**Production mapping**")
                st.markdown(
                    """
                    - Produced So Far = variant-wise **Visibility** from Production
                      Plan Breakup (or the available shift/actual total when
                      Visibility is absent). This is **Total Production So Far**,
                      not Produced P-VIN.
                    - Produced P-VIN is read only from the explicit P-VIN field.
                      If that field is absent, the app reports it as unavailable
                      rather than copying total production.
                    - Generated P-VIN remains a controlled app input until its
                      source feed is integrated.
                    - SKU mapping converts model + colour to FG.
                    - BOM converts FG to component quantities.
                    - Whole vehicles are allocated; no fractional vehicle is created.
                    """
                )
        with rule_columns[1]:
            with st.container(border=True):
                st.markdown("**Stock matching**")
                st.markdown(
                    """
                    - SCM stock joins on **exact part number** only.
                    - Revision-like matches are flagged separately.
                    - Parts absent from SCM Summary need a manual Today's OS.
                    - Unverified matches are excluded from shortage alerts.
                    """
                )
        with st.expander("Colour-mix fallback rule"):
            st.write(
                "If today's colour mix is blank, the app uses the most recent "
                "saved non-zero mix for that model and displays the fallback date."
            )
        with st.expander("HEADER PARTS BOM gap-fill rule"):
            st.markdown(
                """
                - The primary production mapping remains **Daywise SKU Plan**, and
                  the primary component source remains the connected BOM workbook.
                - A reviewed local **HEADER PARTS** supplement fills only verified
                  current-model model/colour mappings absent from Daywise SKU Plan.
                - For a supplemented finished good missing from Exploded BOM, the
                  app reconstructs its component quantities from Raw BOM by
                  multiplying quantities through each explosion level.
                - Existing connected mappings are never overwritten by the supplement.
                - The current supplement adds six verified finished-good mappings:
                  five Gen‑3 X+ 5.2 colour combinations and M3 RX 9.1 KWH
                  Champions edition.
                - The master-refresh result explicitly reports when this gap fill
                  was applied, so its use remains visible and auditable.
                """
            )
        st.subheader(
            "Connected source register",
            help="The Google Sheet tabs used by the app and the job performed by each one.",
        )
        st.dataframe(
            pd.DataFrame(source_rows),
            use_container_width=True,
            hide_index=True,
            column_config={"Link": st.column_config.LinkColumn("Open source")},
        )

    with inwarding_tab:
        st.subheader(
            "How the discrepancy agent works",
            help="How inwarding exceptions are assigned, reviewed, escalated, and verified as resolved.",
        )
        agent_columns = st.columns(3)
        agent_steps = [
            (
                "Detect",
                "The agent checks the refreshed inwarding snapshot for control and quantity issues.",
            ),
            (
                "Assign",
                "Buyer ownership is mapped by exact part first, then by supplier.",
            ),
            (
                "Verify",
                "An issue closes only after a later refresh confirms the discrepancy has disappeared.",
            ),
        ]
        for column, (title, description) in zip(agent_columns, agent_steps):
            with column:
                with st.container(border=True):
                    st.markdown(f"**{title}**")
                    st.caption(description)
        st.markdown(
            """
            - **Gate Entry No** is retained so each issue can be checked against the main inwarding table.
            - Quantity discrepancy compares the inwarding control quantities,
              including Invoice Qty and Receipt Qty; inventory System-versus-
              Physical timing differences are not automatically inwarding discrepancies.
            - Every buyer sees separate **Critical, High, Medium, and Verified resolved** queues.
            - Adding a note does **not** resolve an issue.
            - The audit log retains first detected, last checked, acknowledgement,
              resolution, notes, and escalation state.
            """
        )
        st.info(
            "To fact-check an issue: choose the buyer → open its severity tab → "
            "copy the Gate Entry No → search for it in the inwarding table above."
        )

    with planning_tab:
        st.subheader(
            "Shortage and excess planning",
            help=(
                "How the agents change their demand window, prioritize shortages, "
                "and screen for possible overstock."
            ),
        )
        st.dataframe(
            pd.DataFrame(
                [
                    ("Today", "Remaining demand after production so far"),
                    ("Rolling 7 Days", "Today plus the next six calendar days"),
                    ("Remaining Month", "All remaining positive daily plans through month-end"),
                ],
                columns=["Horizon", "Demand included"],
            ),
            use_container_width=True,
            hide_index=True,
        )
        severity_columns = st.columns(4)
        severity_cards = [
            ("🔴 Critical", "System Stock indicates supplier need on the first plan day"),
            ("🟠 High", "System Stock indicates supplier need within two days"),
            ("🟡 Medium", "System Stock indicates supplier need later in the horizon"),
            ("⚪ Missing stock", "No verified opening stock; excluded from requirement counts"),
        ]
        for column, (title, description) in zip(
            severity_columns,
            severity_cards,
        ):
            with column:
                with st.container(border=True):
                    st.markdown(f"**{title}**")
                    st.caption(description)
        st.subheader(
            "Supplier follow-up",
            help="The information required to save a complete, accountable supplier action.",
        )
        st.markdown(
            """
            A saved action requires **Supplier Status, Next Expected Qty, Expected
            Delivery, Next Follow-up, mapped Follow-up Owner, and Notes**.

            - **Required By** is the first date cumulative RM demand exceeds System Stock.
            - Default follow-up is scheduled two days before Required By.
            - Follow-up Owner is locked to the buyer mapped to the part.
            - A delayed supplier or late ETA triggers a PPC plan-adjustment recommendation.
            - Recommendations state the required quantity, timing response, and accountable owner.
            """
        )
        st.info(
            "Action Centre → Buyer work queues brings Critical parts, suppliers "
            "needing contact, Required Qty, Required By, Confirmed Incoming Qty, "
            "Expected Delivery, and Recommended Next Action into one table. The "
            "Supplier filter is always limited to suppliers mapped to the selected buyer."
        )
        st.warning(
            "The app saves follow-up schedules locally. It does not automatically "
            "email or message suppliers."
        )
        st.subheader(
            "Phase‑1 excess prevention",
            help=(
                "What the current excess screen can conclude from available data "
                "and which missing inputs prevent an automatic supply decision."
            ),
        )
        excess_columns = st.columns(2)
        with excess_columns[0]:
            with st.container(border=True):
                st.markdown("**Current screening rule**")
                st.code("max(Physical Stock − Horizon Demand, 0)")
                st.caption(
                    "Available for Rolling 7 Days and Remaining Month. Buyer and "
                    "supplier filters create a focused review queue."
                )
        with excess_columns[1]:
            with st.container(border=True):
                st.markdown("**Decision safeguard**")
                st.caption(
                    "The result is labelled Potential excess because open POs, "
                    "confirmed incoming supply, safety stock, lead time, MOQ, shelf "
                    "life and part value are not yet integrated."
                )
        st.markdown(
            """
            - **No demand in horizon** means Physical Stock exists but calculated
              part demand is zero through the selected horizon.
            - **More than 2× horizon demand** is a prioritization signal, not an
              instruction to cancel supply.
            - Buyers must validate open orders and safety stock before deferring,
              reducing, or cancelling any delivery.
            - The current agent never changes a purchase commitment automatically.
            """
        )
        st.subheader(
            "Agent lifecycle and current capabilities",
            help="How each agent moves an exception from detection to verified resolution.",
        )
        st.markdown(
            "**Observe → Detect → Prioritize → Assign → Recommend/Act → Follow up → Verify**"
        )
        st.dataframe(
            pd.DataFrame(
                [
                    (
                        "Data Readiness & Mapping",
                        "Active",
                        "Blocks unreliable conclusions when stock, BOM, variant, buyer or supplier data is missing.",
                    ),
                    (
                        "P‑VIN Consumption",
                        "Active with controlled input",
                        "Keeps total production separate; Generated P‑VIN drives System consumption and explicit Produced P‑VIN drives Physical consumption.",
                    ),
                    (
                        "Inventory Reconciliation",
                        "Active",
                        "Separates expected P‑VIN timing and COGI, creates persistent unexplained-delta cases and verifies resolution.",
                    ),
                    (
                        "Shortage Prevention",
                        "Active",
                        "Calculates today/7-day/month requirements, required-by date, severity and buyer ownership.",
                    ),
                    (
                        "Excess Prevention",
                        "Indicative",
                        "Screens seven-day and month-end potential excess. Open POs, safety stock and lead time are still required before cancellation decisions.",
                    ),
                    (
                        "Inwarding Control",
                        "Active",
                        "Checks gate entry, invoice/receipt quantity, unloading age and buyer assignment; resolution is refresh-verified.",
                    ),
                    (
                        "Supplier Action",
                        "Active with approval",
                        "Tracks quantity, ETA and follow-up and drafts expedite/defer actions; a human must approve and send them.",
                    ),
                    (
                        "PPC Plan Response",
                        "Planning estimate",
                        "Shows affected variants, production caps and resequencing scenarios without automatically changing the plan.",
                    ),
                ],
                columns=["Agent", "Status", "What it does"],
            ),
            width="stretch",
            hide_index=True,
        )

    with glossary_tab:
        st.subheader(
            "Column glossary",
            help="Searchable definitions for the main inventory and requirement fields.",
        )
        glossary_search = st.text_input(
            "Find a term",
            placeholder="For example: physical stock or required qty",
            key="documentation_glossary_search",
        )
        filtered_glossary = glossary
        if glossary_search.strip():
            glossary_term = glossary_search.strip()
            glossary_mask = pd.Series(False, index=glossary.index)
            for column in glossary.columns:
                glossary_mask |= glossary[column].astype(str).str.contains(
                    glossary_term,
                    case=False,
                    na=False,
                    regex=False,
                )
            filtered_glossary = glossary[glossary_mask]
        st.dataframe(
            filtered_glossary,
            use_container_width=True,
            hide_index=True,
            height=360,
        )


def perform_master_refresh(
    credentials: Credentials,
) -> tuple[list[str], list[str]]:
    """Refresh every Google-backed snapshot used by the active app pages."""
    completed: list[str] = []
    failed: list[str] = []
    refreshed_sources: dict[str, pd.DataFrame] = {}

    try:
        for key, source in SOURCE_SHEETS.items():
            source_df, _ = load_google_sheet_oauth(
                source["url"],
                credentials,
            )
            refreshed_sources[key] = source_df
        for key, source_df in refreshed_sources.items():
            save_source_cache(SOURCE_SHEETS[key]["cache"], source_df)
        completed.append(
            f"Production plan, BOM and SCM stock ({len(refreshed_sources)} tabs)"
        )
    except Exception as exc:
        refreshed_sources = {}
        failed.append(f"Production/BOM/SCM sources — {exc}")

    if refreshed_sources:
        try:
            refreshed_sources, supplement_diagnostics = (
                apply_header_parts_supplement(refreshed_sources)
            )
            production, _ = build_daily_production(
                refreshed_sources["vin_details"],
                refreshed_sources["sku_map"],
            )
            production_usage, _ = compute_production_part_usage(
                production,
                refreshed_sources["exploded_bom"],
                refreshed_sources["raw_bom"],
                refreshed_sources["part_types"],
                refreshed_sources["suppliers"],
            )
            computed_usage = combine_manual_outwarding(
                production_usage,
                pd.DataFrame(
                    columns=TABLES["outwarding_parts"]["columns"]
                ),
            )
            cache_copy = computed_usage.copy()
            if not cache_copy.empty:
                cache_copy["Usage Date"] = pd.to_datetime(
                    cache_copy["Usage Date"],
                    errors="coerce",
                ).dt.strftime("%Y-%m-%d")
            save_source_cache(COMPUTED_USAGE_CACHE_PATH, cache_copy)
            completed.append(
                f"Outwarding production usage ({len(cache_copy):,} rows)"
            )
            if supplement_diagnostics["supplemental_header_mappings"]:
                completed.append(
                    "HEADER PARTS gap fill "
                    f"({supplement_diagnostics['supplemental_header_mappings']:,} "
                    "SKU mappings; "
                    f"{supplement_diagnostics['supplemental_exploded_fgs']:,} "
                    "BOMs reconstructed)"
                )
        except Exception as exc:
            failed.append(f"Outwarding calculation — {exc}")

    try:
        inwarding_source, inwarding_tab = load_google_sheet_oauth(
            INWARDING_SHEET_URL,
            credentials,
        )
        buyer_source, buyer_tab = load_google_sheet_oauth(
            BUYER_MAPPING_SHEET_URL,
            credentials,
        )
        cleaned_inwarding = clean_inwarding_snapshot(inwarding_source)
        cleaned_buyer_mapping = clean_buyer_mapping_source(buyer_source)
        enriched_inwarding = enrich_inwarding_buyers(
            cleaned_inwarding,
            cleaned_buyer_mapping,
        )
        refreshed_actions = reconcile_agent_actions(
            build_agent_issues(enriched_inwarding)
        )
        save_inwarding_snapshot(cleaned_inwarding, inwarding_tab)
        save_source_cache(
            BUYER_MAPPING_CACHE_PATH,
            cleaned_buyer_mapping,
        )
        open_actions = int(
            (
                refreshed_actions["Active"].eq("Yes")
                & ~refreshed_actions["Status"].isin(
                    ["Resolved", "Auto-resolved"]
                )
            ).sum()
        )
        completed.append(
            f"Inwarding '{inwarding_tab}', buyer map '{buyer_tab}' and "
            f"discrepancy agent ({open_actions:,} open actions)"
        )
    except Exception as exc:
        failed.append(f"Inwarding and discrepancy agent — {exc}")

    try:
        spoc_table, spoc_tab = load_google_sheet_oauth(
            DEFAULT_SPOC_SUMMARY_SHEET_URL,
            credentials,
        )
        spoc_raw = pd.DataFrame(
            [spoc_table.columns.tolist()]
            + spoc_table.astype(str).to_numpy().tolist()
        )
        save_sheet_snapshot(
            spoc_raw,
            SPOC_SUMMARY_SNAPSHOT_CSV,
            SPOC_SUMMARY_SNAPSHOT_META,
            DEFAULT_SPOC_SUMMARY_SHEET_URL,
            "Google OAuth",
        )
        completed.append(
            f"Supplier Buyer Map '{spoc_tab}' ({len(spoc_table):,} rows)"
        )
    except Exception as exc:
        failed.append(f"Supplier Buyer Map — {exc}")

    return completed, failed


@st.fragment(run_every=AUTO_REFRESH_INTERVAL_SECONDS)
def render_auto_refresh_control(
    credentials: Credentials | None,
) -> None:
    """Run the master refresh every 15 minutes while this app session is open."""
    enabled = st.toggle(
        "Auto-refresh every 15 minutes",
        value=True,
        key="inventory_auto_refresh_enabled",
        disabled=credentials is None,
        help=(
            "While this page is open, run the same full workflow as Refresh all "
            "sources every 15 minutes. Previous saved copies remain available if "
            "a source fails."
        ),
    )
    now = datetime.now()
    if "inventory_auto_refresh_last_run" not in st.session_state:
        st.session_state["inventory_auto_refresh_last_run"] = now

    last_run = st.session_state["inventory_auto_refresh_last_run"]
    if not isinstance(last_run, datetime):
        last_run = now
        st.session_state["inventory_auto_refresh_last_run"] = last_run

    if enabled and credentials is not None:
        elapsed = (now - last_run).total_seconds()
        if elapsed >= AUTO_REFRESH_INTERVAL_SECONDS:
            with st.spinner("Running scheduled 15-minute refresh..."):
                completed, failed = perform_master_refresh(credentials)
            st.session_state["inventory_auto_refresh_last_run"] = now
            st.session_state["inventory_auto_refresh_result"] = {
                "completed": completed,
                "failed": failed,
                "finished_at": now.strftime("%H:%M"),
            }
            st.rerun()

        next_run = last_run + timedelta(
            seconds=AUTO_REFRESH_INTERVAL_SECONDS
        )
        st.caption(f"Next automatic refresh around {next_run:%H:%M}.")
    elif credentials is None:
        st.caption("Connect Google in Setup to enable automatic refresh.")


oauth_callback_settings = google_oauth_settings()
if oauth_callback_settings is not None and st.query_params.get("code"):
    if complete_google_oauth(oauth_callback_settings):
        st.session_state["google_oauth_connected_notice"] = True
        st.rerun()

if st.session_state.pop("google_oauth_connected_notice", False):
    st.toast("Google account connected with read-only Sheets access.", icon="✅")


st.markdown(
    """
    <style>
    :root {
        --im-ink: #172033;
        --im-muted: #667085;
        --im-border: #dfe4ec;
        --im-surface: #ffffff;
        --im-canvas: #f3f5f8;
        --im-accent: #ff4f38;
        --im-accent-soft: #fff0ed;
        --im-success: #169b62;
        --im-warning: #d97706;
        --im-danger: #dc2626;
    }
    .stApp { background: #f4f7fb; }
    .block-container {
        padding: 1.25rem 2rem 3rem;
        max-width: 1580px;
    }
    h1, h2, h3 {
        color: var(--im-ink);
        letter-spacing: -0.025em;
    }
    h1 { font-size: 2.25rem !important; }
    h2 { font-size: 1.55rem !important; }
    h3 { font-size: 1.08rem !important; }
    [data-testid="stHeader"] { background: rgba(244, 247, 251, 0.92); }
    [data-testid="stSidebar"] {
        background: #ffffff;
        border-right: 1px solid #e2e8f0;
    }
    [data-testid="stSidebar"] > div:first-child {
        padding-top: 0.85rem;
    }
    .sidebar-brand {
        align-items: center;
        display: flex;
        gap: 12px;
        margin: 4px 2px 28px;
        padding: 4px 2px;
    }
    .sidebar-brand-mark {
        align-items: center;
        background: linear-gradient(145deg, #ff6b55, #f43f2b);
        border-radius: 12px;
        box-shadow: 0 8px 16px rgba(255, 79, 56, 0.22);
        color: #ffffff;
        display: flex;
        font-size: 0.84rem;
        font-weight: 900;
        height: 42px;
        justify-content: center;
        letter-spacing: 0.03em;
        width: 42px;
    }
    .sidebar-brand-name {
        color: var(--im-ink);
        font-size: 1.05rem;
        font-weight: 850;
    }
    .sidebar-brand-subtitle {
        color: #98a2b3;
        font-size: 0.7rem;
        font-weight: 650;
        margin-top: 1px;
    }
    .sidebar-section-label {
        color: #98a2b3;
        font-size: 0.66rem;
        font-weight: 850;
        letter-spacing: 0.13em;
        margin: 0 8px 8px;
    }
    .sidebar-lower-label { margin-top: 28px; }
    .sidebar-context-card {
        align-items: center;
        background: #f8fafc;
        border: 1px solid var(--im-border);
        border-radius: 10px;
        display: flex;
        gap: 10px;
        margin: 0 4px;
        padding: 11px 12px;
    }
    .sidebar-context-dot {
        background: var(--im-success);
        border: 3px solid #d9f6e8;
        border-radius: 50%;
        height: 12px;
        width: 12px;
    }
    .sidebar-context-card b {
        color: var(--im-ink);
        display: block;
        font-size: 0.77rem;
    }
    .sidebar-context-card small {
        color: #98a2b3;
        display: block;
        font-size: 0.64rem;
        margin-top: 2px;
    }
    [data-testid="stSidebar"] [role="radiogroup"] {
        gap: 4px;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        border-radius: 9px;
        color: #586174;
        font-size: 0.88rem;
        font-weight: 700;
        margin: 0;
        padding: 8px 10px;
        transition: background 120ms ease, color 120ms ease;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover {
        background: #f8fafc;
        color: var(--im-ink);
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
        background: var(--im-accent-soft);
        color: var(--im-accent);
    }
    [data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {
        display: none;
    }
    .app-topbar {
        align-items: center;
        background: var(--im-surface);
        border: 1px solid var(--im-border);
        border-radius: 14px;
        display: flex;
        justify-content: space-between;
        margin-bottom: 14px;
        padding: 18px 22px;
    }
    .app-breadcrumb {
        color: var(--im-accent);
        font-size: 0.64rem;
        font-weight: 900;
        letter-spacing: 0.12em;
    }
    .app-topbar-title {
        color: var(--im-ink);
        font-size: 1.38rem;
        font-weight: 880;
        letter-spacing: -0.025em;
        margin-top: 4px;
    }
    .app-topbar-subtitle {
        color: var(--im-muted);
        font-size: 0.76rem;
        margin-top: 2px;
    }
    .app-topbar-user {
        align-items: center;
        display: flex;
        gap: 12px;
        text-align: right;
    }
    .app-topbar-user b {
        color: var(--im-ink);
        display: block;
        font-size: 0.77rem;
    }
    .app-topbar-user span {
        color: #98a2b3;
        display: block;
        font-size: 0.67rem;
        margin-top: 2px;
    }
    .app-user-avatar {
        align-items: center;
        background: #eef2f7;
        border: 1px solid var(--im-border);
        border-radius: 50%;
        color: #4b5565;
        display: flex;
        font-size: 0.65rem;
        font-weight: 900;
        height: 42px;
        justify-content: center;
        width: 42px;
    }
    .workflow-caption {
        align-items: center;
        color: #7c8799;
        display: flex;
        flex-wrap: wrap;
        font-size: 0.69rem;
        font-weight: 700;
        gap: 7px;
        margin: 16px 2px 8px;
    }
    .workflow-caption span {
        align-items: center;
        background: #e8edf4;
        border-radius: 50%;
        color: #566176;
        display: inline-flex;
        font-size: 0.62rem;
        font-style: normal;
        height: 20px;
        justify-content: center;
        width: 20px;
    }
    .workflow-caption i {
        color: #c2c8d2;
        font-style: normal;
    }
    [data-testid="stMain"] [role="radiogroup"][aria-label="Inventory workflow"] {
        background: #ffffff;
        border: 1px solid var(--im-border);
        border-radius: 12px;
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 5px;
        padding: 5px;
        width: 100%;
    }
    [data-testid="stMain"] [role="radiogroup"][aria-label="Inventory workflow"] label {
        align-items: center;
        border-radius: 8px;
        color: #687386;
        display: flex;
        font-size: 0.72rem;
        font-weight: 750;
        justify-content: center;
        min-height: 42px;
        padding: 7px 6px;
        text-align: center;
        width: 100%;
    }
    [data-testid="stMain"] [role="radiogroup"][aria-label="Inventory workflow"] label p {
        color: #687386 !important;
        font-size: inherit;
        line-height: 1.15;
        margin: 0;
        white-space: nowrap;
    }
    [data-testid="stMain"] [role="radiogroup"][aria-label="Inventory workflow"] label:has(input:checked) {
        background: var(--im-ink);
        color: #ffffff;
    }
    [data-testid="stMain"] [role="radiogroup"][aria-label="Inventory workflow"] label:has(input:checked) p {
        color: #ffffff !important;
    }
    [data-testid="stMain"] [role="radiogroup"][aria-label="Inventory workflow"] label > div:first-child {
        display: none;
    }
    [data-testid="stMain"] [role="radiogroup"][aria-label="Inventory workflow"] label > div:last-child {
        width: 100%;
    }
    [data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #dbe3ef;
        border-radius: 12px;
        padding: 14px 16px;
    }
    div[data-testid="stDataFrame"],
    div[data-testid="stDataEditor"] {
        background: #ffffff;
        border-radius: 12px;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: rgba(255,255,255,0.84);
        border-color: var(--im-border) !important;
        border-radius: 14px !important;
        box-shadow: 0 3px 12px rgba(23, 32, 51, 0.035);
    }
    .stButton > button[kind="primary"] {
        background: var(--im-accent);
        border-color: var(--im-accent);
        border-radius: 9px;
        box-shadow: none;
        font-weight: 800;
    }
    .stButton > button[kind="primary"]:hover {
        background: #ed3f2b;
        border-color: #ed3f2b;
    }
    .stButton > button:not([kind="primary"]),
    .stDownloadButton > button {
        background: #ffffff;
        border-color: var(--im-border);
        border-radius: 9px;
        color: var(--im-ink);
        font-weight: 750;
    }
    .agent-status-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin: 8px 0 22px;
    }
    .agent-status-card {
        background: #ffffff;
        border: 1px solid #dbe3ef;
        border-top: 4px solid #2563eb;
        border-radius: 12px;
        min-height: 112px;
        padding: 14px 15px;
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
    }
    .agent-status-card.ok { border-top-color: #16a34a; }
    .agent-status-card.warn { border-top-color: #d97706; }
    .agent-status-card.bad { border-top-color: #dc2626; }
    .agent-status-title {
        color: #0f172a;
        font-size: 0.9rem;
        font-weight: 800;
        margin-bottom: 9px;
    }
    .agent-status-pill {
        background: #eff6ff;
        border-radius: 999px;
        color: #1d4ed8;
        display: inline-block;
        font-size: 0.68rem;
        font-weight: 850;
        letter-spacing: 0.04em;
        padding: 5px 8px;
    }
    .agent-status-card.ok .agent-status-pill {
        background: #dcfce7;
        color: #166534;
    }
    .agent-status-card.warn .agent-status-pill {
        background: #fef3c7;
        color: #92400e;
    }
    .agent-status-card.bad .agent-status-pill {
        background: #fee2e2;
        color: #991b1b;
    }
    .agent-status-detail {
        color: #64748b;
        font-size: 0.78rem;
        margin-top: 9px;
    }
    .agent-action-pill {
        background: #eff6ff;
        border-radius: 999px;
        color: #1d4ed8;
        display: inline-block;
        font-size: 0.68rem;
        font-weight: 850;
        letter-spacing: 0.05em;
        padding: 5px 9px;
    }
    .agent-action-pill.warn {
        background: #fef3c7;
        color: #92400e;
    }
    .agent-action-pill.bad {
        background: #fee2e2;
        color: #991b1b;
    }
    .agent-action-pill.neutral {
        background: #e8eefc;
        color: #334e9e;
    }
    .flow-control-card {
        background: #ffffff;
        border: 1px solid #dbe3ef;
        border-radius: 12px;
        min-height: 160px;
        padding: 17px;
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
    }
    .flow-control-step {
        color: #2563eb;
        font-size: 0.72rem;
        font-weight: 850;
        letter-spacing: 0.04em;
        margin-bottom: 10px;
        text-transform: uppercase;
    }
    .flow-control-value {
        color: #0f172a;
        font-size: 1.18rem;
        font-weight: 850;
        line-height: 1.25;
        margin-bottom: 10px;
    }
    .flow-control-detail {
        color: #64748b;
        font-size: 0.77rem;
        line-height: 1.45;
    }
    .metric-card {
        border: 1px solid #dbe3ef;
        border-left: 6px solid #2563eb;
        border-radius: 12px;
        padding: 18px 18px;
        min-height: 112px;
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
    }
    .metric-label {
        color: #64748b;
        display: flex;
        gap: 7px;
        align-items: center;
        font-weight: 700;
        font-size: 0.9rem;
        margin-bottom: 12px;
    }
    .metric-info {
        color: #7c8799;
        cursor: help;
        flex: 0 0 auto;
        font-size: 0.88rem;
        line-height: 1;
    }
    .metric-value {
        color: #0f172a;
        font-size: 2rem;
        line-height: 1.1;
        font-weight: 800;
    }
    .control-tower-hero {
        align-items: center;
        background: linear-gradient(135deg, #f8fafc 0%, #eff6ff 100%);
        border: 1px solid #dbe3ef;
        border-radius: 14px;
        display: flex;
        gap: 24px;
        justify-content: space-between;
        margin: 6px 0 18px;
        padding: 22px 24px;
    }
    .control-tower-hero h2 {
        color: #0f172a;
        font-size: 1.55rem;
        margin: 4px 0 6px;
    }
    .control-tower-hero p {
        color: #64748b;
        margin: 0;
        max-width: 760px;
    }
    .control-tower-kicker {
        color: #2563eb;
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.08em;
    }
    .control-tower-badge {
        background: #ffffff;
        border: 1px solid #bfdbfe;
        border-radius: 999px;
        color: #1d4ed8;
        flex: 0 0 auto;
        font-size: 0.78rem;
        font-weight: 700;
        padding: 8px 12px;
    }
    @media (max-width: 800px) {
        .control-tower-hero {
            align-items: flex-start;
            flex-direction: column;
        }
    }
    .flow-step {
        border: 1px solid #dbe3ef;
        border-left: 5px solid #2563eb;
        border-radius: 8px;
        padding: 16px 18px;
        margin: 12px 0;
        background: #ffffff;
    }
    .agent-legend {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 10px 0 18px;
    }
    .agent-chip {
        border-radius: 999px;
        display: inline-block;
        font-size: 0.76rem;
        font-weight: 800;
        line-height: 1;
        padding: 7px 10px;
    }
    .agent-chip.critical {
        background: #fee2e2;
        color: #991b1b;
    }
    .agent-chip.high {
        background: #ffedd5;
        color: #9a3412;
    }
    .agent-chip.medium {
        background: #fef9c3;
        color: #854d0e;
    }
    .agent-chip.resolved {
        background: #dcfce7;
        color: #166534;
    }
    .agent-review-heading {
        align-items: center;
        background: #f8fafc;
        border: 1px solid #dbe3ef;
        border-radius: 10px;
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin: 18px 0 12px;
        padding: 12px 14px;
    }
    .agent-review-heading b {
        color: #0f172a;
    }
    .agent-review-heading > span:last-child {
        color: #64748b;
        font-size: 0.82rem;
        margin-left: auto;
    }
    .supplier-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 14px;
        margin: 10px 0 18px;
    }
    .supplier-card {
        border: 1px solid #dbe3ef;
        border-left: 5px solid #16a34a;
        border-radius: 8px;
        padding: 16px;
        background: #ffffff;
        min-height: 132px;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06);
    }
    .supplier-card.ok { border-left-color: #16a34a; }
    .supplier-card.warn { border-left-color: #d97706; }
    .supplier-card.bad { border-left-color: #dc2626; }
    .supplier-card-title {
        color: #0f172a;
        font-weight: 850;
        font-size: 1rem;
        line-height: 1.25;
        margin-bottom: 5px;
        min-height: 40px;
    }
    .supplier-card-owner {
        color: #64748b;
        font-weight: 700;
        font-size: 0.85rem;
        margin-bottom: 13px;
    }
    .supplier-card-kpis {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
    }
    .supplier-card-kpis span {
        color: #94a3b8;
        display: block;
        font-size: 0.72rem;
        font-weight: 800;
        text-transform: uppercase;
    }
    .supplier-card-kpis b {
        color: #0f172a;
        display: block;
        font-size: 1.05rem;
        margin-top: 3px;
    }
    .supplier-empty {
        border: 1px solid #dbe3ef;
        border-radius: 8px;
        padding: 18px;
        color: #64748b;
        background: #ffffff;
    }
    .rm-owner-cards {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin: 12px 0 20px;
    }
    .rm-owner-card {
        background: #ffffff;
        border: 1px solid #dbe3ef;
        border-left: 5px solid #f59e0b;
        border-radius: 10px;
        padding: 14px 15px;
    }
    .rm-owner-card.critical { border-left-color: #dc2626; }
    .rm-owner-name {
        color: #0f172a;
        font-size: 0.92rem;
        font-weight: 800;
        margin-bottom: 12px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .rm-owner-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
    }
    .rm-owner-grid b {
        color: #0f172a;
        display: block;
        font-size: 1.05rem;
    }
    .rm-owner-grid span {
        color: #64748b;
        display: block;
        font-size: 0.68rem;
        font-weight: 700;
        text-transform: uppercase;
    }
    .rm-empty {
        background: #f8fafc;
        border: 1px solid #dbe3ef;
        border-radius: 10px;
        color: #64748b;
        margin: 12px 0 20px;
        padding: 16px;
    }
    @media (max-width: 1000px) {
        [data-testid="stMain"] [role="radiogroup"][aria-label="Inventory workflow"] {
            grid-template-columns: repeat(3, minmax(0, 1fr));
        }
        .agent-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .supplier-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .rm-owner-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 720px) {
        .agent-status-grid { grid-template-columns: 1fr; }
        .supplier-grid { grid-template-columns: 1fr; }
        .rm-owner-cards { grid-template-columns: 1fr; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


with st.sidebar:
    st.markdown(
        '<div class="sidebar-brand">'
        '<div class="sidebar-brand-mark">IM</div>'
        '<div>'
        '<div class="sidebar-brand-name">InventoryOS</div>'
        '<div class="sidebar-brand-subtitle">Material intelligence</div>'
        '</div>'
        '</div>'
        '<div class="sidebar-section-label">OPERATIONS</div>',
        unsafe_allow_html=True,
    )
    sidebar_labels = {
        "Inventory Management Agent": "▦  Inventory Command",
        "Inwarding Parts": "↓  Inwarding Control",
        "Outwarding Parts": "↑  Outwarding Control",
        "Documentation": "◫  Documentation",
        "Setup": "⚙  Setup",
    }
    page = st.radio(
        "Navigation",
        list(sidebar_labels),
        format_func=lambda value: sidebar_labels[value],
        label_visibility="collapsed",
        key="app_navigation",
    )
    st.markdown(
        '<div class="sidebar-section-label sidebar-lower-label">WORKSPACE</div>'
        '<div class="sidebar-context-card">'
        '<span class="sidebar-context-dot"></span>'
        '<div>'
        '<b>HS01 · Stores</b>'
        '<small>Saved-data workspace</small>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )


if page == "Inventory Management Agent":
    st.markdown(
        '<div class="app-topbar">'
        '<div>'
        '<div class="app-breadcrumb">OPERATIONS · INVENTORY</div>'
        '<div class="app-topbar-title">Inventory Command Centre</div>'
        '<div class="app-topbar-subtitle">'
        'Stock, production and supplier decisions'
        '</div>'
        '</div>'
        '<div class="app-topbar-user">'
        '<div>'
        '<b>HS01 Control</b>'
        f'<span>{datetime.now():%d %b %Y · %H:%M}</span>'
        '</div>'
        '<div class="app-user-avatar">SCM</div>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )
else:
    st.title(
        APP_TITLE,
        help=(
            "A single workspace for part requirements, stock health, material "
            "movement, discrepancy control, and supplier follow-up."
        ),
    )


if page == "Inventory Management Agent":
    credentials = load_google_credentials()
    command_inventory, _, command_diagnostics = (
        load_inventory_workspace_snapshot()
    )
    plan_dates = pd.to_datetime(
        command_inventory.get("Plan Date", pd.Series(dtype=str)),
        errors="coerce",
    ).dropna()
    selected_plan_date = (
        plan_dates.max().strftime("%d %b %Y")
        if not plan_dates.empty
        else "Unavailable"
    )
    required_cache_paths = [
        source["cache"] for source in SOURCE_SHEETS.values()
    ] + [
        INWARDING_SNAPSHOT_PATH,
        BUYER_MAPPING_CACHE_PATH,
    ]
    existing_cache_paths = [
        path for path in required_cache_paths if path.exists()
    ]
    missing_cache_count = len(required_cache_paths) - len(
        existing_cache_paths
    )
    latest_saved = (
        datetime.fromtimestamp(
            max(path.stat().st_mtime for path in existing_cache_paths)
        )
        if existing_cache_paths
        else None
    )
    oldest_saved = (
        datetime.fromtimestamp(
            min(path.stat().st_mtime for path in existing_cache_paths)
        )
        if existing_cache_paths
        else None
    )
    freshness_hours = (
        max((datetime.now() - oldest_saved).total_seconds() / 3600, 0)
        if oldest_saved is not None
        else None
    )
    stock_gaps = (
        int(command_inventory["Stock Data Status"].ne("Available").sum())
        if not command_inventory.empty
        and "Stock Data Status" in command_inventory
        else 0
    )
    overall_health = (
        "Ready"
        if not command_diagnostics.get("error")
        and missing_cache_count == 0
        and stock_gaps == 0
        else "Attention"
    )
    with st.container(border=True):
        st.subheader(
            "Control cycle",
            help=(
                "The production date and saved-source state used by every stock, "
                "requirement and agent calculation on this page."
            ),
        )
        command_bar = st.columns([1, 1, 1, 1.15, 1.15])
        with command_bar[0]:
            st.metric(
                "Production date",
                selected_plan_date,
                help="Latest eligible positive production-plan date in the saved source.",
            )
        with command_bar[1]:
            st.metric(
                "Data freshness",
                (
                    f"{freshness_hours:.1f} h"
                    if freshness_hours is not None
                    else "Unavailable"
                ),
                help="Age of the oldest required saved source.",
            )
        with command_bar[2]:
            st.metric(
                "Data health",
                overall_health,
                help=(
                    f"{missing_cache_count} source(s) missing and "
                    f"{stock_gaps} stock-data gap(s)."
                ),
            )
        with command_bar[3]:
            st.metric(
                "Last successful save",
                (
                    latest_saved.strftime("%d %b · %H:%M")
                    if latest_saved is not None
                    else "Unavailable"
                ),
                help="Most recent timestamp among the saved source snapshots.",
            )
        with command_bar[4]:
            master_refresh_clicked = st.button(
                "Refresh all sources",
                type="primary",
                disabled=credentials is None,
                help=(
                    "Refresh production, BOM, SCM stock, outwarding, inwarding, "
                    "buyer mapping, and agent checks."
                ),
                width="stretch",
            )
            st.caption("Previous copies remain if a source fails.")
            render_auto_refresh_control(credentials)
    auto_refresh_result = st.session_state.pop(
        "inventory_auto_refresh_result",
        None,
    )
    if auto_refresh_result:
        completed_count = len(auto_refresh_result.get("completed", []))
        failed_count = len(auto_refresh_result.get("failed", []))
        if failed_count:
            st.toast(
                f"15-minute refresh saved {completed_count} source group(s); "
                f"{failed_count} kept their previous copy.",
                icon="⚠️",
            )
        else:
            st.toast(
                f"15-minute refresh completed at "
                f"{auto_refresh_result.get('finished_at', '')}.",
                icon="✅",
            )
    if credentials is None:
        st.caption(
            "Connect Google in Setup to enable refresh. Saved data remains available."
        )
    if master_refresh_clicked:
        with st.spinner("Refreshing all inventory sources and agent checks..."):
            completed, failed = perform_master_refresh(credentials)
        st.session_state["inventory_auto_refresh_last_run"] = datetime.now()
        if completed:
            st.success(
                "Master refresh completed:\n\n"
                + "\n".join(f"- {item}" for item in completed)
            )
        if failed:
            st.warning(
                "Some sources kept their previous saved copy:\n\n"
                + "\n".join(f"- {item}" for item in failed)
            )
    st.markdown(
        '<div class="workflow-caption">'
        '<span>1</span> Overview <i>→</i>'
        '<span>2</span> Live flow <i>→</i>'
        '<span>3</span> Stock health <i>→</i>'
        '<span>4</span> Requirements <i>→</i>'
        '<span>5</span> Actions <i>→</i>'
        '<span>6</span> Audit'
        '</div>',
        unsafe_allow_html=True,
    )
    inventory_workspace = st.radio(
        "Inventory workflow",
        [
            "Overview",
            "Live Flow",
            "Stock Health",
            "Requirements",
            "Action Centre",
            "Audit & Evidence",
        ],
        horizontal=True,
        label_visibility="collapsed",
        key="inventory_management_workflow",
    )
    st.divider()
    if inventory_workspace == "Overview":
        render_inventory_executive_overview()
    elif inventory_workspace == "Live Flow":
        render_inventory_live_flow()
    elif inventory_workspace == "Stock Health":
        render_stock_health_workspace()
    elif inventory_workspace == "Requirements":
        render_requirements_workspace()
    elif inventory_workspace == "Action Centre":
        render_action_centre()
    else:
        render_audit_evidence_workspace()
elif page == "Inwarding Parts":
    render_inwarding()
elif page == "Outwarding Parts":
    render_outwarding()
elif page == "Documentation":
    render_documentation()
else:
    render_setup()
