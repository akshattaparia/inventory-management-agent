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
LIVE_GRN_CSV = DATA_DIR / "live" / "grn_live.csv"
LIVE_GRN_META = LIVE_GRN_CSV.with_suffix(".json")
GRN_SHEET_SNAPSHOT_CSV = DATA_DIR / "live" / "grn_sheet_snapshot.csv"
GRN_SHEET_SNAPSHOT_META = GRN_SHEET_SNAPSHOT_CSV.with_suffix(".json")
LIVE_GOOGLE_SHEET_SNAPSHOT_CSV = DATA_DIR / "live" / "google_sheet_snapshot.csv"
LIVE_GOOGLE_SHEET_SNAPSHOT_META = LIVE_GOOGLE_SHEET_SNAPSHOT_CSV.with_suffix(".json")
SPOC_SUMMARY_SNAPSHOT_CSV = DATA_DIR / "live" / "spoc_summary_snapshot.csv"
SPOC_SUMMARY_SNAPSHOT_META = SPOC_SUMMARY_SNAPSHOT_CSV.with_suffix(".json")
GRN_EXPORT_SCRIPT = APP_DIR / "scripts" / "scheduled_grn_export.py"
GOOGLE_SERVICE_ACCOUNT_JSON_PATH = APP_DIR / ".streamlit" / "google_service_account.json"
GOOGLE_OAUTH_CONFIG_PATH = APP_DIR / ".streamlit" / "google_oauth.json"
DEFAULT_GOOGLE_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1V3ic-5Dfcz0PoX-0Z0gXdIrFIIOB_lSh-gM20RzLUKs/edit?gid=2111379627#gid=2111379627"
)
DEFAULT_GRN_SHEET_URL = DEFAULT_GOOGLE_SHEET_URL
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
GOOGLE_OAUTH_SCOPES = [GOOGLE_SHEETS_READONLY_SCOPE]
GOOGLE_TOKEN_PATH = APP_DIR / ".streamlit" / "google_oauth_token.json"
GOOGLE_STATE_PATH = APP_DIR / ".streamlit" / "google_oauth_state.txt"
PRODUCTION_SHEET_ID = "1KLvkeqE71PwJN6keLuIqQYLywfFvvQa7sCq9bo-Ii6I"
BOM_SHEET_ID = "1dXeJ6dkDoxgyLlkapGFyws75i3ck2-TYeemvq-dKZ9Y"
SCM_REV_SHEET_ID = "147vIBFZxf6aQddMG-cpQmuFtcM-6nH0pjn0HDHMyLhE"
SERVICING_SHEET_ID = "1K3reYmx6EvqjcYDwFzW--1QaY9odcKCN6H9b_FXr-aY"
SERVICING_DEFAULT_GID = 1098040909
SERVICING_LOOKBACK_DAYS = 21
SR_POSTING_SHEET_ID = "1PuvZ_ghsl6KSlZVCFdLVQkjmi3ApnjUboZSnEQIQSqM"
SR_POSTING_GID = 2027262587


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
SERVICING_SOURCE_SHEET_URL = sheet_url(SERVICING_SHEET_ID, SERVICING_DEFAULT_GID)
SERVICING_SNAPSHOT_PATH = DATA_DIR / "servicing_daily_usage.csv"
SERVICING_SNAPSHOT_META_PATH = DATA_DIR / "servicing_daily_usage.json"
SR_POSTING_SOURCE_SHEET_URL = sheet_url(SR_POSTING_SHEET_ID, SR_POSTING_GID)
SR_POSTING_SNAPSHOT_PATH = DATA_DIR / "sr_311_posting_movements.csv"
SR_POSTING_SNAPSHOT_META_PATH = DATA_DIR / "sr_311_posting_movements.json"
COMPUTED_USAGE_CACHE_PATH = DATA_DIR / "computed_part_usage.csv"
OUTWARDING_BASELINE_PATH = DATA_DIR / "outwarding_plan_baseline.csv"
OUTWARDING_ALERT_LOG_PATH = DATA_DIR / "outwarding_alert_log.csv"
OUTWARDING_OWNER_DEFAULT = "Akshat Taparia, Abhiraj Koslia"
AGENT_TABLE_LIMIT = 250
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
RM_MOVEMENT_PLAN_PATH = DATA_DIR / "rm_movement_plan.csv"
PVIN_INPUTS_PATH = DATA_DIR / "pvin_variant_inputs.csv"
INVENTORY_CONTROL_CASES_PATH = DATA_DIR / "inventory_control_cases.csv"
INVENTORY_CORRECTIONS_PATH = DATA_DIR / "inventory_correction_requests.csv"
PVIN_INPUT_COLUMNS = [
    "Plan Date",
    "Variant",
    "Generated P-VIN",
    "Produced P-VIN",
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
RM_MOVEMENT_COLUMNS = [
    "Plan Date",
    "Buyer",
    "Supplier",
    "Part No.",
    "Part Name",
    "System Stock",
    "Store Stock",
    "In Transit Qty",
    "Stock Difference Transit Qty",
    "VIN Gap Transit Qty",
    "Transit Source",
    "In Transit Override",
    "GA Line Need",
    "SA Line Need",
    "Shop Need",
    "GA Priority",
    "SA Priority",
    "Shop Priority",
    "Remarks",
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
                "Gate Entry No.",
                "Invoice Number",
                "Invoice Qty",
                "Discrepancy",
                "Storage Location",
                "Plant",
                "Source Row",
            ]
        )

    result = pd.DataFrame(index=df.index)
    result["Buyer"] = column_or_blank(df, ["buyer", "buyer_name"])
    result["Supplier"] = column_or_blank(df, ["supplier", "supplier_name", "suplier_name", "vendor", "vendor_name"])
    result["Part No."] = column_or_blank(df, ["part_no", "part_number", "matnr", "material", "material_code"])
    result["Part Name"] = column_or_blank(df, ["part_name", "part_description", "material_description", "maktx"])
    result["Rcvd Qty"] = column_or_blank(
        df,
        ["receipt_qty", "received_qty", "quantity_received", "rcvd_qty", "menge", "actual_quantity_received"],
    )
    result["Arrival Time"] = format_grn_times(column_or_blank(df, ["arrival_time", "in_time", "sap_entry_time", "cputm"]))
    result["Arrival Date"] = format_grn_dates(column_or_blank(df, ["arrival_date", "grn_date", "date", "gate_entry_date", "sap_entry_date", "budat", "posting_date"]))
    result["PO Number"] = column_or_blank(df, ["po_no", "po_number", "ebeln"])
    result["Gate Entry No."] = column_or_blank(df, ["gate_entry_no", "gate_no", "entry_no"])
    result["Invoice Number"] = column_or_blank(df, ["invoice_number", "invoice_no"])
    result["Invoice Qty"] = column_or_blank(df, ["invoice_qty", "invoice_quantity"])
    result["Discrepancy"] = column_or_blank(df, ["discrepancy", "qty_discrepancy"])
    result["Storage Location"] = column_or_blank(df, ["storage_location", "lgort"])
    result["Plant"] = column_or_blank(df, ["plant", "werks"])
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


def data_file_health_row(label: str, path: Path, note: str = "") -> dict[str, object]:
    if not path.exists():
        return {
            "Input source": label,
            "Status": "Missing",
            "Rows": "",
            "Columns": "",
            "Last refreshed": "no copy yet",
            "Feeds": note,
        }

    row_count: object = ""
    column_count: object = ""
    try:
        with path.open("rb") as handle:
            row_count = max(sum(1 for _ in handle) - 1, 0)
    except OSError:
        row_count = ""

    try:
        column_count = len(pd.read_csv(path, dtype=str, nrows=0).columns)
    except Exception:
        column_count = ""

    modified_at = datetime.fromtimestamp(path.stat().st_mtime)
    return {
        "Input source": label,
        "Status": "Ready",
        "Rows": row_count,
        "Columns": column_count,
        "Last refreshed": f"{modified_at:%d %b %I:%M %p} ({snapshot_age_label(path)})",
        "Feeds": note,
    }


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


def value_to_right_of_label(raw: pd.DataFrame, label: str) -> str:
    wanted = normalize_column_name(label)
    for row in range(raw.shape[0]):
        for col in range(raw.shape[1]):
            if normalize_column_name(raw.iat[row, col]) != wanted:
                continue
            for next_col in range(col + 1, min(col + 5, raw.shape[1])):
                value = clean_text(raw.iat[row, next_col])
                if value:
                    return value
    return ""


def find_spoc_onsite_header_row(raw: pd.DataFrame) -> int | None:
    for row_index in range(min(len(raw), 80)):
        headers = {normalize_column_name(value) for value in raw.iloc[row_index].tolist() if clean_text(value)}
        if "part_no" in headers and "opening_stock" in headers:
            return row_index
    return None


def parse_spoc_onsite_stock_raw(raw: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Part No.",
        "Part Name",
        "Stock Qty",
        "Stock Basis",
        "Stock Date",
        "Supplier",
        "Buyer",
        "MRP / Requirement",
        "Closing Stock",
    ]
    if raw.empty:
        return pd.DataFrame(columns=columns)

    header_row = find_spoc_onsite_header_row(raw)
    if header_row is None:
        return pd.DataFrame(columns=columns)

    headers = [clean_text(value) for value in raw.iloc[header_row].tolist()]
    date_col = sheet_col(headers, "date")
    part_col = sheet_col(headers, "part_no", "part_number", "component")
    part_name_col = sheet_col(headers, "part_description", "description", "part_name", "object_description")
    opening_col = sheet_col_contains(headers, "opening", "stock")
    requirement_col = sheet_col(headers, "mrp_requirement", "mrp requirement", "requirement")
    closing_col = sheet_col_contains(headers, "closing", "stock")

    supplier = normalize_supplier_name(value_to_right_of_label(raw, "Supplier Name :"))
    buyer = normalize_buyer_name(
        value_to_right_of_label(raw, "SCM SPOC :")
        or value_to_right_of_label(raw, "On Site SPOC :")
    )

    current_date = pd.NaT
    records: list[dict[str, object]] = []
    for row_index in range(header_row + 1, len(raw)):
        parsed_date = parse_report_date(raw_cell(raw, row_index, date_col))
        if pd.notna(parsed_date):
            current_date = parsed_date

        part_no = stock_part_key(raw_cell(raw, row_index, part_col))
        if not part_no or part_no in {"#N/A", "N/A", "NA", "NONE", "-"}:
            continue

        opening_raw = raw_cell(raw, row_index, opening_col)
        closing_raw = raw_cell(raw, row_index, closing_col)
        requirement_raw = raw_cell(raw, row_index, requirement_col)
        opening_stock = pd.to_numeric(opening_raw, errors="coerce")
        closing_stock = pd.to_numeric(closing_raw, errors="coerce")
        requirement = pd.to_numeric(requirement_raw, errors="coerce")
        has_opening_stock = pd.notna(opening_stock)
        has_closing_stock = pd.notna(closing_stock)
        has_requirement = pd.notna(requirement)
        if not (has_opening_stock or has_closing_stock or has_requirement):
            continue

        stock_qty = float(opening_stock) if has_opening_stock else 0.0
        part_name = clean_text(raw_cell(raw, row_index, part_name_col)).upper()
        stock_date = current_date.strftime("%Y-%m-%d") if pd.notna(current_date) else ""
        records.append(
            {
                "Part No.": part_no,
                "Part Name": part_name,
                "Stock Qty": stock_qty,
                "Stock Basis": f"SPOC opening stock {stock_date}".strip(),
                "Stock Date": stock_date,
                "Supplier": supplier,
                "Buyer": buyer,
                "MRP / Requirement": 0.0 if pd.isna(requirement) else float(requirement),
                "Closing Stock": 0.0 if pd.isna(closing_stock) else float(closing_stock),
            }
        )

    if not records:
        return pd.DataFrame(columns=columns)

    stock = pd.DataFrame(records, columns=columns)
    stock["_date"] = pd.to_datetime(stock["Stock Date"], errors="coerce")
    stock["_row"] = range(len(stock))
    stock = (
        stock.sort_values(["Part No.", "_date", "_row"])
        .drop_duplicates("Part No.", keep="last")
        .drop(columns=["_date", "_row"])
        .reset_index(drop=True)
    )
    return stock[columns]


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
    config: dict[str, object] | None = None
    try:
        if "google_oauth" in st.secrets:
            config = dict(st.secrets["google_oauth"])
    except Exception:
        config = None

    if config is None and GOOGLE_OAUTH_CONFIG_PATH.exists():
        try:
            config = json.loads(GOOGLE_OAUTH_CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            config = None

    if not config:
        return None

    client_id = clean_text(config.get("client_id", ""))
    client_secret = clean_text(config.get("client_secret", ""))
    redirect_uri = clean_text(config.get("redirect_uri", ""))
    if (
        not client_id
        or not client_secret
        or not redirect_uri
        or client_id.startswith("YOUR_")
        or client_secret.startswith("YOUR_")
    ):
        return None

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


def save_google_oauth_settings(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> tuple[bool, str]:
    client_id = clean_text(client_id)
    client_secret = clean_text(client_secret)
    redirect_uri = clean_text(redirect_uri)
    if not client_id or not client_secret or not redirect_uri:
        return False, "Client ID, client secret, and redirect URI are required."
    if not redirect_uri.startswith(("http://", "https://")):
        return False, "Redirect URI must start with http:// or https://."

    save_private_text(
        GOOGLE_OAUTH_CONFIG_PATH,
        json.dumps(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            },
            indent=2,
        ),
    )
    GOOGLE_TOKEN_PATH.unlink(missing_ok=True)
    GOOGLE_STATE_PATH.unlink(missing_ok=True)
    return True, "Google OAuth settings saved."


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
        scopes=GOOGLE_OAUTH_SCOPES,
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
            scopes=GOOGLE_OAUTH_SCOPES,
        )
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(GoogleAuthRequest())
            save_google_credentials(credentials)
        return credentials if credentials.valid else None
    except Exception:
        return None


def clear_google_oauth() -> None:
    GOOGLE_TOKEN_PATH.unlink(missing_ok=True)
    GOOGLE_STATE_PATH.unlink(missing_ok=True)
    for key in ("google_oauth_connected_notice",):
        st.session_state.pop(key, None)


def google_oauth_connected() -> bool:
    return load_google_credentials() is not None


def google_sheet_read_method_label() -> str:
    if google_oauth_connected():
        return "Google OAuth"
    if google_sheets_credentials_configured():
        return "Google service account"
    return "CSV export link"


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


def production_bucket(value: object) -> str:
    text = str(value).upper().replace(" ", "")
    if "P-VIN" in text or "PVIN" in text:
        return "P-VIN"
    if "VNA" in text:
        return "VNA"
    if "FREE" in text:
        return "Free VIN"
    return "Other"


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
    return pd.DataFrame(records, columns=columns)


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
    unmatched_columns = ["Usage Date", "Model", "Color", "Produced Qty", "Production Source"]
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
    date_columns: list[tuple[list[tuple[int, str]], pd.Timestamp]] = []
    for index, value in enumerate(date_header):
        if not re.fullmatch(r"\d{1,2}-[A-Za-z]{3}", value.strip()):
            continue
        usage_date = parse_sheet_date(value)
        if pd.notna(usage_date) and index + 7 < len(date_header):
            date_columns.append(
                (
                    [
                        (index + 1, "P-VIN actuals"),
                        (index + 3, "VNA actuals"),
                        (index + 5, "Free VIN actuals"),
                    ],
                    usage_date.normalize(),
                )
            )

    production_rows: list[dict[str, object]] = []
    unmatched_rows: list[dict[str, object]] = []
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
        for actual_columns, usage_date in date_columns:
            for column, source_label in actual_columns:
                if column >= len(row):
                    continue
                quantity = pd.to_numeric(
                    str(row[column]).replace(",", ""),
                    errors="coerce",
                )
                if pd.isna(quantity) or float(quantity) <= 0:
                    continue
                values = {
                    "Usage Date": usage_date,
                    "Model": current_model,
                    "Color": color,
                    "Produced Qty": float(quantity),
                    "Production Source": source_label,
                }
                if fg:
                    production_rows.append(
                        {
                            "Usage Date": usage_date,
                            "FG": fg,
                            "Produced Qty": float(quantity),
                            "Production Source": source_label,
                        }
                    )
                else:
                    unmatched_rows.append(values)

    production = pd.DataFrame(production_rows, columns=columns)
    if not production.empty:
        production = (
            production.groupby(["Usage Date", "FG", "Production Source"], as_index=False)[
                "Produced Qty"
            ]
            .sum()
        )
    return production, pd.DataFrame(unmatched_rows, columns=unmatched_columns)


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
        production.groupby(["Usage Date", "FG", "Production Source"], as_index=False)[
            "Produced Qty"
        ]
        .sum()
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
        "P-VIN Produced Qty",
        "VNA Produced Qty",
        "Free VIN Produced Qty",
        "Part No.",
        "Part Name",
        "Material Type",
        "Supplier",
        "P-VIN Production Used Qty",
        "VNA Production Used Qty",
        "Free VIN Production Used Qty",
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
    detail["Production Bucket"] = detail["Production Source"].map(production_bucket)
    usage = (
        detail.groupby(["Usage Date", "Component"], as_index=False)[
            "Production Used Qty"
        ]
        .sum()
        .rename(columns={"Component": "Part No."})
    )
    source_usage = (
        detail.pivot_table(
            index=["Usage Date", "Component"],
            columns="Production Bucket",
            values="Production Used Qty",
            aggfunc="sum",
            fill_value=0,
        )
        .rename(
            columns={
                "P-VIN": "P-VIN Production Used Qty",
                "VNA": "VNA Production Used Qty",
                "Free VIN": "Free VIN Production Used Qty",
            }
        )
        .reset_index()
        .rename(columns={"Component": "Part No."})
    )
    for column in [
        "P-VIN Production Used Qty",
        "VNA Production Used Qty",
        "Free VIN Production Used Qty",
    ]:
        if column not in source_usage.columns:
            source_usage[column] = 0.0
    usage = usage.merge(
        source_usage[
            [
                "Usage Date",
                "Part No.",
                "P-VIN Production Used Qty",
                "VNA Production Used Qty",
                "Free VIN Production Used Qty",
            ]
        ],
        on=["Usage Date", "Part No."],
        how="left",
    )
    daily_totals = (
        production.groupby("Usage Date", as_index=False)["Produced Qty"]
        .sum()
        .rename(columns={"Produced Qty": "Daily Total Production"})
    )
    usage = usage.merge(daily_totals, on="Usage Date", how="left")
    production_with_bucket = production.copy()
    production_with_bucket["Production Bucket"] = production_with_bucket[
        "Production Source"
    ].map(production_bucket)
    source_daily_totals = (
        production_with_bucket.pivot_table(
            index="Usage Date",
            columns="Production Bucket",
            values="Produced Qty",
            aggfunc="sum",
            fill_value=0,
        )
        .rename(
            columns={
                "P-VIN": "P-VIN Produced Qty",
                "VNA": "VNA Produced Qty",
                "Free VIN": "Free VIN Produced Qty",
            }
        )
        .reset_index()
    )
    for column in ["P-VIN Produced Qty", "VNA Produced Qty", "Free VIN Produced Qty"]:
        if column not in source_daily_totals.columns:
            source_daily_totals[column] = 0.0
    usage = usage.merge(
        source_daily_totals[
            ["Usage Date", "P-VIN Produced Qty", "VNA Produced Qty", "Free VIN Produced Qty"]
        ],
        on="Usage Date",
        how="left",
    )

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


def normalize_servicing_outwarding(servicing_input: pd.DataFrame) -> pd.DataFrame:
    manual_columns = [
        "Usage Date",
        "Part No.",
        "Manual Part Name",
        "Manual Supplier",
        "Servicing Required Qty",
        "Servicing Used Qty",
        "Servicing Demand Qty",
        "Servicing GRN Pending Qty",
        "Servicing Allocation Qty",
        "Servicing Source",
        "Servicing Model",
        "Servicing SPOC",
        "Reference No.",
        "Remarks",
    ]
    if servicing_input.empty:
        return pd.DataFrame(columns=manual_columns)

    manual = servicing_input.copy()
    manual["Usage Date"] = pd.to_datetime(
        column_or_blank(manual, ["Usage Date", "Date"]),
        errors="coerce",
        format="mixed",
    ).dt.normalize()
    manual["Part No."] = column_or_blank(
        manual,
        ["Part No.", "Part No", "Part Number", "Material", "Material Code"],
    ).apply(stock_part_key)
    manual["Manual Part Name"] = column_or_blank(
        manual,
        ["Part Name", "Description", "Material Description"],
    )
    manual["Manual Supplier"] = column_or_blank(manual, ["Supplier", "Supplier Name"])
    manual["Servicing Required Qty"] = numeric(
        column_or_blank(
            manual,
            ["Servicing Required Qty", "Required Qty", "CPD PNA - July", "CPD PNA"],
        )
    )
    manual["Servicing Used Qty"] = numeric(
        column_or_blank(manual, ["Servicing Used Qty", "Used Qty", "Total"])
    )
    demand_source = column_or_blank(
        manual,
        ["Servicing Demand Qty", "Servicing Balance Qty", "Balance"],
    )
    demand_qty = numeric(demand_source)
    if demand_source.astype(str).str.strip().eq("").all():
        demand_qty = numeric(column_or_blank(manual, ["Used Qty", "Servicing Used Qty"]))
    manual["Servicing Demand Qty"] = demand_qty.clip(lower=0)
    manual["Servicing GRN Pending Qty"] = numeric(
        column_or_blank(manual, ["Servicing GRN Pending Qty", "GRN Pending"])
    )
    manual["Servicing Allocation Qty"] = numeric(
        column_or_blank(manual, ["Servicing Allocation Qty", "Allocation qty", "Allocation Qty"])
    )
    manual["Servicing Source"] = column_or_blank(manual, ["Servicing Source", "Usage Source"])
    manual["Servicing Source"] = manual["Servicing Source"].replace("", "Manual servicing input")
    manual["Servicing Model"] = column_or_blank(manual, ["Servicing Model", "Model"])
    manual["Servicing SPOC"] = column_or_blank(manual, ["Servicing SPOC", "SPOC"])
    manual["Reference No."] = column_or_blank(manual, ["Reference No.", "Reference No", "Source Tab"])
    manual["Remarks"] = column_or_blank(manual, ["Remarks", "PPC & Store Comments", "CPD Comments"])
    manual = manual[manual["Usage Date"].notna() & manual["Part No."].ne("")].copy()
    if manual.empty:
        return pd.DataFrame(columns=manual_columns)
    return (
        manual.groupby(["Usage Date", "Part No."], as_index=False)
        .agg(
            {
                "Manual Part Name": joined_text,
                "Manual Supplier": joined_text,
                "Servicing Required Qty": "sum",
                "Servicing Used Qty": "sum",
                "Servicing Demand Qty": "sum",
                "Servicing GRN Pending Qty": "sum",
                "Servicing Allocation Qty": "sum",
                "Servicing Source": joined_text,
                "Servicing Model": joined_text,
                "Servicing SPOC": joined_text,
                "Reference No.": joined_text,
                "Remarks": joined_text,
            }
        )
    )


def combine_manual_outwarding(
    production_usage: pd.DataFrame,
    manual_outwarding: pd.DataFrame,
) -> pd.DataFrame:
    manual = normalize_servicing_outwarding(manual_outwarding)

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
        "P-VIN Produced Qty",
        "VNA Produced Qty",
        "Free VIN Produced Qty",
        "P-VIN Production Used Qty",
        "VNA Production Used Qty",
        "Free VIN Production Used Qty",
        "Production Used Qty",
        "Servicing Required Qty",
        "Servicing Used Qty",
        "Servicing Demand Qty",
        "Servicing GRN Pending Qty",
        "Servicing Allocation Qty",
    ]:
        if column not in combined.columns:
            combined[column] = 0.0
        combined[column] = numeric(combined[column])
    combined["Total Outwarding Qty"] = (
        combined["Production Used Qty"] + combined["Servicing Used Qty"]
    )
    combined["Total Demand Qty"] = (
        combined["Production Used Qty"] + combined["Servicing Demand Qty"]
    )
    ordered = [
        "Usage Date",
        "Daily Total Production",
        "P-VIN Produced Qty",
        "VNA Produced Qty",
        "Free VIN Produced Qty",
        "Part No.",
        "Part Name",
        "Material Type",
        "Supplier",
        "P-VIN Production Used Qty",
        "VNA Production Used Qty",
        "Free VIN Production Used Qty",
        "Production Used Qty",
        "Servicing Required Qty",
        "Servicing Used Qty",
        "Servicing Demand Qty",
        "Servicing GRN Pending Qty",
        "Servicing Allocation Qty",
        "Servicing Source",
        "Servicing Model",
        "Servicing SPOC",
        "Reference No.",
        "Remarks",
        "Total Outwarding Qty",
        "Total Demand Qty",
    ]
    for column in ordered:
        if column not in combined.columns:
            combined[column] = ""
    return combined[ordered].sort_values(
        ["Usage Date", "Part No."],
        ascending=[False, True],
    )


def enrich_outwarding_buyer_supplier(outwarding: pd.DataFrame) -> pd.DataFrame:
    if outwarding.empty:
        result = outwarding.copy()
        if "Buyer" not in result.columns:
            result["Buyer"] = ""
        return result

    mapping = load_current_buyer_mapping()
    result = outwarding.copy()
    if "Buyer" not in result.columns:
        result["Buyer"] = ""
    if mapping.empty:
        result["Buyer"] = result["Buyer"].replace("", "Not mapped")
        return result

    mapping = mapping.copy()
    mapping["Part Key"] = mapping["Part Number"].map(stock_part_key)
    mapping["Supplier Key"] = mapping["Mapped Supplier"].map(supplier_match_key)
    mapping["Supplier Prefix"] = mapping["Supplier Key"].str[:20]
    mapping["Canonical Supplier Key"] = mapping["Mapped Supplier"].map(
        canonical_supplier_key
    )

    part_supplier_map = (
        mapping[mapping["Part Key"].ne("")]
        .groupby("Part Key")["Mapped Supplier"]
        .agg(joined_text)
    )
    part_buyer_map = (
        mapping[mapping["Part Key"].ne("")]
        .groupby("Part Key")["Buyer Name"]
        .agg(joined_text)
    )
    supplier_buyer_map = (
        mapping[mapping["Supplier Key"].ne("")]
        .groupby("Supplier Key")["Buyer Name"]
        .agg(joined_text)
    )
    supplier_prefix_buyer_map = (
        mapping[mapping["Supplier Prefix"].ne("")]
        .groupby("Supplier Prefix")["Buyer Name"]
        .agg(joined_text)
    )
    canonical_supplier_buyer_map = (
        mapping[mapping["Canonical Supplier Key"].ne("")]
        .groupby("Canonical Supplier Key")["Buyer Name"]
        .agg(joined_text)
    )

    part_keys = result["Part No."].map(stock_part_key)
    mapped_suppliers = part_keys.map(part_supplier_map).fillna("")
    result["Supplier"] = result["Supplier"].where(
        mapped_suppliers.eq(""),
        mapped_suppliers,
    )

    supplier_keys = result["Supplier"].map(supplier_match_key)
    buyers = part_keys.map(part_buyer_map).fillna("")
    buyers = buyers.where(
        buyers.ne(""),
        supplier_keys.map(supplier_buyer_map).fillna(""),
    )
    buyers = buyers.where(
        buyers.ne(""),
        supplier_keys.str[:20].map(supplier_prefix_buyer_map).fillna(""),
    )
    canonical_supplier_keys = result["Supplier"].map(canonical_supplier_key)
    buyers = buyers.where(
        buyers.ne(""),
        canonical_supplier_keys.map(canonical_supplier_buyer_map).fillna(""),
    )
    result["Buyer"] = buyers.replace("", "Not mapped")

    ordered = [
        "Usage Date",
        "Daily Total Production",
        "P-VIN Produced Qty",
        "VNA Produced Qty",
        "Free VIN Produced Qty",
        "Buyer",
        "Part No.",
        "Part Name",
        "Material Type",
        "Supplier",
        "P-VIN Production Used Qty",
        "VNA Production Used Qty",
        "Free VIN Production Used Qty",
        "Production Used Qty",
        "Servicing Required Qty",
        "Servicing Used Qty",
        "Servicing Demand Qty",
        "Servicing GRN Pending Qty",
        "Servicing Allocation Qty",
        "Servicing Source",
        "Servicing Model",
        "Servicing SPOC",
        "Reference No.",
        "Remarks",
        "Total Outwarding Qty",
        "Total Demand Qty",
    ]
    for column in ordered:
        if column not in result.columns:
            result[column] = ""
    return result[ordered]


def grn_reference(row: pd.Series) -> str:
    parts = []
    for label in ["Gate Entry No.", "Invoice Number", "PO Number", "Source Row"]:
        value = clean_text(row.get(label, ""))
        if value:
            parts.append(f"{label}: {value}")
    return " | ".join(parts)


def build_grn_quality_alerts(grn_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Agent",
        "Severity",
        "Issue",
        "Part No.",
        "Supplier",
        "Reference",
        "Rcvd Qty",
        "Arrival Date",
        "Recommended Action",
    ]
    if grn_df.empty:
        return pd.DataFrame(columns=columns)

    df = grn_df.copy().fillna("")
    df["Part No."] = df["Part No."].apply(stock_part_key)
    df["Supplier"] = df["Supplier"].apply(normalize_supplier_name)
    rcvd_qty = numeric(df["Rcvd Qty"])
    invoice_qty = numeric(df["Invoice Qty"]) if "Invoice Qty" in df.columns else pd.Series(0, index=df.index)
    discrepancy = numeric(df["Discrepancy"]) if "Discrepancy" in df.columns else invoice_qty - rcvd_qty
    arrival_dates = parse_grn_dates(df["Arrival Date"])

    records: list[dict[str, object]] = []

    def add_issue(mask: pd.Series, severity: str, issue: str, action: str) -> None:
        for _, row in df.loc[mask].iterrows():
            records.append(
                {
                    "Agent": "GRN Data Quality Agent",
                    "Severity": severity,
                    "Issue": issue,
                    "Part No.": row.get("Part No.", ""),
                    "Supplier": row.get("Supplier", ""),
                    "Reference": grn_reference(row),
                    "Rcvd Qty": row.get("Rcvd Qty", ""),
                    "Arrival Date": row.get("Arrival Date", ""),
                    "Recommended Action": action,
                }
            )

    add_issue(
        df["Part No."].eq(""),
        "Critical",
        "Missing part number",
        "Fix the part number in the GRN sheet before this receipt is used in part-level stock.",
    )
    add_issue(
        df["Supplier"].eq(""),
        "Watch",
        "Missing supplier",
        "Add supplier in the source sheet or map the part to a supplier from the SPOC/BOM master.",
    )
    add_issue(
        rcvd_qty <= 0,
        "Critical",
        "Received quantity is blank, zero, or negative",
        "Correct Receipt Qty. Stock cannot increase from a non-positive GRN receipt.",
    )
    add_issue(
        arrival_dates.isna(),
        "Watch",
        "Missing arrival date",
        "Add the arrival/posting date so the receipt can be compared against production consumption by day/week.",
    )

    invoice_mismatch = (invoice_qty > 0) & ((invoice_qty - rcvd_qty).abs() > 0.0001)
    add_issue(
        invoice_mismatch,
        "Watch",
        "Invoice quantity and received quantity differ",
        "Check whether the difference is accepted shortage/excess or a source entry issue.",
    )

    explicit_discrepancy = discrepancy.abs() > 0.0001
    add_issue(
        explicit_discrepancy,
        "Watch",
        "Quantity discrepancy is recorded",
        "Review discrepancy reason and make sure supplier/SCM follow-up is captured.",
    )

    key_columns = ["Gate Entry No.", "Part No.", "Invoice Number"]
    if all(column in df.columns for column in key_columns):
        duplicate_source = df[key_columns].astype(str).apply(lambda col: col.str.strip())
        non_blank_key = duplicate_source.ne("").all(axis=1)
        duplicate_key = duplicate_source.agg("|".join, axis=1)
        duplicate_mask = non_blank_key & duplicate_key.duplicated(keep=False)
        add_issue(
            duplicate_mask,
            "Watch",
            "Possible duplicate GRN line",
            "Check whether this is a real split receipt or the same gate/invoice/part repeated twice.",
        )

    alerts = pd.DataFrame(records, columns=columns)
    if alerts.empty:
        return alerts
    severity_rank = {"Critical": 0, "Watch": 1}
    alerts["_rank"] = alerts["Severity"].map(severity_rank).fillna(9)
    return alerts.sort_values(["_rank", "Issue", "Part No."]).drop(columns="_rank").reset_index(drop=True)


def build_part_owner_lookup(parts: pd.DataFrame) -> pd.DataFrame:
    columns = ["Part No.", "Buyer", "Mapped Supplier"]
    if parts.empty:
        return pd.DataFrame(columns=columns)
    lookup = parts.copy()
    lookup["Part No."] = lookup["Part No."].apply(stock_part_key)
    lookup = lookup[lookup["Part No."].ne("")]
    if lookup.empty:
        return pd.DataFrame(columns=columns)
    grouped = (
        lookup.groupby("Part No.", as_index=False)
        .agg(
            Buyer=("Buyer", joined_text),
            **{"Mapped Supplier": ("Supplier", joined_text)},
        )
    )
    return grouped[columns]


def build_supplier_owner_alerts(parts: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Agent",
        "Severity",
        "Buyer",
        "Supplier",
        "Parts",
        "At Risk Parts",
        "Critical Parts",
        "Issue",
        "Recommended Action",
    ]
    if parts.empty:
        return pd.DataFrame(columns=columns)

    summary = build_supplier_buyer_summary(parts)
    records: list[dict[str, object]] = []
    for _, row in summary.iterrows():
        buyer = clean_text(row.get("Buyer", "")) or "Unmapped buyer"
        supplier = clean_text(row.get("Supplier", "")) or "Unmapped supplier"
        at_risk = int(row.get("Below Required", 0) or 0)
        critical = int(row.get("Critical", 0) or 0)
        parts_count = int(row.get("Parts", 0) or 0)
        if buyer == "Unmapped buyer" or supplier == "Unmapped supplier":
            records.append(
                {
                    "Agent": "Supplier Ownership Agent",
                    "Severity": "Critical" if critical else "Watch",
                    "Buyer": buyer,
                    "Supplier": supplier,
                    "Parts": parts_count,
                    "At Risk Parts": at_risk,
                    "Critical Parts": critical,
                    "Issue": "Buyer/supplier ownership needs cleanup",
                    "Recommended Action": "Fix the SPOC Summary buyer/supplier mapping so follow-up ownership is clear.",
                }
            )
            continue
        if critical:
            records.append(
                {
                    "Agent": "Supplier Ownership Agent",
                    "Severity": "Critical",
                    "Buyer": buyer,
                    "Supplier": supplier,
                    "Parts": parts_count,
                    "At Risk Parts": at_risk,
                    "Critical Parts": critical,
                    "Issue": "Critical parts under this owner",
                    "Recommended Action": "Buyer should follow up with the supplier and SCM owner before production release.",
                }
            )
        elif at_risk:
            records.append(
                {
                    "Agent": "Supplier Ownership Agent",
                    "Severity": "Watch",
                    "Buyer": buyer,
                    "Supplier": supplier,
                    "Parts": parts_count,
                    "At Risk Parts": at_risk,
                    "Critical Parts": critical,
                    "Issue": "Parts below required quantity",
                    "Recommended Action": "Buyer should confirm incoming supply, pull-in options, or stock correction.",
                }
            )

    alerts = pd.DataFrame(records, columns=columns)
    if alerts.empty:
        return alerts
    severity_rank = {"Critical": 0, "Watch": 1}
    alerts["_rank"] = alerts["Severity"].map(severity_rank).fillna(9)
    return (
        alerts.sort_values(["_rank", "Critical Parts", "At Risk Parts", "Supplier"], ascending=[True, False, False, True])
        .drop(columns="_rank")
        .reset_index(drop=True)
    )


def prepare_usage_for_agent(usage: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Usage Date",
        "Daily Total Production",
        "P-VIN Produced Qty",
        "VNA Produced Qty",
        "Free VIN Produced Qty",
        "Buyer",
        "Part No.",
        "Part Name",
        "Supplier",
        "P-VIN Production Used Qty",
        "VNA Production Used Qty",
        "Free VIN Production Used Qty",
        "Production Used Qty",
        "Servicing Required Qty",
        "Servicing Used Qty",
        "Servicing Demand Qty",
        "Servicing GRN Pending Qty",
        "Servicing Allocation Qty",
        "Total Outwarding Qty",
        "Total Demand Qty",
    ]
    if usage.empty:
        return pd.DataFrame(columns=columns + ["Plan Week"])

    result = usage.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = 0 if column.endswith("Qty") or column == "Daily Total Production" else ""
    result["Usage Date"] = pd.to_datetime(result["Usage Date"], errors="coerce").dt.normalize()
    result = result[result["Usage Date"].notna()].copy()
    for column in [
        "Daily Total Production",
        "P-VIN Produced Qty",
        "VNA Produced Qty",
        "Free VIN Produced Qty",
        "P-VIN Production Used Qty",
        "VNA Production Used Qty",
        "Free VIN Production Used Qty",
        "Production Used Qty",
        "Servicing Required Qty",
        "Servicing Used Qty",
        "Servicing Demand Qty",
        "Servicing GRN Pending Qty",
        "Servicing Allocation Qty",
        "Total Outwarding Qty",
        "Total Demand Qty",
    ]:
        result[column] = numeric(result[column])
    if result["Servicing Demand Qty"].sum() <= 0 and result["Servicing Used Qty"].sum() > 0:
        result["Servicing Demand Qty"] = result["Servicing Used Qty"]
    result["Total Outwarding Qty"] = result["Production Used Qty"] + result["Servicing Used Qty"]
    result["Total Demand Qty"] = result["Production Used Qty"] + result["Servicing Demand Qty"]
    result["Part No."] = result["Part No."].astype(str).str.strip()
    result["Buyer"] = result["Buyer"].fillna("").astype(str).str.strip()
    result["Part Name"] = result["Part Name"].fillna("").astype(str).str.strip()
    result["Supplier"] = result["Supplier"].fillna("").astype(str).str.strip()
    iso = result["Usage Date"].dt.isocalendar()
    result["Plan Week"] = (
        iso["year"].astype(str)
        + "-W"
        + iso["week"].astype(str).str.zfill(2)
    )
    return result[columns + ["Plan Week"]]


def save_outwarding_baseline(usage: pd.DataFrame) -> None:
    baseline = prepare_usage_for_agent(usage).copy()
    if not baseline.empty:
        baseline["Usage Date"] = baseline["Usage Date"].dt.strftime("%Y-%m-%d")
    save_source_cache(OUTWARDING_BASELINE_PATH, baseline)


def load_outwarding_baseline() -> pd.DataFrame:
    if not OUTWARDING_BASELINE_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(OUTWARDING_BASELINE_PATH, dtype=str).fillna("")


def load_outwarding_alert_log() -> pd.DataFrame:
    if not OUTWARDING_ALERT_LOG_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(OUTWARDING_ALERT_LOG_PATH, dtype=str).fillna("")


def weekly_production_summary(usage: pd.DataFrame) -> pd.DataFrame:
    prepared = prepare_usage_for_agent(usage)
    if prepared.empty:
        return pd.DataFrame(columns=["Plan Week", "Vehicles"])
    daily = (
        prepared.groupby(["Usage Date", "Plan Week"], as_index=False)["Daily Total Production"]
        .max()
    )
    return (
        daily.groupby("Plan Week", as_index=False)["Daily Total Production"]
        .sum()
        .rename(columns={"Daily Total Production": "Vehicles"})
    )


def load_grn_sheet_display_snapshot() -> pd.DataFrame:
    raw = load_source_cache(INWARDING_SNAPSHOT_PATH)
    if not raw.empty:
        return build_grn_display_frame(raw)
    raw = load_sheet_snapshot(GRN_SHEET_SNAPSHOT_CSV)
    if raw.empty:
        return build_grn_display_frame(pd.DataFrame())
    return build_grn_display_frame(raw_sheet_to_table(raw))


def weekly_part_usage_summary(usage: pd.DataFrame) -> pd.DataFrame:
    prepared = prepare_usage_for_agent(usage)
    columns = [
        "Plan Week",
        "Part No.",
        "Buyer",
        "Part Name",
        "Supplier",
        "P-VIN Production Used Qty",
        "VNA Production Used Qty",
        "Free VIN Production Used Qty",
        "Production Used Qty",
        "Servicing Required Qty",
        "Servicing Used Qty",
        "Servicing Demand Qty",
        "Servicing GRN Pending Qty",
        "Servicing Allocation Qty",
        "Total Outwarding Qty",
        "Total Demand Qty",
    ]
    if prepared.empty:
        return pd.DataFrame(columns=columns)
    return (
        prepared.groupby(["Plan Week", "Part No."], as_index=False)
        .agg(
            **{
                "Buyer": ("Buyer", joined_text),
                "Part Name": ("Part Name", joined_text),
                "Supplier": ("Supplier", joined_text),
                "P-VIN Production Used Qty": ("P-VIN Production Used Qty", "sum"),
                "VNA Production Used Qty": ("VNA Production Used Qty", "sum"),
                "Free VIN Production Used Qty": ("Free VIN Production Used Qty", "sum"),
                "Production Used Qty": ("Production Used Qty", "sum"),
                "Servicing Required Qty": ("Servicing Required Qty", "sum"),
                "Servicing Used Qty": ("Servicing Used Qty", "sum"),
                "Servicing Demand Qty": ("Servicing Demand Qty", "sum"),
                "Servicing GRN Pending Qty": ("Servicing GRN Pending Qty", "sum"),
                "Servicing Allocation Qty": ("Servicing Allocation Qty", "sum"),
                "Total Outwarding Qty": ("Total Outwarding Qty", "sum"),
                "Total Demand Qty": ("Total Demand Qty", "sum"),
            }
        )
        .sort_values(["Plan Week", "Part No."], ascending=[False, True])
    )


def pct_delta(current: float, baseline: float) -> float:
    if baseline == 0:
        return 100.0 if current > 0 else 0.0
    return ((current - baseline) / baseline) * 100


def scalar_float(value: object) -> float:
    return float(pd.to_numeric(pd.Series([value]), errors="coerce").fillna(0).iloc[0])


def alert_severity(delta_pct: float, delta_qty: float, critical_qty: float) -> str:
    if abs(delta_pct) >= 30 or abs(delta_qty) >= critical_qty:
        return "Critical"
    return "Watch"


def build_outwarding_agent_alerts(
    current_usage: pd.DataFrame,
    baseline_usage: pd.DataFrame,
    owners: str,
    reduction_pct_threshold: float,
    vehicle_delta_threshold: float,
    part_delta_threshold: float,
) -> pd.DataFrame:
    alert_columns = [
        "Alert ID",
        "Agent",
        "Severity",
        "Plan Week",
        "Part No.",
        "Part Name",
        "Supplier",
        "Baseline Qty",
        "Current Qty",
        "Delta Qty",
        "Delta %",
        "Owners",
        "Recommended Action",
    ]
    if baseline_usage.empty or current_usage.empty:
        return pd.DataFrame(columns=alert_columns)

    records: list[dict[str, object]] = []
    owner_text = clean_text(owners) or OUTWARDING_OWNER_DEFAULT

    current_weekly = weekly_production_summary(current_usage)
    baseline_weekly = weekly_production_summary(baseline_usage)
    production_compare = current_weekly.merge(
        baseline_weekly,
        on="Plan Week",
        how="outer",
        suffixes=("_current", "_baseline"),
    ).fillna(0)
    for _, row in production_compare.iterrows():
        current_qty = float(row.get("Vehicles_current", 0) or 0)
        baseline_qty = float(row.get("Vehicles_baseline", 0) or 0)
        delta_qty = current_qty - baseline_qty
        delta_percent = pct_delta(current_qty, baseline_qty)
        if baseline_qty <= 0 and current_qty <= 0:
            continue
        if delta_qty <= -vehicle_delta_threshold and abs(delta_percent) >= reduction_pct_threshold:
            severity = alert_severity(delta_percent, delta_qty, vehicle_delta_threshold * 3)
            records.append(
                {
                    "Alert ID": f"production_drop|{row['Plan Week']}|{current_qty:.0f}|{baseline_qty:.0f}",
                    "Agent": "Production fluctuation agent",
                    "Severity": severity,
                    "Plan Week": row["Plan Week"],
                    "Part No.": "",
                    "Part Name": "Weekly vehicle production",
                    "Supplier": "",
                    "Baseline Qty": baseline_qty,
                    "Current Qty": current_qty,
                    "Delta Qty": delta_qty,
                    "Delta %": delta_percent,
                    "Owners": owner_text,
                    "Recommended Action": "Production is down versus baseline. Review supplier call-offs and line-feed quantities before over-issuing material.",
                }
            )
        elif delta_qty >= vehicle_delta_threshold and delta_percent >= reduction_pct_threshold:
            severity = alert_severity(delta_percent, delta_qty, vehicle_delta_threshold * 3)
            records.append(
                {
                    "Alert ID": f"production_increase|{row['Plan Week']}|{current_qty:.0f}|{baseline_qty:.0f}",
                    "Agent": "Production fluctuation agent",
                    "Severity": severity,
                    "Plan Week": row["Plan Week"],
                    "Part No.": "",
                    "Part Name": "Weekly vehicle production",
                    "Supplier": "",
                    "Baseline Qty": baseline_qty,
                    "Current Qty": current_qty,
                    "Delta Qty": delta_qty,
                    "Delta %": delta_percent,
                    "Owners": owner_text,
                    "Recommended Action": "Production is up versus baseline. Check stock cover and inwarding support for extra outwarding demand.",
                }
            )

    current_parts = weekly_part_usage_summary(current_usage)
    baseline_parts = weekly_part_usage_summary(baseline_usage)
    part_compare = current_parts.merge(
        baseline_parts,
        on=["Plan Week", "Part No."],
        how="outer",
        suffixes=("_current", "_baseline"),
    ).fillna("")
    for _, row in part_compare.iterrows():
        current_qty = scalar_float(
            row.get("Total Demand Qty_current", row.get("Total Outwarding Qty_current", 0))
        )
        baseline_qty = scalar_float(
            row.get("Total Demand Qty_baseline", row.get("Total Outwarding Qty_baseline", 0))
        )
        delta_qty = current_qty - baseline_qty
        if abs(delta_qty) < part_delta_threshold:
            continue
        delta_percent = pct_delta(current_qty, baseline_qty)
        part_name = clean_text(row.get("Part Name_current", "")) or clean_text(row.get("Part Name_baseline", ""))
        supplier = clean_text(row.get("Supplier_current", "")) or clean_text(row.get("Supplier_baseline", ""))
        if baseline_qty == 0 and current_qty > 0:
            agent = "New outwarding demand agent"
            action = "New part demand appears in the plan. Confirm stock, supplier coverage, and line-feed readiness."
        elif current_qty == 0 and baseline_qty > 0:
            agent = "Reduced production impact agent"
            action = "Part demand has dropped to zero. Pause or reduce calls for this part and check if inventory will become excess."
        elif delta_qty > 0:
            agent = "Outward stock pressure agent"
            action = "Part usage increased versus baseline. Check available stock and pending inwarding before plan release."
        else:
            agent = "Reduced production impact agent"
            action = "Part usage reduced versus baseline. Check if supplier call-offs or line-feed issues should be adjusted."
        severity = alert_severity(delta_percent, delta_qty, part_delta_threshold * 3)
        records.append(
            {
                "Alert ID": f"{agent}|{row['Plan Week']}|{row['Part No.']}|{current_qty:.0f}|{baseline_qty:.0f}",
                "Agent": agent,
                "Severity": severity,
                "Plan Week": row["Plan Week"],
                "Part No.": row["Part No."],
                "Part Name": part_name,
                "Supplier": supplier,
                "Baseline Qty": baseline_qty,
                "Current Qty": current_qty,
                "Delta Qty": delta_qty,
                "Delta %": delta_percent,
                "Owners": owner_text,
                "Recommended Action": action,
            }
        )

    alerts = pd.DataFrame(records, columns=alert_columns)
    if alerts.empty:
        return alerts
    severity_rank = {"Critical": 0, "Watch": 1}
    alerts["_severity_rank"] = alerts["Severity"].map(severity_rank).fillna(9)
    alerts["_abs_delta"] = alerts["Delta Qty"].abs()
    alerts = alerts.sort_values(
        ["_severity_rank", "Plan Week", "_abs_delta"],
        ascending=[True, False, False],
    ).drop(columns=["_severity_rank", "_abs_delta"])
    return alerts.reset_index(drop=True)


def build_inbound_coverage_alerts(
    current_usage: pd.DataFrame,
    grn_df: pd.DataFrame,
    minimum_gap_qty: float,
) -> pd.DataFrame:
    columns = [
        "Agent",
        "Severity",
        "Plan Week",
        "Buyer",
        "Supplier",
        "Part No.",
        "Part Name",
        "Outwarding Qty",
        "GRN Received Qty",
        "Gap Qty",
        "Last GRN Date",
        "Recommended Action",
    ]
    if current_usage.empty:
        return pd.DataFrame(columns=columns)

    outward = weekly_part_usage_summary(current_usage).rename(
        columns={
            "Buyer": "Outward Buyer",
            "Supplier": "Outward Supplier",
            "Total Demand Qty": "Outwarding Qty",
        }
    )
    if outward.empty:
        return pd.DataFrame(columns=columns)
    outward["Part No."] = outward["Part No."].apply(stock_part_key)
    outward = outward[outward["Part No."].ne("")]

    inward = weekly_grn_receipts_summary(grn_df)
    owner_lookup = load_part_owner_lookup()
    merged = outward.merge(inward, on=["Plan Week", "Part No."], how="left")
    if not owner_lookup.empty:
        merged = merged.merge(owner_lookup, on="Part No.", how="left")
    else:
        merged["Buyer"] = ""
        merged["Mapped Supplier"] = ""

    for column in ["Received Qty", "Production Used Qty", "Servicing Used Qty", "Outwarding Qty"]:
        if column not in merged.columns:
            merged[column] = 0
        merged[column] = numeric(merged[column])
    for column in ["Buyer", "Mapped Supplier", "Outward Buyer", "Outward Supplier", "Inward Supplier", "Part Name", "Last Arrival Date"]:
        if column not in merged.columns:
            merged[column] = ""
        merged[column] = merged[column].fillna("").astype(str)

    merged["Gap Qty"] = merged["Outwarding Qty"] - merged["Received Qty"]
    action_rows = merged[
        (merged["Outwarding Qty"] > 0)
        & (
            merged["Received Qty"].le(0)
            | merged["Gap Qty"].ge(float(minimum_gap_qty))
        )
    ].copy()
    if action_rows.empty:
        return pd.DataFrame(columns=columns)

    records: list[dict[str, object]] = []
    for _, row in action_rows.iterrows():
        outward_qty = scalar_float(row.get("Outwarding Qty", 0))
        received_qty = scalar_float(row.get("Received Qty", 0))
        gap_qty = outward_qty - received_qty
        supplier = (
            clean_text(row.get("Mapped Supplier", ""))
            or clean_text(row.get("Outward Supplier", ""))
            or clean_text(row.get("Inward Supplier", ""))
            or "Unmapped supplier"
        )
        buyer = (
            clean_text(row.get("Buyer", ""))
            or clean_text(row.get("Outward Buyer", ""))
            or "Akshat Taparia, Abhiraj Koslia"
        )
        if received_qty <= 0:
            severity = "Critical"
            issue_action = "No same-week GRN receipt is visible. Check opening stock, pending inwarding, and supplier commitment before issuing to line."
        elif gap_qty / max(outward_qty, 1) >= 0.5:
            severity = "Critical"
            issue_action = "Same-week inwarding covers less than half of outwarding. Confirm stock cover and pull-in requirement."
        else:
            severity = "Watch"
            issue_action = "Outwarding is higher than same-week GRN. Validate opening stock or pending receipts before releasing calls."
        records.append(
            {
                "Agent": "Inbound Coverage Agent",
                "Severity": severity,
                "Plan Week": row.get("Plan Week", ""),
                "Buyer": buyer,
                "Supplier": supplier,
                "Part No.": row.get("Part No.", ""),
                "Part Name": row.get("Part Name", ""),
                "Outwarding Qty": outward_qty,
                "GRN Received Qty": received_qty,
                "Gap Qty": gap_qty,
                "Last GRN Date": row.get("Last Arrival Date", ""),
                "Recommended Action": issue_action,
            }
        )

    alerts = pd.DataFrame(records, columns=columns)
    severity_rank = {"Critical": 0, "Watch": 1}
    alerts["_rank"] = alerts["Severity"].map(severity_rank).fillna(9)
    return (
        alerts.sort_values(["_rank", "Plan Week", "Gap Qty"], ascending=[True, False, False])
        .drop(columns="_rank")
        .reset_index(drop=True)
    )


def build_part_available_stock() -> pd.DataFrame:
    columns = ["Part No.", "Stock Qty", "Stock Basis"]
    spoc_stock = parse_spoc_onsite_stock_raw(load_sheet_snapshot(SPOC_SUMMARY_SNAPSHOT_CSV))
    if not spoc_stock.empty:
        spoc_result = spoc_stock[columns].copy()
    else:
        spoc_result = pd.DataFrame(columns=columns)

    inventory = load_table("part_inventory")
    if inventory.empty:
        return spoc_result

    stock_candidates = [
        ("Physical Stock", "Physical stock"),
        ("Closing Stock", "Closing stock"),
        ("System Stock", "SAP/system stock"),
        ("Opening Stock", "Opening stock"),
    ]
    records: list[dict[str, object]] = []
    for _, row in inventory.iterrows():
        part_no = stock_part_key(row.get("Part No.", ""))
        if not part_no:
            continue
        stock_qty = 0.0
        stock_basis = "No stock source"
        for column, label in stock_candidates:
            value = clean_text(row.get(column, ""))
            if value:
                stock_qty = scalar_float(value)
                stock_basis = label
                break
        records.append(
            {
                "Part No.": part_no,
                "Stock Qty": stock_qty,
                "Stock Basis": stock_basis,
            }
        )

    inventory_stock = pd.DataFrame(records, columns=columns) if records else pd.DataFrame(columns=columns)
    if inventory_stock.empty:
        return spoc_result

    if not spoc_result.empty:
        inventory_stock = inventory_stock[
            ~inventory_stock["Part No."].isin(spoc_result["Part No."])
        ]
    combined = pd.concat([spoc_result, inventory_stock], ignore_index=True)
    if combined.empty:
        return pd.DataFrame(columns=columns)
    return (
        combined.groupby("Part No.", as_index=False)
        .agg(
            **{
                "Stock Qty": ("Stock Qty", "sum"),
                "Stock Basis": ("Stock Basis", joined_text),
            }
        )
        .sort_values("Part No.")
        .reset_index(drop=True)
    )


def allocation_recommendation(
    production_shortfall: float,
    servicing_shortfall: float,
    surplus_qty: float,
) -> tuple[str, str, str]:
    if production_shortfall > 0:
        return (
            "Critical",
            "Production constrained",
            "Reserve the production allocation first, pull in supplier/GRN support, and avoid releasing uncovered line demand.",
        )
    if servicing_shortfall > 0:
        return (
            "Watch",
            "Servicing constrained",
            "Release the allocated servicing quantity only and keep the balance as pending/backorder until more stock is received.",
        )
    if surplus_qty > 0:
        return (
            "OK",
            "Fully covered with surplus",
            "Allocate full production and servicing demand; hold surplus in store or keep it visible for the next call-off.",
        )
    return (
        "OK",
        "Fully covered",
        "Allocate full production and servicing demand.",
    )


def build_allocation_optimizer(
    current_usage: pd.DataFrame,
    grn_df: pd.DataFrame,
    production_guard_pct: float,
    servicing_guard_pct: float,
    production_priority_weight: float,
    servicing_priority_weight: float,
) -> pd.DataFrame:
    columns = [
        "Severity",
        "Plan Week",
        "Buyer",
        "Supplier",
        "Part No.",
        "Part Name",
        "Starting Stock Qty",
        "Starting Stock Source",
        "GRN Received Qty",
        "Confirmed 311 Qty",
        "Pending 311 Qty",
        "Movement Coverage %",
        "Available Qty",
        "Production Demand",
        "Servicing Demand",
        "Production Allocation",
        "Servicing Allocation",
        "Production Shortfall",
        "Servicing Shortfall",
        "Projected Closing Stock",
        "Decision",
        "Recommended Action",
    ]
    usage = weekly_part_usage_summary(current_usage)
    if usage.empty:
        return pd.DataFrame(columns=columns)

    usage = usage.rename(
        columns={
            "Buyer": "Outward Buyer",
            "Supplier": "Outward Supplier",
            "Production Used Qty": "Production Demand",
            "Servicing Demand Qty": "Servicing Demand",
        }
    )
    usage["Part No."] = usage["Part No."].apply(stock_part_key)
    usage = usage[usage["Part No."].ne("")].copy()
    if usage.empty:
        return pd.DataFrame(columns=columns)

    inward = weekly_grn_receipts_summary(grn_df).rename(
        columns={"Received Qty": "GRN Received Qty"}
    )
    movement_311 = weekly_311_movement_summary(load_source_cache(SR_POSTING_SNAPSHOT_PATH))
    stock = build_part_available_stock()
    owners = load_part_owner_lookup()

    allocation = usage.merge(
        inward[["Plan Week", "Part No.", "Inward Supplier", "GRN Received Qty"]],
        on=["Plan Week", "Part No."],
        how="left",
    )
    if not movement_311.empty:
        allocation = allocation.merge(
            movement_311[["Plan Week", "Part No.", "Confirmed 311 Qty", "Pending 311 Qty"]],
            on=["Plan Week", "Part No."],
            how="left",
        )
    else:
        allocation["Confirmed 311 Qty"] = 0
        allocation["Pending 311 Qty"] = 0
    if not stock.empty:
        allocation = allocation.merge(stock, on="Part No.", how="left")
    else:
        allocation["Stock Qty"] = 0
    if not owners.empty:
        allocation = allocation.merge(owners, on="Part No.", how="left")
    else:
        allocation["Buyer"] = ""
        allocation["Mapped Supplier"] = ""

    for column in [
        "Stock Qty",
        "GRN Received Qty",
        "Confirmed 311 Qty",
        "Pending 311 Qty",
        "Production Demand",
        "Servicing Demand",
    ]:
        if column not in allocation.columns:
            allocation[column] = 0
        allocation[column] = numeric(allocation[column])
    for column in ["Buyer", "Mapped Supplier", "Outward Buyer", "Outward Supplier", "Inward Supplier", "Part Name", "Stock Basis"]:
        if column not in allocation.columns:
            allocation[column] = ""
        allocation[column] = allocation[column].fillna("").astype(str)

    production_guard = max(float(production_guard_pct), 0) / 100
    servicing_guard = max(float(servicing_guard_pct), 0) / 100
    production_weight = max(float(production_priority_weight), 0.1)
    servicing_weight = max(float(servicing_priority_weight), 0.1)

    allocation = allocation.sort_values(["Part No.", "Plan Week"]).reset_index(drop=True)
    records: list[dict[str, object]] = []
    for _, part_rows in allocation.groupby("Part No.", sort=False):
        carryover_stock = scalar_float(part_rows.iloc[0].get("Stock Qty", 0))
        for _, row in part_rows.iterrows():
            production_demand = scalar_float(row.get("Production Demand", 0))
            servicing_demand = scalar_float(row.get("Servicing Demand", 0))
            grn_received = scalar_float(row.get("GRN Received Qty", 0))
            confirmed_311 = scalar_float(row.get("Confirmed 311 Qty", 0))
            pending_311 = scalar_float(row.get("Pending 311 Qty", 0))
            total_demand_for_movement = production_demand + servicing_demand
            movement_coverage_pct = (
                confirmed_311 / total_demand_for_movement * 100
                if total_demand_for_movement > 0
                else 0
            )
            starting_stock = carryover_stock
            available_qty = max(starting_stock, 0) + max(grn_received, 0)
            if production_demand <= 0 and servicing_demand <= 0:
                carryover_stock = available_qty
                continue

            remaining = max(available_qty, 0)
            production_allocation = 0.0
            servicing_allocation = 0.0

            protected_production = min(production_demand, production_demand * production_guard)
            protected_servicing = min(servicing_demand, servicing_demand * servicing_guard)

            take = min(remaining, protected_production)
            production_allocation += take
            remaining -= take

            take = min(remaining, protected_servicing)
            servicing_allocation += take
            remaining -= take

            production_gap = max(production_demand - production_allocation, 0)
            servicing_gap = max(servicing_demand - servicing_allocation, 0)
            if remaining > 0 and (production_gap > 0 or servicing_gap > 0):
                weighted_production = production_gap * production_weight
                weighted_servicing = servicing_gap * servicing_weight
                total_weight = weighted_production + weighted_servicing
                if total_weight > 0:
                    extra_production = min(
                        production_gap,
                        remaining * weighted_production / total_weight,
                    )
                    extra_servicing = min(
                        servicing_gap,
                        remaining * weighted_servicing / total_weight,
                    )
                    leftover = remaining - extra_production - extra_servicing
                    if leftover > 0:
                        production_more = min(production_gap - extra_production, leftover)
                        extra_production += production_more
                        leftover -= production_more
                    if leftover > 0:
                        extra_servicing += min(servicing_gap - extra_servicing, leftover)

                    production_allocation += extra_production
                    servicing_allocation += extra_servicing

            production_shortfall = max(production_demand - production_allocation, 0)
            servicing_shortfall = max(servicing_demand - servicing_allocation, 0)
            projected_closing = max(
                available_qty - production_allocation - servicing_allocation,
                0,
            )
            carryover_stock = projected_closing
            severity, decision, recommended_action = allocation_recommendation(
                production_shortfall,
                servicing_shortfall,
                projected_closing,
            )
            supplier = (
                clean_text(row.get("Mapped Supplier", ""))
                or clean_text(row.get("Outward Supplier", ""))
                or clean_text(row.get("Inward Supplier", ""))
                or "Unmapped supplier"
            )
            buyer = (
                clean_text(row.get("Buyer", ""))
                or clean_text(row.get("Outward Buyer", ""))
                or "Akshat Taparia, Abhiraj Koslia"
            )

            records.append(
                {
                    "Severity": severity,
                    "Plan Week": row.get("Plan Week", ""),
                    "Buyer": buyer,
                    "Supplier": supplier,
                    "Part No.": row.get("Part No.", ""),
                    "Part Name": row.get("Part Name", ""),
                    "Starting Stock Qty": starting_stock,
                    "Starting Stock Source": clean_text(row.get("Stock Basis", "")) or "No stock source",
                    "GRN Received Qty": grn_received,
                    "Confirmed 311 Qty": confirmed_311,
                    "Pending 311 Qty": pending_311,
                    "Movement Coverage %": movement_coverage_pct,
                    "Available Qty": available_qty,
                    "Production Demand": production_demand,
                    "Servicing Demand": servicing_demand,
                    "Production Allocation": production_allocation,
                    "Servicing Allocation": servicing_allocation,
                    "Production Shortfall": production_shortfall,
                    "Servicing Shortfall": servicing_shortfall,
                    "Projected Closing Stock": projected_closing,
                    "Decision": decision,
                    "Recommended Action": recommended_action,
                }
            )

    if not records:
        return pd.DataFrame(columns=columns)
    result = pd.DataFrame(records, columns=columns)
    severity_rank = {"Critical": 0, "Watch": 1, "OK": 2}
    result["_rank"] = result["Severity"].map(severity_rank).fillna(9)
    result["_shortfall"] = result["Production Shortfall"] + result["Servicing Shortfall"]
    return (
        result.sort_values(["_rank", "Plan Week", "_shortfall"], ascending=[True, False, False])
        .drop(columns=["_rank", "_shortfall"])
        .reset_index(drop=True)
    )


def append_outwarding_alert_log(alerts: pd.DataFrame) -> pd.DataFrame:
    if alerts.empty:
        return load_outwarding_alert_log()
    log_now = datetime.now().isoformat(timespec="seconds")
    to_log = alerts.copy()
    to_log.insert(0, "Logged At", log_now)
    existing = load_outwarding_alert_log()
    combined = pd.concat([existing, to_log], ignore_index=True) if not existing.empty else to_log
    if "Alert ID" in combined.columns:
        combined = combined.drop_duplicates("Alert ID", keep="last")
    save_source_cache(OUTWARDING_ALERT_LOG_PATH, combined)
    return combined


def outwarding_control_columns() -> list[str]:
    return [
        "Action ID",
        "Severity",
        "Action Type",
        "Plan Week",
        "Buyer",
        "Supplier",
        "Part No.",
        "Part Name",
        "Signals",
        "Starting Stock Qty",
        "GRN Received Qty",
        "Confirmed 311 Qty",
        "Pending 311 Qty",
        "Movement Coverage %",
        "Available Qty",
        "Production Demand",
        "Servicing Demand",
        "Production Allocation",
        "Servicing Allocation",
        "Production Shortfall",
        "Servicing Shortfall",
        "Projected Closing Stock",
        "Inbound Gap Qty",
        "Baseline Qty",
        "Current Qty",
        "Delta Qty",
        "Delta %",
        "Owner Action",
        "Escalation",
        "Closure Rule",
    ]


def outwarding_severity_rank(severity: object) -> int:
    return {
        "Critical": 0,
        "High": 1,
        "Watch": 2,
        "Ready": 3,
        "OK": 3,
    }.get(clean_text(severity), 9)


def highest_outwarding_severity(values: list[str]) -> str:
    if not values:
        return "Ready"
    ordered = sorted(values, key=outwarding_severity_rank)
    return "Ready" if ordered[0] == "OK" else ordered[0]


def outwarding_escalation_text(severity: str) -> str:
    if severity == "Critical":
        return (
            "Immediate escalation: PPC lead, Stores lead, and mapped buyer must "
            "verify stock cover before release. If cover is not proven, hold blind "
            "issue and revise production or pull supplier/GRN support."
        )
    if severity == "High":
        return (
            "Same-day escalation: Stores and SCM buyer validate available stock, "
            "pending GRN, and production-vs-servicing split before material is issued."
        )
    if severity == "Watch":
        return (
            "Monitor and validate: confirm baseline change, stock source, or inbound "
            "evidence before the next shift handover."
        )
    return (
        "Ready to execute: issue only the recommended production and servicing "
        "quantities, then close after scan/MB51 evidence is visible."
    )


def outwarding_closure_rule(severity: str) -> str:
    if severity == "Critical":
        return (
            "Close only when physical stock/GRN evidence covers the production gap, "
            "or PPC records a plan correction."
        )
    if severity == "High":
        return (
            "Close when the buyer or Stores owner confirms the stock source and the "
            "allocation split is accepted."
        )
    if severity == "Watch":
        return (
            "Close after next refresh confirms the signal is no longer present, or "
            "after the owner records the corrected baseline/source."
        )
    return "Close after material issue is posted or scanned at the consuming point."


def build_outwarding_control_actions(
    allocation: pd.DataFrame,
    coverage_alerts: pd.DataFrame,
    change_alerts: pd.DataFrame,
) -> pd.DataFrame:
    columns = outwarding_control_columns()
    records: list[dict[str, object]] = []

    coverage_lookup: dict[str, pd.Series] = {}
    if not coverage_alerts.empty:
        coverage = coverage_alerts.copy()
        coverage["Part Key"] = coverage["Part No."].map(stock_part_key)
        coverage["_key"] = coverage["Plan Week"].astype(str) + "|" + coverage["Part Key"]
        coverage["_rank"] = coverage["Severity"].map(outwarding_severity_rank)
        coverage = coverage.sort_values(["_key", "_rank", "Gap Qty"], ascending=[True, True, False])
        coverage_lookup = {
            row["_key"]: row
            for _, row in coverage.drop_duplicates("_key", keep="first").iterrows()
        }

    change_lookup: dict[str, pd.Series] = {}
    plan_change_rows = pd.DataFrame(columns=change_alerts.columns)
    if not change_alerts.empty:
        changes = change_alerts.copy()
        changes["Part Key"] = changes["Part No."].map(stock_part_key)
        plan_change_rows = changes[changes["Part Key"].eq("")].copy()
        part_changes = changes[changes["Part Key"].ne("")].copy()
        if not part_changes.empty:
            part_changes["_key"] = part_changes["Plan Week"].astype(str) + "|" + part_changes["Part Key"]
            part_changes["_rank"] = part_changes["Severity"].map(outwarding_severity_rank)
            part_changes["_abs_delta"] = numeric(part_changes["Delta Qty"]).abs()
            part_changes = part_changes.sort_values(
                ["_key", "_rank", "_abs_delta"],
                ascending=[True, True, False],
            )
            change_lookup = {
                row["_key"]: row
                for _, row in part_changes.drop_duplicates("_key", keep="first").iterrows()
            }

    if not allocation.empty:
        for _, row in allocation.iterrows():
            part_no = stock_part_key(row.get("Part No.", ""))
            plan_week = clean_text(row.get("Plan Week", ""))
            key = f"{plan_week}|{part_no}"
            coverage = coverage_lookup.get(key)
            change = change_lookup.get(key)

            production_shortfall = scalar_float(row.get("Production Shortfall", 0))
            servicing_shortfall = scalar_float(row.get("Servicing Shortfall", 0))
            projected_closing = scalar_float(row.get("Projected Closing Stock", 0))
            confirmed_311 = scalar_float(row.get("Confirmed 311 Qty", 0))
            pending_311 = scalar_float(row.get("Pending 311 Qty", 0))
            movement_coverage_pct = scalar_float(row.get("Movement Coverage %", 0))
            inbound_gap = scalar_float(coverage.get("Gap Qty", 0)) if coverage is not None else 0
            delta_qty = scalar_float(change.get("Delta Qty", 0)) if change is not None else 0
            delta_pct = scalar_float(change.get("Delta %", 0)) if change is not None else 0

            severities: list[str] = []
            signals: list[str] = []
            actions: list[str] = []
            action_type = "Ready to issue"

            if production_shortfall > 0:
                severities.append("Critical")
                action_type = "Production constrained"
                signals.append(f"Production shortfall {production_shortfall:,.0f}")
                actions.append(
                    "Protect production first; do not release uncovered line demand without PPC approval."
                )
            if servicing_shortfall > 0:
                severities.append("High")
                if action_type == "Ready to issue":
                    action_type = "Servicing constrained"
                signals.append(f"Servicing shortfall {servicing_shortfall:,.0f}")
                actions.append(
                    "Allocate servicing only up to the recommended quantity and keep the balance pending."
                )
            if coverage is not None:
                coverage_severity = clean_text(coverage.get("Severity", "Watch"))
                severities.append("Critical" if coverage_severity == "Critical" else "High")
                if action_type == "Ready to issue":
                    action_type = "Inbound coverage gap"
                signals.append(f"Inbound gap {inbound_gap:,.0f}")
                actions.append(clean_text(coverage.get("Recommended Action", "")))
            if change is not None:
                change_severity = clean_text(change.get("Severity", "Watch"))
                severities.append("Critical" if change_severity == "Critical" else "Watch")
                if action_type == "Ready to issue":
                    action_type = "Plan changed"
                signals.append(f"Demand delta {delta_qty:+,.0f}")
                actions.append(clean_text(change.get("Recommended Action", "")))
            if pending_311 > 0:
                pending_severity = "High" if pending_311 >= max(100, (production_shortfall + servicing_shortfall) * 0.1) else "Watch"
                severities.append(pending_severity)
                if action_type == "Ready to issue":
                    action_type = "311 SR posting pending"
                signals.append(f"311 pending posting {pending_311:,.0f}")
                actions.append(
                    "Close the Stock Request posting or confirm the line movement with SAP posting number evidence."
                )
            if projected_closing > 0 and not signals:
                signals.append(f"Covered with projected closing {projected_closing:,.0f}")
                actions.append(clean_text(row.get("Recommended Action", "")))
            if confirmed_311 > 0 and not any("311" in signal for signal in signals):
                signals.append(f"311 posted {confirmed_311:,.0f} ({movement_coverage_pct:.0f}% of demand)")
            if not signals:
                signals.append("Demand covered exactly")
                actions.append(clean_text(row.get("Recommended Action", "")))

            severity = highest_outwarding_severity(severities)
            records.append(
                {
                    "Action ID": f"outwarding|{plan_week}|{part_no}",
                    "Severity": severity,
                    "Action Type": action_type,
                    "Plan Week": plan_week,
                    "Buyer": clean_text(row.get("Buyer", "")) or "Not mapped",
                    "Supplier": clean_text(row.get("Supplier", "")) or "Unmapped supplier",
                    "Part No.": part_no,
                    "Part Name": clean_text(row.get("Part Name", "")),
                    "Signals": " | ".join(signal for signal in signals if signal),
                    "Starting Stock Qty": scalar_float(row.get("Starting Stock Qty", 0)),
                    "GRN Received Qty": scalar_float(row.get("GRN Received Qty", 0)),
                    "Confirmed 311 Qty": confirmed_311,
                    "Pending 311 Qty": pending_311,
                    "Movement Coverage %": movement_coverage_pct,
                    "Available Qty": scalar_float(row.get("Available Qty", 0)),
                    "Production Demand": scalar_float(row.get("Production Demand", 0)),
                    "Servicing Demand": scalar_float(row.get("Servicing Demand", 0)),
                    "Production Allocation": scalar_float(row.get("Production Allocation", 0)),
                    "Servicing Allocation": scalar_float(row.get("Servicing Allocation", 0)),
                    "Production Shortfall": production_shortfall,
                    "Servicing Shortfall": servicing_shortfall,
                    "Projected Closing Stock": projected_closing,
                    "Inbound Gap Qty": inbound_gap,
                    "Baseline Qty": scalar_float(change.get("Baseline Qty", 0)) if change is not None else 0,
                    "Current Qty": scalar_float(change.get("Current Qty", 0)) if change is not None else 0,
                    "Delta Qty": delta_qty,
                    "Delta %": delta_pct,
                    "Owner Action": " ".join(action for action in actions if action).strip(),
                    "Escalation": outwarding_escalation_text(severity),
                    "Closure Rule": outwarding_closure_rule(severity),
                }
            )

    for _, row in plan_change_rows.iterrows():
        severity = "Critical" if clean_text(row.get("Severity", "")) == "Critical" else "Watch"
        plan_week = clean_text(row.get("Plan Week", ""))
        records.append(
            {
                "Action ID": clean_text(row.get("Alert ID", "")) or f"plan-change|{plan_week}",
                "Severity": severity,
                "Action Type": "Plan-level production change",
                "Plan Week": plan_week,
                "Buyer": clean_text(row.get("Owners", "")) or OUTWARDING_OWNER_DEFAULT,
                "Supplier": "",
                "Part No.": "PLAN",
                "Part Name": clean_text(row.get("Part Name", "")) or "Weekly vehicle production",
                "Signals": f"Vehicle plan delta {scalar_float(row.get('Delta Qty', 0)):+,.0f}",
                "Starting Stock Qty": 0,
                "GRN Received Qty": 0,
                "Confirmed 311 Qty": 0,
                "Pending 311 Qty": 0,
                "Movement Coverage %": 0,
                "Available Qty": 0,
                "Production Demand": 0,
                "Servicing Demand": 0,
                "Production Allocation": 0,
                "Servicing Allocation": 0,
                "Production Shortfall": 0,
                "Servicing Shortfall": 0,
                "Projected Closing Stock": 0,
                "Inbound Gap Qty": 0,
                "Baseline Qty": scalar_float(row.get("Baseline Qty", 0)),
                "Current Qty": scalar_float(row.get("Current Qty", 0)),
                "Delta Qty": scalar_float(row.get("Delta Qty", 0)),
                "Delta %": scalar_float(row.get("Delta %", 0)),
                "Owner Action": clean_text(row.get("Recommended Action", "")),
                "Escalation": outwarding_escalation_text(severity),
                "Closure Rule": outwarding_closure_rule(severity),
            }
        )

    if not records:
        return pd.DataFrame(columns=columns)
    result = pd.DataFrame(records, columns=columns)
    result["_rank"] = result["Severity"].map(outwarding_severity_rank)
    result["_impact"] = (
        numeric(result["Production Shortfall"])
        + numeric(result["Servicing Shortfall"])
        + numeric(result["Inbound Gap Qty"]).clip(lower=0)
        + numeric(result["Delta Qty"]).abs()
        + numeric(result["Pending 311 Qty"])
    )
    return (
        result.sort_values(["_rank", "Plan Week", "_impact"], ascending=[True, False, False])
        .drop(columns=["_rank", "_impact"])
        .reset_index(drop=True)
    )


def render_outwarding_control_flow(
    combined: pd.DataFrame,
    production: pd.DataFrame,
    manual_outwarding: pd.DataFrame,
) -> None:
    st.subheader("Outwarding Control Flow")
    st.write(
        "One operating queue for production and servicing consumption: calculate "
        "demand, check stock and GRN coverage, allocate constrained stock, then "
        "escalate only the exceptions."
    )
    st.markdown(
        """
        <div class="agent-legend">
            <span class="agent-chip">1. Demand</span>
            <span class="agent-chip">2. Coverage</span>
            <span class="agent-chip">3. Allocation</span>
            <span class="agent-chip">4. Escalation</span>
            <span class="agent-chip">5. Closure</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.graphviz_chart(
        """
        digraph Outwarding_Flow {
            graph [rankdir=LR, bgcolor="transparent", pad="0.2", nodesep="0.55", ranksep="0.65"];
            node [shape=box, style="rounded,filled", color="#CBD5E1", fillcolor="#F8FAFC", fontname="Arial", fontsize=11];
            edge [color="#334155", fontname="Arial", fontsize=10, arrowsize=0.75];
            Inputs [label="Production actuals\\n+ Servicing usage"];
            BOM [label="BOM explosion\\npart demand"];
            Cover [label="Opening stock\\n+ same-week GRN"];
            Allocate [label="Production vs servicing\\nallocation"];
            Move [label="311 SR posting evidence\\nconfirmed vs pending"];
            Queue [label="Buyer-owned\\nexception queue"];
            Escalate [label="Critical / High / Watch\\nescalation"];
            Close [label="Close with scan\\nor MB51 evidence"];
            Inputs -> BOM -> Cover -> Allocate -> Move -> Queue -> Escalate -> Close;
        }
        """,
        use_container_width=True,
    )

    baseline = load_outwarding_baseline()
    grn_df = load_grn_sheet_display_snapshot()
    with st.expander("Control settings", expanded=False):
        control_cols = st.columns(4)
        with control_cols[0]:
            owners = st.text_input(
                "Default escalation owners",
                value=OUTWARDING_OWNER_DEFAULT,
                key="outwarding_flow_owners",
            )
        with control_cols[1]:
            production_change_pct = st.number_input(
                "Plan change %",
                min_value=1.0,
                max_value=100.0,
                value=10.0,
                step=1.0,
                key="outwarding_flow_change_pct",
            )
        with control_cols[2]:
            vehicle_delta_threshold = st.number_input(
                "Vehicle delta",
                min_value=1,
                value=50,
                step=10,
                key="outwarding_flow_vehicle_delta",
            )
        with control_cols[3]:
            part_delta_threshold = st.number_input(
                "Part delta",
                min_value=1,
                value=1000,
                step=100,
                key="outwarding_flow_part_delta",
            )
        allocation_cols = st.columns(5)
        with allocation_cols[0]:
            minimum_gap_qty = st.number_input(
                "Inbound gap threshold",
                min_value=1,
                value=100,
                step=50,
                key="outwarding_flow_gap_qty",
            )
        with allocation_cols[1]:
            production_guard_pct = st.slider(
                "Production guard %",
                min_value=0,
                max_value=100,
                value=90,
                step=5,
                key="outwarding_flow_prod_guard",
            )
        with allocation_cols[2]:
            servicing_guard_pct = st.slider(
                "Servicing guard %",
                min_value=0,
                max_value=100,
                value=20,
                step=5,
                key="outwarding_flow_service_guard",
            )
        with allocation_cols[3]:
            production_priority_weight = st.number_input(
                "Production weight",
                min_value=0.1,
                value=3.0,
                step=0.5,
                key="outwarding_flow_prod_weight",
            )
        with allocation_cols[4]:
            servicing_priority_weight = st.number_input(
                "Servicing weight",
                min_value=0.1,
                value=1.0,
                step=0.5,
                key="outwarding_flow_service_weight",
            )
        save_cols = st.columns([1.5, 4.5])
        with save_cols[0]:
            if st.button("Save current baseline", type="primary", key="outwarding_flow_save_baseline"):
                save_outwarding_baseline(combined)
                st.success("Saved current outwarding calculation as the baseline.")
                st.rerun()
        with save_cols[1]:
            if baseline.empty:
                st.caption("No baseline exists yet. Plan-change alerts stay off until you save one trusted baseline.")
            else:
                st.caption(
                    f"Baseline last saved: {snapshot_age_label(OUTWARDING_BASELINE_PATH)}. "
                    f"GRN snapshot: {snapshot_age_label(INWARDING_SNAPSHOT_PATH)}."
                )

    change_alerts = (
        build_outwarding_agent_alerts(
            current_usage=combined,
            baseline_usage=baseline,
            owners=owners,
            reduction_pct_threshold=float(production_change_pct),
            vehicle_delta_threshold=float(vehicle_delta_threshold),
            part_delta_threshold=float(part_delta_threshold),
        )
        if not baseline.empty
        else pd.DataFrame()
    )
    if grn_df.empty:
        st.warning(
            "No saved GRN snapshot is available, so inbound coverage is treated "
            "as a data-confidence gap rather than a supplier escalation. Refresh "
            "Inwarding Parts before trusting coverage decisions."
        )
        coverage_alerts = pd.DataFrame()
    else:
        coverage_alerts = build_inbound_coverage_alerts(
            current_usage=combined,
            grn_df=grn_df,
            minimum_gap_qty=float(minimum_gap_qty),
        )
    allocation = build_allocation_optimizer(
        current_usage=combined,
        grn_df=grn_df,
        production_guard_pct=float(production_guard_pct),
        servicing_guard_pct=float(servicing_guard_pct),
        production_priority_weight=float(production_priority_weight),
        servicing_priority_weight=float(servicing_priority_weight),
    )
    actions = build_outwarding_control_actions(
        allocation=allocation,
        coverage_alerts=coverage_alerts,
        change_alerts=change_alerts,
    )
    if actions.empty:
        st.info("No outwarding demand could be converted into an action queue yet.")
        return

    open_actions = actions[~actions["Severity"].isin(["Ready", "OK"])].copy()
    critical = actions[actions["Severity"].eq("Critical")]
    high = actions[actions["Severity"].eq("High")]
    watch = actions[actions["Severity"].eq("Watch")]
    ready = actions[actions["Severity"].eq("Ready")]
    metric_cols = st.columns(5)
    with metric_cols[0]:
        render_metric("Open escalations", f"{len(open_actions):,}", "warn" if len(open_actions) else "ok")
    with metric_cols[1]:
        render_metric("Critical", f"{len(critical):,}", "bad" if len(critical) else "ok")
    with metric_cols[2]:
        render_metric("High", f"{len(high):,}", "warn" if len(high) else "ok")
    with metric_cols[3]:
        render_metric("Watch", f"{len(watch):,}", "warn" if len(watch) else "ok")
    with metric_cols[4]:
        render_metric("Ready", f"{len(ready):,}", "ok")

    shortage_cols = st.columns(5)
    with shortage_cols[0]:
        render_metric(
            "Production shortfall",
            display_qty(numeric(actions["Production Shortfall"]).sum()),
            "bad" if numeric(actions["Production Shortfall"]).sum() else "ok",
        )
    with shortage_cols[1]:
        render_metric(
            "Servicing shortfall",
            display_qty(numeric(actions["Servicing Shortfall"]).sum()),
            "warn" if numeric(actions["Servicing Shortfall"]).sum() else "ok",
        )
    with shortage_cols[2]:
        render_metric(
            "Inbound gap",
            display_qty(numeric(actions["Inbound Gap Qty"]).clip(lower=0).sum()),
            "bad" if numeric(actions["Inbound Gap Qty"]).clip(lower=0).sum() else "ok",
        )
    with shortage_cols[3]:
        render_metric(
            "311 pending",
            display_qty(numeric(actions["Pending 311 Qty"]).sum()),
            "warn" if numeric(actions["Pending 311 Qty"]).sum() else "ok",
        )
    with shortage_cols[4]:
        render_metric(
            "Projected closing",
            display_qty(numeric(actions["Projected Closing Stock"]).sum()),
            "neutral",
        )

    if not open_actions.empty:
        owner_summary = (
            open_actions.groupby("Buyer", as_index=False)
            .agg(
                Actions=("Action ID", "nunique"),
                Critical=("Severity", lambda values: values.eq("Critical").sum()),
                High=("Severity", lambda values: values.eq("High").sum()),
                ProductionShortfall=("Production Shortfall", "sum"),
                ServicingShortfall=("Servicing Shortfall", "sum"),
                InboundGap=("Inbound Gap Qty", "sum"),
            )
            .sort_values(["Critical", "High", "Actions"], ascending=[False, False, False])
        )
        with st.expander("Buyer escalation summary", expanded=True):
            st.dataframe(
                owner_summary,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "ProductionShortfall": st.column_config.NumberColumn("Production shortfall", format="%.0f"),
                    "ServicingShortfall": st.column_config.NumberColumn("Servicing shortfall", format="%.0f"),
                    "InboundGap": st.column_config.NumberColumn("Inbound gap", format="%.0f"),
                },
            )

    queue_frames = {
        "Critical - act now": critical,
        "High - same day": high,
        "Watch - validate": watch,
        "Ready - execute": ready,
        "All actions": actions,
    }
    queue_labels = {
        name: f"{name} ({len(frame):,})"
        for name, frame in queue_frames.items()
    }
    default_queue = "Critical - act now" if len(critical) else (
        "High - same day" if len(high) else "Watch - validate" if len(watch) else "Ready - execute"
    )
    filter_cols = st.columns([1.3, 1, 1, 0.7])
    with filter_cols[0]:
        queue_name = st.selectbox(
            "Work queue",
            list(queue_frames),
            index=list(queue_frames).index(default_queue),
            format_func=lambda value: queue_labels[value],
            key="outwarding_flow_queue",
        )
    queue = queue_frames[queue_name].copy()
    with filter_cols[1]:
        buyers = sorted(
            queue.get("Buyer", pd.Series(dtype=str))
            .replace("", pd.NA)
            .dropna()
            .unique()
            .tolist()
        )
        selected_buyer = st.selectbox(
            "Buyer",
            ["All buyers"] + buyers,
            key="outwarding_flow_buyer",
        )
    supplier_source = queue
    if selected_buyer != "All buyers":
        supplier_source = supplier_source[supplier_source["Buyer"].eq(selected_buyer)]
    with filter_cols[2]:
        suppliers = sorted(
            supplier_source.get("Supplier", pd.Series(dtype=str))
            .replace("", pd.NA)
            .dropna()
            .unique()
            .tolist()
        )
        selected_supplier = st.selectbox(
            "Supplier",
            ["All suppliers"] + suppliers,
            key=f"outwarding_flow_supplier_{normalize_column_name(selected_buyer)}",
        )
    with filter_cols[3]:
        page_size = st.selectbox("Rows", [10, 25, 50], index=1, key="outwarding_flow_rows")

    search = st.text_input(
        "Search outwarding queue",
        placeholder="part number, part name, supplier, buyer, signal",
        key="outwarding_flow_search",
    )
    filtered = queue.copy()
    if selected_buyer != "All buyers":
        filtered = filtered[filtered["Buyer"].eq(selected_buyer)]
    if selected_supplier != "All suppliers":
        filtered = filtered[filtered["Supplier"].eq(selected_supplier)]
    if search.strip():
        term = search.strip().lower()
        search_columns = ["Part No.", "Part Name", "Supplier", "Buyer", "Signals", "Action Type"]
        filtered = filtered[
            filtered[search_columns]
            .astype(str)
            .apply(lambda column: column.str.lower().str.contains(term, na=False))
            .any(axis=1)
        ]
    if filtered.empty:
        st.success("No outwarding actions match this queue and filter combination.")
        return

    total_pages = max((len(filtered) + page_size - 1) // page_size, 1)
    page_cols = st.columns([1, 4])
    with page_cols[0]:
        page_number = st.number_input(
            "Page",
            min_value=1,
            max_value=total_pages,
            value=1,
            step=1,
            key=f"outwarding_flow_page_{normalize_column_name(queue_name)}",
        )
    with page_cols[1]:
        st.caption(
            f"{len(filtered):,} action(s) · page {page_number} of {total_pages}. "
            "Select one row to inspect evidence and closure criteria."
        )
    start = (int(page_number) - 1) * page_size
    page_frame = filtered.iloc[start : start + page_size].reset_index(drop=True)
    compact = page_frame[
        [
            "Severity",
            "Action Type",
            "Plan Week",
            "Buyer",
            "Supplier",
            "Part No.",
            "Part Name",
            "Production Shortfall",
            "Servicing Shortfall",
            "Inbound Gap Qty",
            "Pending 311 Qty",
            "Signals",
        ]
    ].copy()
    selection = st.dataframe(
        compact,
        use_container_width=True,
        hide_index=True,
        height=min(520, 42 + len(compact) * 38),
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Production Shortfall": st.column_config.NumberColumn(format="%.0f"),
            "Servicing Shortfall": st.column_config.NumberColumn(format="%.0f"),
            "Inbound Gap Qty": st.column_config.NumberColumn(format="%.0f"),
            "Pending 311 Qty": st.column_config.NumberColumn("Pending 311", format="%.0f"),
        },
        key=f"outwarding_flow_selection_{normalize_column_name(queue_name)}_{page_number}",
    )
    selected_rows = (
        selection.selection.rows
        if hasattr(selection, "selection")
        else selection.get("selection", {}).get("rows", [])
    )
    download_cols = st.columns([1.3, 1.3, 3.4])
    with download_cols[0]:
        st.download_button(
            "Download action queue",
            actions.to_csv(index=False),
            file_name="outwarding_control_flow_actions.csv",
            mime="text/csv",
            key="outwarding_flow_download",
        )
    with download_cols[1]:
        if st.button("Log open escalations", disabled=open_actions.empty, key="outwarding_flow_log"):
            loggable = open_actions.rename(columns={"Action ID": "Alert ID"})
            updated_log = append_outwarding_alert_log(loggable)
            st.success(f"Logged {len(open_actions):,} open escalation(s). Log now has {len(updated_log):,} row(s).")
            st.rerun()
    if not selected_rows:
        st.info("Select an outwarding action above to see the exact evidence, escalation, and closure rule.")
        return

    selected = page_frame.iloc[selected_rows[0]].copy()
    st.markdown("#### Selected outwarding action")
    st.markdown(
        f"### {escape(clean_text(selected['Part No.']))} · "
        f"{escape(clean_text(selected['Part Name']) or 'Plan level action')}"
    )
    evidence_cols = st.columns(6)
    with evidence_cols[0]:
        render_metric("Available", display_qty(selected["Available Qty"]), "neutral")
    with evidence_cols[1]:
        render_metric("Production demand", display_qty(selected["Production Demand"]), "neutral")
    with evidence_cols[2]:
        render_metric("Servicing demand", display_qty(selected["Servicing Demand"]), "neutral")
    with evidence_cols[3]:
        render_metric(
            "Production shortfall",
            display_qty(selected["Production Shortfall"]),
            "bad" if scalar_float(selected["Production Shortfall"]) else "ok",
        )
    with evidence_cols[4]:
        render_metric(
            "Inbound gap",
            display_qty(selected["Inbound Gap Qty"]),
            "bad" if scalar_float(selected["Inbound Gap Qty"]) else "ok",
        )
    with evidence_cols[5]:
        render_metric(
            "311 pending",
            display_qty(selected["Pending 311 Qty"]),
            "warn" if scalar_float(selected["Pending 311 Qty"]) else "ok",
        )

    detail_cols = st.columns([1.3, 1])
    with detail_cols[0]:
        st.markdown("**Why it is in the queue**")
        st.write(clean_text(selected["Signals"]) or "No open risk signal.")
        split = pd.DataFrame(
            [
                (
                    "Production",
                    selected["Production Demand"],
                    selected["Production Allocation"],
                    selected["Production Shortfall"],
                ),
                (
                    "Servicing",
                    selected["Servicing Demand"],
                    selected["Servicing Allocation"],
                    selected["Servicing Shortfall"],
                ),
            ],
            columns=["Bucket", "Demand", "Allocated", "Shortfall"],
        )
        st.dataframe(
            split,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Demand": st.column_config.NumberColumn(format="%.0f"),
                "Allocated": st.column_config.NumberColumn(format="%.0f"),
                "Shortfall": st.column_config.NumberColumn(format="%.0f"),
            },
        )
        evidence = pd.DataFrame(
            [
                ("Starting stock", selected["Starting Stock Qty"]),
                ("Same-week GRN", selected["GRN Received Qty"]),
                ("Confirmed 311 movement", selected["Confirmed 311 Qty"]),
                ("Pending 311 posting", selected["Pending 311 Qty"]),
                ("311 movement coverage %", selected["Movement Coverage %"]),
                ("Projected closing", selected["Projected Closing Stock"]),
                ("Baseline qty", selected["Baseline Qty"]),
                ("Current qty", selected["Current Qty"]),
                ("Delta qty", selected["Delta Qty"]),
            ],
            columns=["Evidence", "Value"],
        )
        st.dataframe(
            evidence,
            use_container_width=True,
            hide_index=True,
            column_config={"Value": st.column_config.NumberColumn(format="%.0f")},
        )
    with detail_cols[1]:
        severity = clean_text(selected["Severity"])
        if severity == "Critical":
            st.error(clean_text(selected["Escalation"]))
        elif severity == "High":
            st.warning(clean_text(selected["Escalation"]))
        elif severity == "Watch":
            st.info(clean_text(selected["Escalation"]))
        else:
            st.success(clean_text(selected["Escalation"]))
        st.markdown(
            f"**Buyer:** {escape(clean_text(selected['Buyer']))}  \n"
            f"**Supplier:** {escape(clean_text(selected['Supplier']) or 'Not applicable')}  \n"
            f"**Action type:** {escape(clean_text(selected['Action Type']))}"
        )
        st.markdown("**Owner action**")
        st.write(clean_text(selected["Owner Action"]) or "Execute the recommended allocation.")
        st.markdown("**Closure rule**")
        st.write(clean_text(selected["Closure Rule"]))


def weekly_grn_receipts_summary(grn_df: pd.DataFrame) -> pd.DataFrame:
    columns = ["Plan Week", "Part No.", "Inward Supplier", "Received Qty", "Last Arrival Date"]
    if grn_df.empty:
        return pd.DataFrame(columns=columns)

    prepared = grn_df.copy()
    prepared["Part No."] = prepared["Part No."].apply(stock_part_key)
    prepared["Inward Supplier"] = prepared["Supplier"].apply(normalize_supplier_name)
    prepared["Received Qty"] = numeric(prepared["Rcvd Qty"])
    prepared["Arrival Date Parsed"] = parse_grn_dates(prepared["Arrival Date"])
    prepared = prepared[
        prepared["Part No."].ne("")
        & prepared["Arrival Date Parsed"].notna()
        & (prepared["Received Qty"] > 0)
    ].copy()
    if prepared.empty:
        return pd.DataFrame(columns=columns)

    iso = prepared["Arrival Date Parsed"].dt.isocalendar()
    prepared["Plan Week"] = (
        iso["year"].astype(str)
        + "-W"
        + iso["week"].astype(str).str.zfill(2)
    )
    grouped = (
        prepared.groupby(["Plan Week", "Part No."], as_index=False)
        .agg(
            **{
                "Inward Supplier": ("Inward Supplier", joined_text),
                "Received Qty": ("Received Qty", "sum"),
                "Last Arrival Date": ("Arrival Date Parsed", "max"),
            }
        )
    )
    grouped["Last Arrival Date"] = grouped["Last Arrival Date"].dt.strftime("%Y-%m-%d")
    return grouped[columns]


def load_current_buyer_mapping() -> pd.DataFrame:
    columns = ["Part Number", "Mapped Supplier", "Buyer Name"]
    mapping = clean_buyer_mapping_source(load_source_cache(BUYER_MAPPING_CACHE_PATH))
    if not mapping.empty:
        return mapping

    inwarding = load_source_cache(INWARDING_SNAPSHOT_PATH)
    required_columns = {"Part Number", "Supplier Name", "Buyer Name"}
    if required_columns.issubset(inwarding.columns):
        fallback = inwarding[["Part Number", "Supplier Name", "Buyer Name"]].copy()
        fallback.columns = columns
        fallback = fallback[fallback["Buyer Name"].ne("Not mapped")]
        mapping = clean_buyer_mapping_source(fallback)
        if not mapping.empty:
            return mapping

    return pd.DataFrame(columns=columns)


def load_part_owner_lookup() -> pd.DataFrame:
    columns = ["Part No.", "Buyer", "Mapped Supplier"]
    mapping = load_current_buyer_mapping()
    if not mapping.empty:
        part_lookup = mapping[mapping["Part Number"].ne("")].copy()
        if not part_lookup.empty:
            part_lookup = part_lookup.rename(
                columns={
                    "Part Number": "Part No.",
                    "Buyer Name": "Buyer",
                }
            )
            return (
                part_lookup.groupby("Part No.", as_index=False)
                .agg(
                    **{
                        "Buyer": ("Buyer", joined_text),
                        "Mapped Supplier": ("Mapped Supplier", joined_text),
                    }
                )
                .sort_values("Part No.")
                .reset_index(drop=True)
            )

    raw = load_sheet_snapshot(SPOC_SUMMARY_SNAPSHOT_CSV)
    if raw.empty:
        return pd.DataFrame(columns=columns)
    try:
        parts, _ = parse_spoc_summary_raw(raw)
    except Exception:
        return pd.DataFrame(columns=columns)
    return build_part_owner_lookup(parts)


def load_google_sheet_oauth_raw(
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
    rows = [row + [""] * (width - len(row)) for row in values]
    return pd.DataFrame(rows, dtype=str).fillna(""), selected_sheet


def servicing_usage_columns() -> list[str]:
    return [
        "Usage Date",
        "Part No.",
        "Part Name",
        "Model",
        "SPOC",
        "Supplier",
        "Servicing Required Qty",
        "A Shift Qty",
        "B Shift Qty",
        "C Shift Qty",
        "Servicing Used Qty",
        "Servicing Demand Qty",
        "Servicing GRN Pending Qty",
        "Servicing Allocation Qty",
        "Servicing Source",
        "Reference No.",
        "Remarks",
    ]


def parse_servicing_tab_date(title: object) -> pd.Timestamp | None:
    text = clean_text(title)
    if not text:
        return None

    numeric_date = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b", text)
    if numeric_date:
        day, month, year = numeric_date.groups()
        year_number = int(year) + 2000 if len(year) == 2 else int(year)
        parsed = pd.to_datetime(
            f"{year_number}-{int(month):02d}-{int(day):02d}",
            errors="coerce",
        )
        return None if pd.isna(parsed) else parsed.normalize()

    cleaned = re.sub(r"(?i)\b(\d{1,2})(st|nd|rd|th)\b", r"\1", text)
    month_date = re.search(
        r"\b(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?\b",
        cleaned,
    )
    if month_date:
        day, month_name, year = month_date.groups()
        year_value = year or str(datetime.now().year)
        parsed = pd.to_datetime(
            f"{day} {month_name} {year_value}",
            dayfirst=True,
            errors="coerce",
        )
        return None if pd.isna(parsed) else parsed.normalize()

    return None


def load_google_sheet_oauth_metadata(
    spreadsheet_id: str,
    credentials: Credentials,
) -> list[dict[str, object]]:
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleAuthRequest())
        save_google_credentials(credentials)

    response = requests.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}",
        headers={"Authorization": f"Bearer {credentials.token}"},
        params={"fields": "sheets.properties(sheetId,title,index,hidden)"},
        timeout=20,
    )
    response.raise_for_status()
    return [
        item.get("properties", {})
        for item in response.json().get("sheets", [])
        if item.get("properties", {})
    ]


def parse_servicing_daily_raw(raw: pd.DataFrame, tab_title: str) -> pd.DataFrame:
    columns = servicing_usage_columns()
    plan_date = parse_servicing_tab_date(tab_title)
    if raw.empty or plan_date is None:
        return pd.DataFrame(columns=columns)

    header_index: int | None = None
    for index in range(min(len(raw), 25)):
        normalized = [normalize_column_name(value) for value in raw.iloc[index].tolist()]
        if "part_no" in normalized and "description" in normalized and "total" in normalized:
            header_index = index
            break
    if header_index is None:
        return pd.DataFrame(columns=columns)

    table = raw.iloc[header_index + 1 :].copy()
    table.columns = unique_headers(raw.iloc[header_index].tolist(), raw.shape[1])
    table = table.reset_index(drop=True).fillna("")

    def first_column(candidates: list[str]) -> str | None:
        return first_existing_column(table, candidates)

    def contains_column(*needles: str) -> str | None:
        for column in table.columns:
            normalized = normalize_column_name(column)
            if all(needle in normalized for needle in needles):
                return column
        return None

    part_col = first_column(["Part No", "Part No.", "Part Number", "Material", "Material Code"])
    desc_col = first_column(["Description", "Part Name", "Material Description"])
    if not part_col:
        return pd.DataFrame(columns=columns)

    pna_col = contains_column("pna") or contains_column("requirement")
    total_col = first_column(["Total"])
    balance_col = first_column(["Balance"])
    grn_pending_col = first_column(["GRN Pending"])
    allocation_col = first_column(["Allocation qty", "Allocation Qty", "Allocated Qty"])
    remarks_col = first_column(["Remarks"])
    ppc_comments_col = first_column(["PPC & Store Comments", "PPC Comments", "Store Comments"])
    cpd_comments_col = first_column(["CPD Comments"])

    result = pd.DataFrame(index=table.index)
    result["Usage Date"] = plan_date
    result["Part No."] = table[part_col].apply(stock_part_key)
    result["Part Name"] = (
        table[desc_col].fillna("").astype(str).str.strip() if desc_col else ""
    )
    result["Model"] = column_or_blank(table, ["Model"])
    result["SPOC"] = column_or_blank(table, ["SPOC"])
    result["Supplier"] = ""

    required_qty = numeric(table[pna_col]) if pna_col else pd.Series(0, index=table.index)
    a_shift = numeric(table[first_column(["A"])]) if first_column(["A"]) else pd.Series(0, index=table.index)
    b_shift = numeric(table[first_column(["B"])]) if first_column(["B"]) else pd.Series(0, index=table.index)
    c_shift = numeric(table[first_column(["C"])]) if first_column(["C"]) else pd.Series(0, index=table.index)
    shift_total = a_shift + b_shift + c_shift

    if total_col:
        used_qty = numeric(table[total_col])
        used_qty = used_qty.where(used_qty.gt(0), shift_total)
    else:
        used_qty = shift_total

    calculated_balance = (required_qty - used_qty).clip(lower=0)
    if balance_col:
        balance_text = table[balance_col].apply(clean_text)
        balance_qty = numeric(table[balance_col]).where(balance_text.ne(""), calculated_balance)
    else:
        balance_qty = calculated_balance

    result["Servicing Required Qty"] = required_qty
    result["A Shift Qty"] = a_shift
    result["B Shift Qty"] = b_shift
    result["C Shift Qty"] = c_shift
    result["Servicing Used Qty"] = used_qty
    result["Servicing Demand Qty"] = balance_qty.clip(lower=0)
    result["Servicing GRN Pending Qty"] = (
        numeric(table[grn_pending_col]) if grn_pending_col else pd.Series(0, index=table.index)
    )
    result["Servicing Allocation Qty"] = (
        numeric(table[allocation_col]) if allocation_col else pd.Series(0, index=table.index)
    )
    result["Servicing Source"] = "Live CPD/PNA servicing sheet"
    result["Reference No."] = tab_title

    comment_parts = []
    for column in [ppc_comments_col, cpd_comments_col, remarks_col]:
        if column:
            comment_parts.append(table[column].apply(clean_text))
    if comment_parts:
        comments = comment_parts[0]
        for part in comment_parts[1:]:
            comments = comments.where(part.eq(""), comments + " | " + part)
            comments = comments.where(comments.ne(" | "), part)
        result["Remarks"] = comments.str.strip(" |")
    else:
        result["Remarks"] = ""

    quantity_columns = [
        "Servicing Required Qty",
        "A Shift Qty",
        "B Shift Qty",
        "C Shift Qty",
        "Servicing Used Qty",
        "Servicing Demand Qty",
        "Servicing GRN Pending Qty",
        "Servicing Allocation Qty",
    ]
    result = result[
        result["Part No."].ne("")
        & result[quantity_columns].sum(axis=1).gt(0)
    ].copy()
    return result[columns].reset_index(drop=True)


def refresh_servicing_google_sheet(
    credentials: Credentials,
    lookback_days: int = SERVICING_LOOKBACK_DAYS,
) -> tuple[pd.DataFrame, dict[str, object]]:
    metadata = load_google_sheet_oauth_metadata(SERVICING_SHEET_ID, credentials)
    daily_tabs: list[tuple[pd.Timestamp, dict[str, object]]] = []
    for properties in metadata:
        if properties.get("hidden"):
            continue
        tab_date = parse_servicing_tab_date(properties.get("title", ""))
        if tab_date is not None:
            daily_tabs.append((tab_date, properties))

    if not daily_tabs:
        parsed = pd.DataFrame(columns=servicing_usage_columns())
        save_source_cache(SERVICING_SNAPSHOT_PATH, parsed)
        meta = {
            "source_url": SERVICING_SOURCE_SHEET_URL,
            "rows": 0,
            "tabs": [],
            "copied_at": datetime.now().isoformat(timespec="seconds"),
            "note": "No visible dated servicing tabs were found.",
        }
        SERVICING_SNAPSHOT_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return parsed, meta

    daily_tabs.sort(key=lambda item: item[0])
    latest_date = daily_tabs[-1][0]
    cutoff = latest_date - pd.Timedelta(days=max(int(lookback_days), 1) - 1)
    selected_tabs = [
        (tab_date, properties)
        for tab_date, properties in daily_tabs
        if tab_date >= cutoff
    ]

    parsed_frames: list[pd.DataFrame] = []
    selected_titles: list[str] = []
    for _, properties in selected_tabs:
        gid = properties.get("sheetId")
        title = str(properties.get("title", ""))
        if gid is None:
            continue
        raw, tab_name = load_google_sheet_oauth_raw(
            sheet_url(SERVICING_SHEET_ID, int(gid)),
            credentials,
        )
        parsed = parse_servicing_daily_raw(raw, tab_name)
        if not parsed.empty:
            parsed_frames.append(parsed)
            selected_titles.append(title)

    if parsed_frames:
        result = pd.concat(parsed_frames, ignore_index=True)
    else:
        result = pd.DataFrame(columns=servicing_usage_columns())

    result_to_save = result.copy()
    if not result_to_save.empty:
        result_to_save["Usage Date"] = pd.to_datetime(
            result_to_save["Usage Date"],
            errors="coerce",
        ).dt.strftime("%Y-%m-%d")
    save_source_cache(SERVICING_SNAPSHOT_PATH, result_to_save)
    meta = {
        "source_url": SERVICING_SOURCE_SHEET_URL,
        "rows": int(len(result_to_save)),
        "tabs": selected_titles,
        "latest_tab": selected_titles[-1] if selected_titles else "",
        "lookback_days": int(lookback_days),
        "copied_at": datetime.now().isoformat(timespec="seconds"),
    }
    SERVICING_SNAPSHOT_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return result_to_save, meta


def sr_posting_columns() -> list[str]:
    return [
        "Movement Date",
        "Plan Week",
        "Part No.",
        "Part Name",
        "Movement Type",
        "Requested Qty",
        "Posted Qty Raw",
        "Pending Qty Raw",
        "Confirmed 311 Qty",
        "Pending 311 Qty",
        "UOM",
        "Plant",
        "Source Storage",
        "Destination Line",
        "Shop",
        "Destination Bucket",
        "Route",
        "Shift",
        "SR Number",
        "Posting Number",
        "Posting Status",
        "Picker Name",
        "Poster Name",
        "Models",
        "Evidence Status",
    ]


def classify_sr_destination_bucket(shop: object, line: object) -> str:
    shop_text = clean_text(shop).upper()
    line_text = clean_text(line).upper()
    combined = f"{shop_text} {line_text}"
    if line_text.startswith(("LW", "LB", "LM")) or any(
        token in combined for token in ["WELD", "BATTERY", "MOTOR", "PAINT"]
    ):
        return "Shop"
    if line_text.startswith("LS") or any(
        token in combined for token in ["SUB LINE", "SUB ASSY", "SUB-ASSEMBLY", "SUB ASSEMBLY"]
    ):
        return "SA"
    if line_text.startswith("LG") or any(
        token in combined for token in ["GA", "KITTING", "OBL", "FINAL"]
    ):
        return "GA"
    return "Unmapped"


def parse_sr_posting_date(series: pd.Series) -> pd.Series:
    values = series.fillna("").astype(str).str.strip()
    current_year = pd.Timestamp.now(tz="Asia/Kolkata").year
    with_year = values.where(values.str.contains(r"\d{4}", regex=True), values + f"-{current_year}")
    return pd.to_datetime(with_year, errors="coerce", dayfirst=True)


def parse_sr_311_posting_raw(raw: pd.DataFrame) -> pd.DataFrame:
    columns = sr_posting_columns()
    if raw.empty:
        return pd.DataFrame(columns=columns)

    table = raw.copy().fillna("")
    result = pd.DataFrame(index=table.index)
    result["Movement Date"] = parse_sr_posting_date(column_or_blank(table, ["Date", "Posting Date"]))
    result["Part No."] = column_or_blank(table, ["Part Number", "Part No.", "Material", "MATNR"]).apply(stock_part_key)
    result["Part Name"] = column_or_blank(table, ["PART NAME", "Part Name", "Material Description"])
    result["Movement Type"] = "311"
    result["Requested Qty"] = numeric(column_or_blank(table, ["QTY", "Quantity", "Requested Qty"]))
    result["Posted Qty Raw"] = numeric(column_or_blank(table, ["Posted Qty", "POSTED QTY"]))
    result["Pending Qty Raw"] = numeric(column_or_blank(table, ["Pending Qty", "PENDING QTY"]))
    result["UOM"] = column_or_blank(table, ["UOM"])
    result["Plant"] = column_or_blank(table, ["PLANT", "Plant"])
    result["Source Storage"] = column_or_blank(table, ["STORAGE", "Storage", "Source Storage"])
    result["Destination Line"] = column_or_blank(table, ["LINE", "Line", "Destination Line"])
    result["Shop"] = column_or_blank(table, ["Shop"])
    result["Shift"] = column_or_blank(table, ["SHIFT", "Shift"])
    result["SR Number"] = column_or_blank(table, ["SR NUMBER", "SR NO", "SR Number"])
    result["Posting Number"] = column_or_blank(table, ["POSTING NO", "Posting No", "Posting Number"])
    result["Posting Status"] = column_or_blank(table, ["Posting Status", "Posting Status "])
    result["Picker Name"] = column_or_blank(table, ["PICKER NAME", "Picker Name"])
    result["Poster Name"] = column_or_blank(table, ["Poster Name", "Poster\n Name", "Pending Poster Name"])
    result["Models"] = column_or_blank(table, ["MODELS", "Models"])

    status_lower = result["Posting Status"].astype(str).str.lower()
    is_closed = status_lower.str.contains("closed|close|posted", na=False)
    has_posting_number = result["Posting Number"].astype(str).str.strip().ne("")
    posted_raw = numeric(result["Posted Qty Raw"])
    requested_qty = numeric(result["Requested Qty"])
    pending_raw = numeric(result["Pending Qty Raw"])

    confirmed_qty = posted_raw.copy()
    closed_or_posted = is_closed | has_posting_number
    confirmed_qty = confirmed_qty.where(~(closed_or_posted & confirmed_qty.le(0)), requested_qty)
    confirmed_qty = confirmed_qty.clip(lower=0)

    pending_qty = pending_raw.copy()
    no_explicit_pending = pending_qty.le(0)
    pending_qty = pending_qty.where(
        ~no_explicit_pending,
        (requested_qty - confirmed_qty).clip(lower=0),
    )
    pending_qty = pending_qty.where(~(closed_or_posted & no_explicit_pending), 0)
    pending_qty = pending_qty.clip(lower=0)

    result["Confirmed 311 Qty"] = confirmed_qty
    result["Pending 311 Qty"] = pending_qty
    result["Destination Bucket"] = [
        classify_sr_destination_bucket(shop, line)
        for shop, line in zip(result["Shop"], result["Destination Line"])
    ]
    result["Route"] = result["Destination Bucket"].map(
        {
            "GA": "HS01 Store -> HS01 GA",
            "SA": "HS01 Store -> HS01 SA",
            "Shop": "HS01 Store -> HS01 Shop",
        }
    ).fillna("311 route unmapped")
    result["Evidence Status"] = "Pending SR posting"
    result.loc[result["Confirmed 311 Qty"].gt(0), "Evidence Status"] = "Confirmed 311 posting"
    result.loc[
        result["Confirmed 311 Qty"].gt(0) & result["Pending 311 Qty"].gt(0),
        "Evidence Status",
    ] = "Partially posted"

    valid = (
        result["Part No."].ne("")
        & result["Movement Date"].notna()
        & (result["Requested Qty"].gt(0) | result["Confirmed 311 Qty"].gt(0) | result["Pending 311 Qty"].gt(0))
    )
    result = result.loc[valid].copy()
    if result.empty:
        return pd.DataFrame(columns=columns)

    iso = result["Movement Date"].dt.isocalendar()
    result["Plan Week"] = (
        iso["year"].astype(str)
        + "-W"
        + iso["week"].astype(str).str.zfill(2)
    )
    result["Movement Date"] = result["Movement Date"].dt.strftime("%Y-%m-%d")
    return result[columns].reset_index(drop=True)


def refresh_sr_311_posting_google_sheet(
    credentials: Credentials,
) -> tuple[pd.DataFrame, dict[str, object]]:
    raw, tab_name = load_google_sheet_oauth(SR_POSTING_SOURCE_SHEET_URL, credentials)
    parsed = parse_sr_311_posting_raw(raw)
    save_source_cache(SR_POSTING_SNAPSHOT_PATH, parsed)
    meta = {
        "source_url": SR_POSTING_SOURCE_SHEET_URL,
        "sheet_tab": tab_name,
        "rows": int(len(parsed)),
        "copied_at": datetime.now().isoformat(timespec="seconds"),
        "note": "SR means Stock Request / Store Requisition; rows are normalized as SAP 311 internal movement evidence.",
    }
    SR_POSTING_SNAPSHOT_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return parsed, meta


def weekly_311_movement_summary(movement_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Plan Week",
        "Part No.",
        "Confirmed 311 Qty",
        "Pending 311 Qty",
        "Last 311 Date",
        "311 Routes",
        "Open SR Count",
    ]
    if movement_df.empty:
        return pd.DataFrame(columns=columns)

    movement = movement_df.copy()
    movement["Part No."] = movement["Part No."].apply(stock_part_key)
    movement["Movement Date Parsed"] = pd.to_datetime(movement["Movement Date"], errors="coerce")
    if "Plan Week" not in movement.columns or movement["Plan Week"].astype(str).str.strip().eq("").all():
        iso = movement["Movement Date Parsed"].dt.isocalendar()
        movement["Plan Week"] = (
            iso["year"].astype(str)
            + "-W"
            + iso["week"].astype(str).str.zfill(2)
        )
    for column in ["Confirmed 311 Qty", "Pending 311 Qty"]:
        movement[column] = numeric(movement.get(column, pd.Series(index=movement.index)))
    movement = movement[
        movement["Part No."].ne("")
        & movement["Plan Week"].astype(str).str.strip().ne("")
        & (movement["Confirmed 311 Qty"].gt(0) | movement["Pending 311 Qty"].gt(0))
    ].copy()
    if movement.empty:
        return pd.DataFrame(columns=columns)

    movement["Open SR Flag"] = movement["Pending 311 Qty"].gt(0).astype(int)
    grouped = (
        movement.groupby(["Plan Week", "Part No."], as_index=False)
        .agg(
            **{
                "Confirmed 311 Qty": ("Confirmed 311 Qty", "sum"),
                "Pending 311 Qty": ("Pending 311 Qty", "sum"),
                "Last 311 Date": ("Movement Date Parsed", "max"),
                "311 Routes": ("Route", joined_text),
                "Open SR Count": ("Open SR Flag", "sum"),
            }
        )
    )
    grouped["Last 311 Date"] = grouped["Last 311 Date"].dt.strftime("%Y-%m-%d")
    return grouped[columns]


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



def render_google_oauth_controls(key_prefix: str, expanded: bool = False) -> Credentials | None:
    oauth_settings = google_oauth_settings()
    credentials = load_google_credentials()
    with st.expander("Google Sheets authorization", expanded=expanded or credentials is None):
        if credentials is not None:
            st.success("Google account is connected for read-only Sheets access.")
            if st.button("Disconnect Google Sheets account", key=f"{key_prefix}_disconnect_oauth"):
                clear_google_oauth()
                st.rerun()
            return credentials

        if oauth_settings:
            st.success("Google OAuth client is saved.")
            st.caption(f"Redirect URI: {oauth_settings['redirect_uri']}")
        else:
            st.warning("Google OAuth client is not saved yet.")

        with st.form(f"{key_prefix}_oauth_settings_form"):
            st.write("Use this to read private Google Sheets from your Google account.")
            client_id = st.text_input(
                "Google OAuth Client ID",
                value=oauth_settings["client_id"] if oauth_settings else "",
                key=f"{key_prefix}_oauth_client_id",
            )
            client_secret = st.text_input(
                "Google OAuth Client Secret",
                value=oauth_settings["client_secret"] if oauth_settings else "",
                type="password",
                key=f"{key_prefix}_oauth_client_secret",
            )
            redirect_uri = st.text_input(
                "Redirect URI",
                value=oauth_settings["redirect_uri"] if oauth_settings else "http://localhost:8501/",
                help="This must exactly match the authorized redirect URI in Google Cloud.",
                key=f"{key_prefix}_oauth_redirect_uri",
            )
            saved_oauth = st.form_submit_button("Save Google OAuth settings", type="primary")
        if saved_oauth:
            ok, message = save_google_oauth_settings(client_id, client_secret, redirect_uri)
            if ok:
                st.success(message)
                st.rerun()
            st.error(message)

        oauth_settings = google_oauth_settings()
        if oauth_settings:
            authorization_url = begin_google_oauth(oauth_settings)
            st.link_button(
                "Connect Google account for Sheets",
                authorization_url,
                type="primary",
            )
            st.caption("Use a Google account that has Viewer access to the source sheets.")

    return load_google_credentials()

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
    inventory, diagnostics = build_part_inventory_plan(
        load_table("part_inventory"),
        sources,
        delta_threshold=float(
            st.session_state.get("pvin_delta_threshold", 10.0)
        ),
    )
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
                    "No inventory snapshot is available. Refresh all data once.",
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
    critical_parts = int(
        (stock_available & inventory["Status"].eq("Critical")).sum()
    )
    shortage_parts = int(
        (stock_available & operational_shortage.gt(0)).sum()
    )
    supplier_parts = int(
        (stock_available & supplier_required.gt(0)).sum()
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

    metric_columns = st.columns(5)
    with metric_columns[0]:
        render_metric(
            "Plan / produced",
            f"{plan_target} / {total_production}",
            "neutral",
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
        render_metric("Line-risk parts", f"{shortage_parts:,}", "warn")
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
        )
        st.button(
            "Open action centre",
            key="overview_open_actions",
            on_click=lambda: st.session_state.update(
                {"inventory_management_workflow": "Action Centre"}
            ),
            width="stretch",
        )

    st.subheader(
        "Recommended management actions",
        help="A deterministic daily brief generated from the current exception queues.",
    )
    action_columns = st.columns(3)
    action_cards = [
        (
            "Protect production",
            "bad",
            f"Prioritize {critical_parts:,} critical and {shortage_parts:,} total "
            "line-risk parts by required-by date.",
        ),
        (
            "Control supply",
            "warn",
            f"Confirm quantities and ETAs for {supplier_parts:,} parts with a "
            "system-stock requirement.",
        ),
        (
            "Prevent excess",
            "neutral",
            f"Review {len(excess):,} potential month-end excess signals before "
            "changing any supplier commitment.",
        ),
    ]
    for column, (title, tone, description) in zip(action_columns, action_cards):
        with column:
            with st.container(border=True):
                st.markdown(f"**{title}**")
                st.caption(description)

    shortage_queue = inventory[
        stock_available & operational_shortage.gt(0)
    ].copy()
    shortage_queue["Operational Shortage"] = operational_shortage.loc[
        shortage_queue.index
    ]
    shortage_queue = shortage_queue.sort_values(
        "Operational Shortage",
        ascending=False,
    ).head(5)
    delta_queue = inventory[inventory["Delta Flag"].eq("Review")].copy()
    delta_queue = delta_queue.reindex(
        delta_queue["Unexplained Delta"].abs().sort_values(
            ascending=False
        ).index
    ).head(5)
    master_queue = inventory[
        ~stock_available | unmapped_mask
    ].head(5)
    if not overdue.empty:
        overdue = overdue.merge(
            inventory[
                ["Part No.", "Part Name", "Buyer", "Supplier"]
            ].drop_duplicates("Part No."),
            on="Part No.",
            how="left",
        )
    inventory_cases = load_inventory_control_cases()
    inwarding_actions = load_agent_actions()
    resolved_dates = pd.concat(
        [
            pd.to_datetime(
                inventory_cases.get("Resolved At", pd.Series(dtype=str)),
                errors="coerce",
            ),
            pd.to_datetime(
                inwarding_actions.get("Resolved At", pd.Series(dtype=str)),
                errors="coerce",
            ),
        ],
        ignore_index=True,
    )
    newly_resolved = int(
        resolved_dates.dt.normalize().eq(plan_date).sum()
    )
    overdue_buyers = sorted(
        overdue.get("Buyer", pd.Series(dtype=str))
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    st.subheader(
        "Management briefing",
        help=(
            "The top five risks, overdue commitments, unexplained deltas and "
            "master-data decisions requiring attention."
        ),
    )
    (
        risk_tab,
        overdue_tab,
        delta_tab,
        master_tab,
    ) = st.tabs(
        [
            f"Top risks ({len(shortage_queue):,})",
            f"Overdue commitments ({overdue_count:,})",
            f"Delta review ({len(delta_queue):,})",
            f"Data decisions ({len(master_queue):,})",
        ]
    )
    with risk_tab:
        if shortage_queue.empty:
            st.success("No operational shortages in the current snapshot.")
        else:
            st.dataframe(
                shortage_queue[
                    [
                        "Part No.",
                        "Part Name",
                        "Buyer",
                        "Operational Shortage",
                        "Status",
                    ]
                ],
                width="stretch",
                hide_index=True,
                height=240,
            )
    with overdue_tab:
        if overdue.empty:
            st.success("No supplier commitment is overdue.")
        else:
            st.dataframe(
                overdue.head(5)[
                    [
                        "Part No.",
                        "Part Name",
                        "Buyer",
                        "Supplier",
                        "Next Expected Qty",
                        "Expected Delivery",
                        "Next Follow-up",
                        "Supplier Status",
                    ]
                ],
                width="stretch",
                hide_index=True,
                height=240,
            )
    with delta_tab:
        if delta_queue.empty:
            st.success("No unexplained stock delta exceeds the alert threshold.")
        else:
            st.dataframe(
                delta_queue[
                    [
                        "Part No.",
                        "Part Name",
                        "Buyer",
                        "Stock Delta",
                        "Expected Delta",
                        "Unexplained Delta",
                    ]
                ],
                width="stretch",
                hide_index=True,
                height=240,
            )
    with master_tab:
        if master_queue.empty:
            st.success("No missing-stock or buyer-mapping decision is open.")
        else:
            st.dataframe(
                master_queue[
                    [
                        "Part No.",
                        "Part Name",
                        "Buyer",
                        "Supplier",
                        "Stock Data Status",
                        "SCM Stock Match",
                    ]
                ],
                width="stretch",
                hide_index=True,
                height=240,
            )

    st.info(
        f"**Management decision:** protect {critical_parts:,} critical parts, close "
        f"{overdue_count:,} overdue supplier commitments, review "
        f"{len(delta_queue):,} large unexplained deltas, and validate "
        f"{len(excess):,} potential month-end excess signals. Potential excess "
        "remains indicative until open POs and safety stock are available."
    )
    st.caption(
        f"Potential production impact is shown in each selected risk · "
        f"buyers with overdue actions: "
        f"{', '.join(overdue_buyers[:6]) if overdue_buyers else 'none'} · "
        f"newly verified resolved today: {newly_resolved:,} · "
        f"decisions requiring validation: {len(delta_queue) + len(excess):,}."
    )


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
                    "No inventory snapshot is available. Refresh all data once.",
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
                    "No inventory snapshot is available. Refresh all data once.",
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
                    "No inventory snapshot is available. Refresh all data once.",
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
                    "No inventory snapshot is available. Refresh all data once.",
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



def load_rm_movement_plan() -> pd.DataFrame:
    if not RM_MOVEMENT_PLAN_PATH.exists():
        return pd.DataFrame(columns=RM_MOVEMENT_COLUMNS)
    frame = pd.read_csv(RM_MOVEMENT_PLAN_PATH, dtype=str).fillna("")
    for column in RM_MOVEMENT_COLUMNS:
        if column not in frame:
            frame[column] = ""
    return frame[RM_MOVEMENT_COLUMNS]


def save_rm_movement_plan(frame: pd.DataFrame) -> None:
    cleaned = frame.copy().fillna("")
    for column in RM_MOVEMENT_COLUMNS:
        if column not in cleaned:
            cleaned[column] = ""
    existing = load_rm_movement_plan()
    if not existing.empty:
        existing = existing.copy()
        existing["_key"] = (
            existing["Plan Date"].astype(str)
            + "|"
            + existing["Part No."].map(stock_part_key)
        )
        cleaned["_key"] = (
            cleaned["Plan Date"].astype(str)
            + "|"
            + cleaned["Part No."].map(stock_part_key)
        )
        existing = existing[~existing["_key"].isin(cleaned["_key"])]
        cleaned = pd.concat(
            [existing.drop(columns="_key"), cleaned.drop(columns="_key")],
            ignore_index=True,
        )
    RM_MOVEMENT_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = RM_MOVEMENT_PLAN_PATH.with_suffix(".tmp")
    cleaned[RM_MOVEMENT_COLUMNS].to_csv(tmp_path, index=False)
    tmp_path.replace(RM_MOVEMENT_PLAN_PATH)


def allocate_capped_quantities(
    weights: pd.Series,
    caps: pd.Series,
    total: float,
) -> pd.Series:
    caps = pd.to_numeric(caps, errors="coerce").fillna(0).clip(lower=0)
    weights = pd.to_numeric(weights, errors="coerce").fillna(0).clip(lower=0)
    target = int(round(min(max(float(total), 0), float(caps.sum()))))
    allocation = pd.Series(0, index=caps.index, dtype=int)
    remaining = target
    while remaining > 0:
        capacity = caps - allocation
        active = capacity[capacity.gt(0)]
        if active.empty:
            break
        active_weights = weights.reindex(active.index).fillna(0)
        if active_weights.sum() <= 0:
            active_weights = active
        batch = allocate_integer_quantities(active_weights, remaining)
        batch = batch.clip(upper=active.astype(int))
        if int(batch.sum()) <= 0:
            best = active_weights.sort_values(ascending=False).index[0]
            batch = pd.Series(0, index=active.index, dtype=int)
            batch.loc[best] = 1
        allocation.loc[batch.index] += batch.astype(int)
        next_remaining = target - int(allocation.sum())
        if next_remaining == remaining:
            break
        remaining = next_remaining
    return allocation.astype(int)


def backlog_series(values: pd.Series) -> pd.Series:
    backlog = 0.0
    records: list[float] = []
    for value in pd.to_numeric(values, errors="coerce").fillna(0):
        backlog = max(backlog + float(value), 0.0)
        records.append(backlog)
    return pd.Series(records, index=values.index, dtype=float)


def build_vin_gap_transit_signal(
    sources: dict[str, pd.DataFrame],
    plan_date: pd.Timestamp,
) -> pd.DataFrame:
    columns = [
        "Part No.",
        "VIN Gap Transit Qty",
        "Daily VIN Gap Part Qty",
        "Cumulative VIN Gap Vehicles",
        "VIN Gap Source",
    ]
    if not sources:
        return pd.DataFrame(columns=columns)

    sku_map = parse_sku_map(sources.get("sku_map", pd.DataFrame()))
    plan_actual, _ = parse_vin_detail_plan_actual(
        sources.get("vin_details", pd.DataFrame()),
        sku_map,
    )
    exploded_bom = sources.get("exploded_bom", pd.DataFrame())
    required_bom = {"FG", "Component", "Qty per FG (exploded)"}
    if plan_actual.empty or not required_bom.issubset(exploded_bom.columns):
        return pd.DataFrame(columns=columns)

    cutoff_date = pd.Timestamp(plan_date).normalize()
    gap = plan_actual.copy()
    gap["Plan Date"] = pd.to_datetime(gap["Plan Date"], errors="coerce").dt.normalize()
    gap = gap[gap["Plan Date"].notna() & gap["Plan Date"].le(cutoff_date)].copy()
    if gap.empty:
        return pd.DataFrame(columns=columns)

    gap["FG"] = gap["FG"].astype(str).str.strip()
    gap["Detailed Plan Qty"] = numeric(gap["Detailed Plan Qty"])
    gap["Produced Qty"] = numeric(gap["Produced Qty"])
    gap = (
        gap.groupby(["Plan Date", "FG"], as_index=False)[
            ["Detailed Plan Qty", "Produced Qty"]
        ]
        .sum()
        .sort_values(["FG", "Plan Date"])
    )
    gap["Daily VIN Delta"] = gap["Detailed Plan Qty"] - gap["Produced Qty"]
    gap["Daily VIN Gap Qty"] = gap["Daily VIN Delta"].clip(lower=0)
    gap["Cumulative VIN Gap Vehicles"] = (
        gap.groupby("FG", group_keys=False)["Daily VIN Delta"]
        .apply(backlog_series)
        .clip(lower=0)
    )
    latest_gap = gap.drop_duplicates("FG", keep="last")
    latest_gap = latest_gap[
        latest_gap["Cumulative VIN Gap Vehicles"].gt(0)
        | latest_gap["Daily VIN Gap Qty"].gt(0)
    ].copy()
    if latest_gap.empty:
        return pd.DataFrame(columns=columns)

    bom = exploded_bom[["FG", "Component", "Qty per FG (exploded)"]].copy()
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
    exploded_gap = latest_gap.merge(bom[["FG", "Component", "Qty per FG"]], on="FG")
    if exploded_gap.empty:
        return pd.DataFrame(columns=columns)

    exploded_gap["VIN Gap Transit Qty"] = (
        exploded_gap["Cumulative VIN Gap Vehicles"] * exploded_gap["Qty per FG"]
    )
    exploded_gap["Daily VIN Gap Part Qty"] = (
        exploded_gap["Daily VIN Gap Qty"] * exploded_gap["Qty per FG"]
    )
    result = (
        exploded_gap.groupby("Component", as_index=False)
        .agg(
            {
                "VIN Gap Transit Qty": "sum",
                "Daily VIN Gap Part Qty": "sum",
                "Cumulative VIN Gap Vehicles": "sum",
            }
        )
        .rename(columns={"Component": "Part No."})
    )
    result["VIN Gap Source"] = (
        "cumulative planned/possible VIN gap x exploded BOM"
    )
    return result[columns]


def build_rm_movement_input(
    inventory: pd.DataFrame,
    today_view: pd.DataFrame,
    meta: dict[str, object],
    sources: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    if inventory.empty:
        return pd.DataFrame(columns=RM_MOVEMENT_COLUMNS)

    plan_ts = pd.Timestamp(meta.get("plan_date", pd.Timestamp.now())).normalize()
    plan_date = plan_ts.strftime("%Y-%m-%d")
    base = inventory.copy()
    base["Part Key"] = base["Part No."].map(stock_part_key)
    base["System Stock"] = numeric(base.get("System Stock", pd.Series(index=base.index)))
    base["Store Stock"] = numeric(base.get("Physical Stock", pd.Series(index=base.index)))
    base["Stock Difference Transit Qty"] = (
        base["System Stock"] - base["Store Stock"]
    ).clip(lower=0)
    base["VIN Gap Transit Qty"] = 0.0
    base["Transit Source"] = "stock difference"
    vin_gap_signal = build_vin_gap_transit_signal(sources or {}, plan_ts)
    if not vin_gap_signal.empty:
        vin_gap_signal = vin_gap_signal.copy()
        vin_gap_signal["Part Key"] = vin_gap_signal["Part No."].map(stock_part_key)
        vin_gap_signal = vin_gap_signal.drop_duplicates("Part Key").set_index("Part Key")
        base["VIN Gap Transit Qty"] = (
            base["Part Key"].map(vin_gap_signal["VIN Gap Transit Qty"]).fillna(0)
        )
    base["In Transit Qty"] = pd.concat(
        [
            base["Stock Difference Transit Qty"],
            base["VIN Gap Transit Qty"],
        ],
        axis=1,
    ).max(axis=1)
    base["Transit Source"] = "stock difference"
    base.loc[
        base["VIN Gap Transit Qty"].gt(base["Stock Difference Transit Qty"]),
        "Transit Source",
    ] = "VIN gap backlog"
    base.loc[
        base["In Transit Qty"].le(0),
        "Transit Source",
    ] = "not visible"

    shortage = today_view.copy()
    if not shortage.empty:
        shortage["Part Key"] = shortage["Part No."].map(stock_part_key)
        shortage = shortage.drop_duplicates("Part Key").set_index("Part Key")
        base["GA Line Need"] = base["Part Key"].map(shortage["RM Shortage"]).fillna(0)
        base["Required By"] = base["Part Key"].map(shortage["Required By"]).fillna("")
        base["Severity"] = base["Part Key"].map(shortage["Severity"]).fillna("")
    else:
        base["GA Line Need"] = 0
        base["Required By"] = ""
        base["Severity"] = ""

    movement = base[
        [
            "Buyer",
            "Supplier",
            "Part No.",
            "Part Name",
            "System Stock",
            "Store Stock",
            "In Transit Qty",
            "Stock Difference Transit Qty",
            "VIN Gap Transit Qty",
            "Transit Source",
            "GA Line Need",
            "Required By",
            "Severity",
        ]
    ].copy()
    movement["Plan Date"] = plan_date
    movement["SA Line Need"] = 0
    movement["Shop Need"] = 0
    movement["GA Priority"] = movement["Severity"].map(
        {"Critical": 3.0, "High": 2.2, "Medium": 1.6}
    ).fillna(1.5)
    movement["SA Priority"] = 1.2
    movement["Shop Priority"] = 1.0
    movement["In Transit Override"] = ""
    movement["Remarks"] = ""

    saved = load_rm_movement_plan()
    if not saved.empty:
        saved = saved.copy()
        saved = saved[saved["Plan Date"].astype(str).eq(plan_date)]
        saved["Part Key"] = saved["Part No."].map(stock_part_key)
        saved = saved.drop_duplicates("Part Key", keep="last").set_index("Part Key")
        movement["Part Key"] = movement["Part No."].map(stock_part_key)
        editable_columns = [
            "In Transit Override",
            "GA Line Need",
            "SA Line Need",
            "Shop Need",
            "GA Priority",
            "SA Priority",
            "Shop Priority",
            "Remarks",
        ]
        for column in editable_columns:
            if column in saved:
                values = movement["Part Key"].map(saved[column]).fillna("")
                if column.endswith("Need") or column.endswith("Priority"):
                    movement[column] = values.where(
                        values.astype(str).str.strip().ne(""),
                        movement[column],
                    )
                else:
                    movement[column] = values
        movement = movement.drop(columns="Part Key")

    numeric_columns = [
        "System Stock",
        "Store Stock",
        "In Transit Qty",
        "Stock Difference Transit Qty",
        "VIN Gap Transit Qty",
        "GA Line Need",
        "SA Line Need",
        "Shop Need",
        "GA Priority",
        "SA Priority",
        "Shop Priority",
    ]
    for column in numeric_columns:
        movement[column] = numeric(movement[column])

    movement = movement[
        numeric(movement["In Transit Qty"]).gt(0)
        | numeric(movement["GA Line Need"]).gt(0)
        | numeric(movement["SA Line Need"]).gt(0)
        | numeric(movement["Shop Need"]).gt(0)
    ].copy()
    if movement.empty:
        return pd.DataFrame(columns=RM_MOVEMENT_COLUMNS)

    return movement[RM_MOVEMENT_COLUMNS].sort_values(
        ["GA Line Need", "In Transit Qty", "Supplier", "Part No."],
        ascending=[False, False, True, True],
    ).reset_index(drop=True)


def build_rm_movement_allocations(movement_input: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Decision",
        "Plan Date",
        "Buyer",
        "Supplier",
        "Part No.",
        "Part Name",
        "System Stock",
        "Store Stock",
        "In Transit Qty",
        "Stock Difference Transit Qty",
        "VIN Gap Transit Qty",
        "Transit Source",
        "Demand Total",
        "GA Need",
        "SA Need",
        "Shop Need",
        "GA Allocated",
        "SA Allocated",
        "Shop Allocated",
        "GA Gap",
        "SA Gap",
        "Shop Gap",
        "a Store -> GA",
        "b Store -> SA",
        "c Store -> Shop",
        "d Shop -> SA",
        "e Shop -> GA",
        "f SA -> GA",
        "Allocated Transit",
        "Unallocated Transit",
        "Uncovered Demand",
        "Severity",
        "Escalation",
        "Owner Action",
        "Recommended Action",
    ]
    if movement_input.empty:
        return pd.DataFrame(columns=columns)

    records: list[dict[str, object]] = []
    for _, row in movement_input.iterrows():
        system_stock = scalar_float(row.get("System Stock", 0))
        store_stock = scalar_float(row.get("Store Stock", 0))
        stock_difference_transit = scalar_float(
            row.get(
                "Stock Difference Transit Qty",
                max(system_stock - store_stock, 0),
            )
        )
        vin_gap_transit = scalar_float(row.get("VIN Gap Transit Qty", 0))
        prepared_in_transit = scalar_float(
            row.get(
                "In Transit Qty",
                max(stock_difference_transit, vin_gap_transit),
            )
        )
        override = pd.to_numeric(
            pd.Series([row.get("In Transit Override", "")]),
            errors="coerce",
        ).iloc[0]
        in_transit = (
            float(override)
            if pd.notna(override) and float(override) >= 0
            else prepared_in_transit
        )
        transit_source = clean_text(row.get("Transit Source", ""))
        if pd.notna(override) and float(override) >= 0:
            transit_source = "manual override"

        demands = pd.Series(
            {
                "GA": scalar_float(row.get("GA Line Need", 0)),
                "SA": scalar_float(row.get("SA Line Need", 0)),
                "Shop": scalar_float(row.get("Shop Need", 0)),
            },
            dtype=float,
        ).clip(lower=0)
        priorities = pd.Series(
            {
                "GA": scalar_float(row.get("GA Priority", 1.5)) or 1.5,
                "SA": scalar_float(row.get("SA Priority", 1.2)) or 1.2,
                "Shop": scalar_float(row.get("Shop Priority", 1.0)) or 1.0,
            },
            dtype=float,
        ).clip(lower=0.1)
        demand_total = float(demands.sum())
        destination_alloc = allocate_capped_quantities(
            demands * priorities,
            demands,
            in_transit,
        )

        route_values = {
            "a Store -> GA": 0,
            "b Store -> SA": 0,
            "c Store -> Shop": 0,
            "d Shop -> SA": 0,
            "e Shop -> GA": 0,
            "f SA -> GA": 0,
        }
        ga_alloc = int(destination_alloc.get("GA", 0))
        sa_alloc = int(destination_alloc.get("SA", 0))
        shop_alloc = int(destination_alloc.get("Shop", 0))
        if ga_alloc > 0:
            ga_routes = allocate_integer_quantities(
                pd.Series(
                    {
                        "a Store -> GA": 1.0,
                        "f SA -> GA": 0.9,
                        "e Shop -> GA": 0.75,
                    }
                ),
                ga_alloc,
            )
            route_values.update(ga_routes.to_dict())
        if sa_alloc > 0:
            sa_routes = allocate_integer_quantities(
                pd.Series({"b Store -> SA": 0.85, "d Shop -> SA": 0.7}),
                sa_alloc,
            )
            route_values.update(sa_routes.to_dict())
        route_values["c Store -> Shop"] = shop_alloc

        allocated = float(sum(route_values.values()))
        unallocated = max(in_transit - allocated, 0)
        ga_gap = max(float(demands.get("GA", 0)) - ga_alloc, 0)
        sa_gap = max(float(demands.get("SA", 0)) - sa_alloc, 0)
        shop_gap = max(float(demands.get("Shop", 0)) - shop_alloc, 0)
        uncovered = ga_gap + sa_gap + shop_gap
        if in_transit <= 0:
            decision = "No in-transit stock"
            action = "No movement split can be created until stock is visible in transit."
        elif demand_total <= 0:
            decision = "Demand missing"
            action = "Do not force movement. Capture GA, SA, or shop demand before releasing material."
        elif uncovered > 0:
            decision = "Insufficient transit"
            action = "Release the recommended split, then escalate the uncovered demand or pull from store stock."
        elif unallocated > 0:
            decision = "Demand covered with surplus"
            action = "Move the recommended quantity and hold surplus in store or keep it visible for the next call-off."
        else:
            decision = "Fully allocated"
            action = "Release the route split and track scan confirmation at each receiving point."
        if ga_gap > 0:
            severity = "Critical"
            escalation = "PPC lead + Stores lead now"
            owner_action = "Protect GA first: move feasible quantity, then escalate uncovered GA demand."
        elif sa_gap > 0:
            severity = "High"
            escalation = "Area owner + SCM buyer today"
            owner_action = "Protect SA feed and confirm whether GA can be buffered from existing line stock."
        elif shop_gap > 0:
            severity = "High"
            escalation = "Shop owner + Stores lead today"
            owner_action = "Move feasible shop quantity and flag risk to upstream operation owner."
        elif demand_total <= 0 and in_transit > 0:
            severity = "Watch"
            escalation = "Stores SPOC by next review"
            owner_action = "Do not release blindly. Trace the material and capture the correct destination demand."
        elif unallocated > 0:
            severity = "Watch"
            escalation = "Stores SPOC by next review"
            owner_action = "Hold surplus visibly or assign it to the next confirmed call-off."
        else:
            severity = "OK"
            escalation = "Scan confirmation"
            owner_action = "Execute the movement split and close after destination scan-in."

        records.append(
            {
                "Decision": decision,
                "Plan Date": row.get("Plan Date", ""),
                "Buyer": row.get("Buyer", ""),
                "Supplier": row.get("Supplier", ""),
                "Part No.": row.get("Part No.", ""),
                "Part Name": row.get("Part Name", ""),
                "System Stock": system_stock,
                "Store Stock": store_stock,
                "In Transit Qty": in_transit,
                "Stock Difference Transit Qty": stock_difference_transit,
                "VIN Gap Transit Qty": vin_gap_transit,
                "Transit Source": transit_source,
                "Demand Total": demand_total,
                "GA Need": float(demands.get("GA", 0)),
                "SA Need": float(demands.get("SA", 0)),
                "Shop Need": float(demands.get("Shop", 0)),
                "GA Allocated": ga_alloc,
                "SA Allocated": sa_alloc,
                "Shop Allocated": shop_alloc,
                "GA Gap": ga_gap,
                "SA Gap": sa_gap,
                "Shop Gap": shop_gap,
                **route_values,
                "Allocated Transit": allocated,
                "Unallocated Transit": unallocated,
                "Uncovered Demand": uncovered,
                "Severity": severity,
                "Escalation": escalation,
                "Owner Action": owner_action,
                "Recommended Action": action,
            }
        )

    result = pd.DataFrame(records, columns=columns)
    decision_rank = {
        "Insufficient transit": 0,
        "No in-transit stock": 1,
        "Demand missing": 2,
        "Demand covered with surplus": 3,
        "Fully allocated": 4,
    }
    result["_rank"] = result["Decision"].map(decision_rank).fillna(9)
    severity_rank = {"Critical": 0, "High": 1, "Watch": 2, "OK": 3}
    result["_severity_rank"] = result["Severity"].map(severity_rank).fillna(9)
    return (
        result.sort_values(
            ["_severity_rank", "_rank", "Uncovered Demand", "In Transit Qty"],
            ascending=[True, True, False, False],
        )
        .drop(columns=["_rank", "_severity_rank"])
        .reset_index(drop=True)
    )


def rm_mdp_route_specs() -> list[dict[str, str]]:
    return [
        {
            "lane": "a Store -> GA",
            "from": "Store",
            "to": "GA",
            "sap": "311",
        },
        {
            "lane": "b Store -> SA",
            "from": "Store",
            "to": "SA",
            "sap": "311",
        },
        {
            "lane": "c Store -> Shop",
            "from": "Store",
            "to": "Shop",
            "sap": "311",
        },
        {
            "lane": "d Shop -> SA",
            "from": "Shop",
            "to": "SA",
            "sap": "311",
        },
        {
            "lane": "e Shop -> GA",
            "from": "Shop",
            "to": "GA",
            "sap": "311",
        },
        {
            "lane": "f SA -> GA",
            "from": "SA",
            "to": "GA",
            "sap": "311",
        },
    ]


def rm_mdp_state_frame(
    state: tuple[int, int, int, int, int, int],
    unit_size: int,
    label: str,
) -> pd.DataFrame:
    buckets = ["Store", "Shop", "SA", "GA", "Unknown Transit", "Rework/Hold"]
    return pd.DataFrame(
        {
            "Bucket": buckets,
            label: [int(value) * int(unit_size) for value in state],
        }
    )


def rm_mdp_generate_actions(
    state: tuple[int, int, int, int, int, int],
    max_move_units: int,
) -> list[tuple[int, int, int, int, int, int]]:
    store, shop, sa, _, _, _ = state
    max_move_units = max(int(max_move_units), 0)
    actions: list[tuple[int, int, int, int, int, int]] = []
    for a in range(min(store, max_move_units) + 1):
        for b in range(min(store - a, max_move_units - a) + 1):
            for c in range(min(store - a - b, max_move_units - a - b) + 1):
                store_out = a + b + c
                remaining_after_store = max_move_units - store_out
                for d in range(min(shop, remaining_after_store) + 1):
                    for e in range(min(shop - d, remaining_after_store - d) + 1):
                        remaining_after_shop = remaining_after_store - d - e
                        for f in range(min(sa, remaining_after_shop) + 1):
                            actions.append((a, b, c, d, e, f))
    return actions or [(0, 0, 0, 0, 0, 0)]


def rm_mdp_action_heuristic(
    action: tuple[int, int, int, int, int, int],
    params: dict[str, float | int],
) -> float:
    a, b, c, d, e, f = action
    ga_feed = a + e + f
    sa_feed = b + d
    shop_feed = c
    total_move = sum(action)
    return (
        float(params["ga_shortage_cost"]) * min(ga_feed, int(params["ga_demand"]))
        + float(params["sa_shortage_cost"]) * min(sa_feed, int(params["sa_demand"]))
        + float(params["shop_shortage_cost"]) * min(shop_feed, int(params["shop_demand"]))
        - float(params["handling_cost"]) * total_move
    )


def rm_mdp_transition(
    state: tuple[int, int, int, int, int, int],
    action: tuple[int, int, int, int, int, int],
    params: dict[str, float | int],
) -> tuple[tuple[int, int, int, int, int, int], float, dict[str, float]]:
    store, shop, sa, ga, transit, rework = [float(value) for value in state]

    store += float(params["daily_inbound"])

    transit_recovered = transit * float(params["transit_recovery_rate"])
    transit -= transit_recovered
    store += transit_recovered

    rework_recovered = rework * float(params["rework_recovery_rate"])
    rework -= rework_recovered
    store += rework_recovered

    buckets = {
        "Store": store,
        "Shop": shop,
        "SA": sa,
        "GA": ga,
        "Unknown Transit": transit,
        "Rework/Hold": rework,
    }

    route_specs = rm_mdp_route_specs()
    event_total = (
        float(params["delay_rate"])
        + float(params["retract_rate"])
        + float(params["rework_rate"])
    )
    success_rate = max(0.0, 1.0 - event_total)
    dispatched_units = 0.0
    expected_success = 0.0
    expected_retracted = 0.0
    expected_rework = 0.0
    expected_delayed = 0.0
    for quantity, route in zip(action, route_specs):
        quantity = float(quantity)
        if quantity <= 0:
            continue
        source = route["from"]
        destination = route["to"]
        buckets[source] -= quantity
        success_qty = quantity * success_rate
        retract_qty = quantity * float(params["retract_rate"])
        rework_qty = quantity * float(params["rework_rate"])
        delay_qty = quantity * float(params["delay_rate"])
        buckets[destination] += success_qty
        buckets[source] += retract_qty
        buckets["Rework/Hold"] += rework_qty
        buckets["Unknown Transit"] += delay_qty
        dispatched_units += quantity
        expected_success += success_qty
        expected_retracted += retract_qty
        expected_rework += rework_qty
        expected_delayed += delay_qty

    shortages = {
        "Shop": max(float(params["shop_demand"]) - buckets["Shop"], 0.0),
        "SA": max(float(params["sa_demand"]) - buckets["SA"], 0.0),
        "GA": max(float(params["ga_demand"]) - buckets["GA"], 0.0),
    }
    for bucket, shortage in shortages.items():
        buckets[bucket] = max(buckets[bucket] - float(params[f"{bucket.lower()}_demand"]), 0.0)

    congestion = (
        max(buckets["Shop"] - float(params["shop_capacity"]), 0.0)
        + max(buckets["SA"] - float(params["sa_capacity"]), 0.0)
        + max(buckets["GA"] - float(params["ga_capacity"]), 0.0)
    )
    shortage_cost = (
        shortages["GA"] * float(params["ga_shortage_cost"])
        + shortages["SA"] * float(params["sa_shortage_cost"])
        + shortages["Shop"] * float(params["shop_shortage_cost"])
    )
    handling_cost = dispatched_units * float(params["handling_cost"])
    congestion_cost = congestion * float(params["congestion_cost"])
    uncertainty_cost = (
        buckets["Unknown Transit"] + buckets["Rework/Hold"]
    ) * float(params["uncertainty_cost"])
    cost = shortage_cost + handling_cost + congestion_cost + uncertainty_cost

    next_state = tuple(
        max(int(round(buckets[bucket])), 0)
        for bucket in ["Store", "Shop", "SA", "GA", "Unknown Transit", "Rework/Hold"]
    )
    details = {
        "shortage_units": sum(shortages.values()),
        "ga_shortage_units": shortages["GA"],
        "sa_shortage_units": shortages["SA"],
        "shop_shortage_units": shortages["Shop"],
        "dispatched_units": dispatched_units,
        "expected_success_units": expected_success,
        "expected_retracted_units": expected_retracted,
        "expected_rework_units": expected_rework,
        "expected_delayed_units": expected_delayed,
        "transit_recovered_units": transit_recovered,
        "rework_recovered_units": rework_recovered,
        "congestion_units": congestion,
        "shortage_cost": shortage_cost,
        "handling_cost": handling_cost,
        "congestion_cost": congestion_cost,
        "uncertainty_cost": uncertainty_cost,
        "total_cost": cost,
    }
    return next_state, -cost, details


def rm_mdp_terminal_value(
    state: tuple[int, int, int, int, int, int],
    params: dict[str, float | int],
) -> float:
    store, shop, sa, ga, transit, rework = state
    readiness_value = ga * 1.6 + sa * 1.1 + shop * 0.8 + store * 0.25
    risk_penalty = (transit + rework) * float(params["uncertainty_cost"])
    return readiness_value - risk_penalty


def solve_rm_mdp_pilot(
    initial_state: tuple[int, int, int, int, int, int],
    params: dict[str, float | int],
) -> tuple[float, dict[tuple[int, tuple[int, ...]], dict[str, object]]]:
    horizon = int(params["horizon_days"])
    discount = float(params["discount"])
    max_candidates = int(params["candidate_limit"])
    memo: dict[tuple[int, tuple[int, ...]], float] = {}
    policy: dict[tuple[int, tuple[int, ...]], dict[str, object]] = {}

    def evaluate(day: int, state: tuple[int, int, int, int, int, int]) -> float:
        key = (day, state)
        if key in memo:
            return memo[key]
        if day > horizon:
            value = rm_mdp_terminal_value(state, params)
            memo[key] = value
            return value

        actions = rm_mdp_generate_actions(state, int(params["max_move_units"]))
        actions = sorted(
            actions,
            key=lambda item: rm_mdp_action_heuristic(item, params),
            reverse=True,
        )[:max_candidates]
        best_value = float("-inf")
        best_result: dict[str, object] = {}
        for action in actions:
            next_state, reward, details = rm_mdp_transition(state, action, params)
            candidate_value = reward + discount * evaluate(day + 1, next_state)
            if candidate_value > best_value:
                best_value = candidate_value
                best_result = {
                    "action": action,
                    "next_state": next_state,
                    "reward": reward,
                    "details": details,
                    "value": candidate_value,
                }
        memo[key] = best_value
        policy[key] = best_result
        return best_value

    value = evaluate(1, initial_state)
    return value, policy


def rm_mdp_action_frame(
    action: tuple[int, int, int, int, int, int],
    unit_size: int,
) -> pd.DataFrame:
    rows = []
    for quantity, route in zip(action, rm_mdp_route_specs()):
        rows.append(
            {
                "Lane": route["lane"],
                "From": route["from"],
                "To": route["to"],
                "Recommended Qty": int(quantity) * int(unit_size),
                "SAP movement mapping": route["sap"],
            }
        )
    return pd.DataFrame(rows)


def build_rm_mdp_rollout(
    initial_state: tuple[int, int, int, int, int, int],
    params: dict[str, float | int],
    policy: dict[tuple[int, tuple[int, ...]], dict[str, object]],
) -> pd.DataFrame:
    state = initial_state
    unit_size = int(params["unit_size"])
    records: list[dict[str, object]] = []
    for day in range(1, int(params["horizon_days"]) + 1):
        decision = policy.get((day, state), {})
        action = decision.get("action", (0, 0, 0, 0, 0, 0))
        next_state = decision.get("next_state", state)
        details = decision.get("details", {})
        route_qty = {
            spec["lane"]: int(qty) * unit_size
            for qty, spec in zip(action, rm_mdp_route_specs())
        }
        records.append(
            {
                "Day": day,
                "Start Store": state[0] * unit_size,
                "Start Shop": state[1] * unit_size,
                "Start SA": state[2] * unit_size,
                "Start GA": state[3] * unit_size,
                **route_qty,
                "Expected good arrival": round(
                    float(details.get("expected_success_units", 0)) * unit_size,
                    1,
                ),
                "Expected delayed/retracted/rework": round(
                    (
                        float(details.get("expected_delayed_units", 0))
                        + float(details.get("expected_retracted_units", 0))
                        + float(details.get("expected_rework_units", 0))
                    )
                    * unit_size,
                    1,
                ),
                "GA shortage": round(float(details.get("ga_shortage_units", 0)) * unit_size, 1),
                "SA shortage": round(float(details.get("sa_shortage_units", 0)) * unit_size, 1),
                "Shop shortage": round(float(details.get("shop_shortage_units", 0)) * unit_size, 1),
                "End Store": next_state[0] * unit_size,
                "End Shop": next_state[1] * unit_size,
                "End SA": next_state[2] * unit_size,
                "End GA": next_state[3] * unit_size,
                "End Unknown Transit": next_state[4] * unit_size,
                "End Rework/Hold": next_state[5] * unit_size,
                "Expected cost": round(float(details.get("total_cost", 0)), 2),
            }
        )
        state = next_state
    return pd.DataFrame(records)


def render_rm_mdp_pilot() -> None:
    st.subheader("MDP Pilot: RM Movement Policy")
    st.write(
        "An interactive pilot for deciding RM movements before live scan data is "
        "available. It treats Store, Shop, SA, GA, Unknown Transit, and Rework/Hold "
        "as the state, and the six movement lanes as the action."
    )
    st.info(
        "This is a controlled pilot, not a black-box model. Every assumption is "
        "visible and editable. Later, delay/rework/retraction probabilities can be "
        "learned from MB51, Mendix scan events, and physical movement history."
    )

    presets = {
        "Critical GA shortage": {
            "store": 120,
            "shop": 40,
            "sa": 20,
            "ga": 10,
            "transit": 30,
            "rework": 10,
            "ga_demand": 70,
            "sa_demand": 20,
            "shop_demand": 15,
            "daily_inbound": 20,
            "delay_pct": 12,
            "retract_pct": 6,
            "rework_pct": 4,
        },
        "SA bottleneck": {
            "store": 140,
            "shop": 55,
            "sa": 5,
            "ga": 45,
            "transit": 20,
            "rework": 5,
            "ga_demand": 45,
            "sa_demand": 45,
            "shop_demand": 20,
            "daily_inbound": 15,
            "delay_pct": 10,
            "retract_pct": 4,
            "rework_pct": 3,
        },
        "Rework-heavy day": {
            "store": 110,
            "shop": 35,
            "sa": 25,
            "ga": 20,
            "transit": 55,
            "rework": 45,
            "ga_demand": 65,
            "sa_demand": 25,
            "shop_demand": 15,
            "daily_inbound": 10,
            "delay_pct": 15,
            "retract_pct": 8,
            "rework_pct": 10,
        },
        "Balanced flow": {
            "store": 180,
            "shop": 50,
            "sa": 40,
            "ga": 35,
            "transit": 15,
            "rework": 5,
            "ga_demand": 55,
            "sa_demand": 25,
            "shop_demand": 20,
            "daily_inbound": 25,
            "delay_pct": 8,
            "retract_pct": 3,
            "rework_pct": 2,
        },
    }
    preset_name = st.selectbox(
        "Pilot scenario",
        list(presets),
        key="rm_mdp_preset",
        help="Use this to quickly explain different factory conditions.",
    )
    defaults = presets[preset_name]
    preset_key = re.sub(r"[^a-z0-9]+", "_", preset_name.lower()).strip("_")

    setup_cols = st.columns(4)
    with setup_cols[0]:
        part_name = st.text_input(
            "Example part",
            value="M3 battery bracket / shared RM",
            key=f"rm_mdp_part_{preset_key}",
        )
    with setup_cols[1]:
        unit_size = st.selectbox(
            "Planning unit size",
            [5, 10, 25, 50],
            index=1,
            key=f"rm_mdp_unit_{preset_key}",
            help="The MDP works in lots so the state space stays readable.",
        )
    with setup_cols[2]:
        horizon_days = st.slider(
            "Planning horizon",
            min_value=1,
            max_value=4,
            value=3,
            key=f"rm_mdp_horizon_{preset_key}",
        )
    with setup_cols[3]:
        max_move_units = st.slider(
            "Max movement lots/day",
            min_value=1,
            max_value=5,
            value=4,
            key=f"rm_mdp_max_move_{preset_key}",
        )

    st.markdown("#### Current state")
    state_cols = st.columns(6)
    state_inputs = {}
    for col, label, default in zip(
        state_cols,
        ["Store", "Shop", "SA", "GA", "Unknown Transit", "Rework/Hold"],
        [
            defaults["store"],
            defaults["shop"],
            defaults["sa"],
            defaults["ga"],
            defaults["transit"],
            defaults["rework"],
        ],
    ):
        with col:
            state_inputs[label] = st.number_input(
                label,
                min_value=0,
                value=int(default),
                step=int(unit_size),
                key=f"rm_mdp_state_{preset_key}_{label}",
            )

    st.markdown("#### Demand, reliability, and constraints")
    demand_cols = st.columns(4)
    with demand_cols[0]:
        ga_demand = st.number_input(
            "GA demand/day",
            min_value=0,
            value=int(defaults["ga_demand"]),
            step=int(unit_size),
            key=f"rm_mdp_ga_demand_{preset_key}",
        )
    with demand_cols[1]:
        sa_demand = st.number_input(
            "SA demand/day",
            min_value=0,
            value=int(defaults["sa_demand"]),
            step=int(unit_size),
            key=f"rm_mdp_sa_demand_{preset_key}",
        )
    with demand_cols[2]:
        shop_demand = st.number_input(
            "Shop demand/day",
            min_value=0,
            value=int(defaults["shop_demand"]),
            step=int(unit_size),
            key=f"rm_mdp_shop_demand_{preset_key}",
        )
    with demand_cols[3]:
        daily_inbound = st.number_input(
            "Daily GRN/inbound",
            min_value=0,
            value=int(defaults["daily_inbound"]),
            step=int(unit_size),
            key=f"rm_mdp_inbound_{preset_key}",
        )

    reliability_cols = st.columns(5)
    with reliability_cols[0]:
        delay_pct = st.slider(
            "Delay %",
            min_value=0,
            max_value=40,
            value=int(defaults["delay_pct"]),
            key=f"rm_mdp_delay_{preset_key}",
        )
    with reliability_cols[1]:
        retract_pct = st.slider(
            "Retract %",
            min_value=0,
            max_value=30,
            value=int(defaults["retract_pct"]),
            key=f"rm_mdp_retract_{preset_key}",
        )
    with reliability_cols[2]:
        rework_pct = st.slider(
            "Rework %",
            min_value=0,
            max_value=30,
            value=int(defaults["rework_pct"]),
            key=f"rm_mdp_rework_{preset_key}",
        )
    with reliability_cols[3]:
        transit_recovery_pct = st.slider(
            "Transit trace recovery %",
            min_value=0,
            max_value=100,
            value=45,
            key=f"rm_mdp_transit_recovery_{preset_key}",
        )
    with reliability_cols[4]:
        rework_recovery_pct = st.slider(
            "Rework recovery %",
            min_value=0,
            max_value=100,
            value=35,
            key=f"rm_mdp_rework_recovery_{preset_key}",
        )

    with st.expander("Advanced cost and capacity settings"):
        cost_cols = st.columns(4)
        with cost_cols[0]:
            ga_shortage_cost = st.number_input(
                "GA shortage cost",
                min_value=1.0,
                value=12.0,
                step=1.0,
                key=f"rm_mdp_ga_cost_{preset_key}",
            )
        with cost_cols[1]:
            sa_shortage_cost = st.number_input(
                "SA shortage cost",
                min_value=1.0,
                value=7.0,
                step=1.0,
                key=f"rm_mdp_sa_cost_{preset_key}",
            )
        with cost_cols[2]:
            shop_shortage_cost = st.number_input(
                "Shop shortage cost",
                min_value=1.0,
                value=4.0,
                step=1.0,
                key=f"rm_mdp_shop_cost_{preset_key}",
            )
        with cost_cols[3]:
            handling_cost = st.number_input(
                "Handling cost",
                min_value=0.0,
                value=0.8,
                step=0.1,
                key=f"rm_mdp_handling_cost_{preset_key}",
            )
        capacity_cols = st.columns(5)
        with capacity_cols[0]:
            shop_capacity = st.number_input(
                "Shop capacity",
                min_value=0,
                value=120,
                step=int(unit_size),
                key=f"rm_mdp_shop_capacity_{preset_key}",
            )
        with capacity_cols[1]:
            sa_capacity = st.number_input(
                "SA capacity",
                min_value=0,
                value=110,
                step=int(unit_size),
                key=f"rm_mdp_sa_capacity_{preset_key}",
            )
        with capacity_cols[2]:
            ga_capacity = st.number_input(
                "GA capacity",
                min_value=0,
                value=120,
                step=int(unit_size),
                key=f"rm_mdp_ga_capacity_{preset_key}",
            )
        with capacity_cols[3]:
            congestion_cost = st.number_input(
                "Congestion cost",
                min_value=0.0,
                value=1.2,
                step=0.1,
                key=f"rm_mdp_congestion_cost_{preset_key}",
            )
        with capacity_cols[4]:
            uncertainty_cost = st.number_input(
                "Uncertainty cost",
                min_value=0.0,
                value=1.8,
                step=0.1,
                key=f"rm_mdp_uncertainty_cost_{preset_key}",
            )
        model_cols = st.columns(2)
        with model_cols[0]:
            discount = st.slider(
                "Future importance",
                min_value=0.50,
                max_value=0.98,
                value=0.86,
                step=0.02,
                key=f"rm_mdp_discount_{preset_key}",
            )
        with model_cols[1]:
            candidate_limit = st.selectbox(
                "Actions evaluated per state",
                [60, 120, 200],
                index=1,
                key=f"rm_mdp_candidate_limit_{preset_key}",
            )

    event_total_pct = delay_pct + retract_pct + rework_pct
    if event_total_pct >= 95:
        st.warning(
            "Delay + retract + rework is too high for a useful pilot. The model "
            "will cap success at a very small value."
        )

    def to_units(value: object) -> int:
        return max(int(round(float(value) / float(unit_size))), 0)

    initial_state = (
        to_units(state_inputs["Store"]),
        to_units(state_inputs["Shop"]),
        to_units(state_inputs["SA"]),
        to_units(state_inputs["GA"]),
        to_units(state_inputs["Unknown Transit"]),
        to_units(state_inputs["Rework/Hold"]),
    )
    params: dict[str, float | int] = {
        "unit_size": int(unit_size),
        "horizon_days": int(horizon_days),
        "max_move_units": int(max_move_units),
        "candidate_limit": int(candidate_limit),
        "discount": float(discount),
        "daily_inbound": to_units(daily_inbound),
        "ga_demand": to_units(ga_demand),
        "sa_demand": to_units(sa_demand),
        "shop_demand": to_units(shop_demand),
        "delay_rate": float(delay_pct) / 100.0,
        "retract_rate": float(retract_pct) / 100.0,
        "rework_rate": float(rework_pct) / 100.0,
        "transit_recovery_rate": float(transit_recovery_pct) / 100.0,
        "rework_recovery_rate": float(rework_recovery_pct) / 100.0,
        "ga_shortage_cost": float(ga_shortage_cost),
        "sa_shortage_cost": float(sa_shortage_cost),
        "shop_shortage_cost": float(shop_shortage_cost),
        "handling_cost": float(handling_cost),
        "shop_capacity": to_units(shop_capacity),
        "sa_capacity": to_units(sa_capacity),
        "ga_capacity": to_units(ga_capacity),
        "congestion_cost": float(congestion_cost),
        "uncertainty_cost": float(uncertainty_cost),
    }

    with st.spinner("Solving compact MDP pilot..."):
        value, policy = solve_rm_mdp_pilot(initial_state, params)
    day_one = policy.get((1, initial_state), {})
    day_one_action = day_one.get("action", (0, 0, 0, 0, 0, 0))
    day_one_next = day_one.get("next_state", initial_state)
    day_one_details = day_one.get("details", {})
    action_frame = rm_mdp_action_frame(day_one_action, int(unit_size))
    recommended_total = int(action_frame["Recommended Qty"].sum())

    metrics = st.columns(5)
    with metrics[0]:
        render_metric("Recommended move", display_qty(recommended_total), "ok" if recommended_total else "warn")
    with metrics[1]:
        render_metric(
            "Expected good arrival",
            display_qty(float(day_one_details.get("expected_success_units", 0)) * int(unit_size)),
            "ok",
        )
    with metrics[2]:
        render_metric(
            "Expected shortage",
            display_qty(float(day_one_details.get("shortage_units", 0)) * int(unit_size)),
            "bad" if float(day_one_details.get("shortage_units", 0)) else "ok",
        )
    with metrics[3]:
        render_metric(
            "Transit/rework risk",
            display_qty(
                (
                    float(day_one_details.get("expected_delayed_units", 0))
                    + float(day_one_details.get("expected_rework_units", 0))
                    + float(day_one_details.get("expected_retracted_units", 0))
                )
                * int(unit_size)
            ),
            "warn",
        )
    with metrics[4]:
        render_metric("Policy value", f"{value:,.1f}", "neutral")

    st.markdown(f"#### Day-1 policy for {escape(part_name)}")
    if recommended_total <= 0:
        st.warning(
            "The pilot recommends holding material because the movement risk/cost "
            "is higher than the expected shortage benefit under the current assumptions."
        )
    else:
        st.success(
            "The pilot recommends moving the routes below. Quantities are rounded "
            "to the selected planning unit."
        )
    st.dataframe(
        action_frame,
        use_container_width=True,
        hide_index=True,
        column_config={"Recommended Qty": st.column_config.NumberColumn(format="%.0f")},
    )
    chart_frame = action_frame.set_index("Lane")[["Recommended Qty"]]
    st.bar_chart(chart_frame, use_container_width=True)

    st.markdown("#### State transition preview")
    now_frame = rm_mdp_state_frame(initial_state, int(unit_size), "Now")
    next_frame = rm_mdp_state_frame(day_one_next, int(unit_size), "Expected after day 1")
    state_compare = now_frame.merge(next_frame, on="Bucket", how="outer")
    state_compare["Change"] = state_compare["Expected after day 1"] - state_compare["Now"]
    st.dataframe(
        state_compare,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Now": st.column_config.NumberColumn(format="%.0f"),
            "Expected after day 1": st.column_config.NumberColumn(format="%.0f"),
            "Change": st.column_config.NumberColumn(format="%+.0f"),
        },
    )

    rollout = build_rm_mdp_rollout(initial_state, params, policy)
    st.markdown("#### Multi-day rollout")
    st.dataframe(
        rollout,
        use_container_width=True,
        hide_index=True,
        height=300,
    )

    with st.expander("MDP logic used in this pilot", expanded=True):
        st.markdown(
            """
            **State**

            ```text
            S = [Store, Shop, SA, GA, Unknown Transit, Rework/Hold]
            ```

            **Action**

            ```text
            A = [a, b, c, d, e, f]
            ```

            **Transition**

            ```text
            Next State = Current State
            + GRN / recovered transit / recovered rework
            + successful movements
            - dispatched movements
            - demand consumption
            + delayed / retracted / rework exceptions
            ```

            **Objective**

            ```text
            Minimize expected shortage cost
            + handling cost
            + congestion cost
            + unknown-transit / rework risk cost
            ```

            The pilot solves this by finite-horizon dynamic programming. In the
            real version, MB51, Mendix scan logs, GRN, and line-consumption
            history will replace the manually entered probabilities.
            """
        )


def render_rm_material_movement_agent(
    inventory: pd.DataFrame,
    views: dict[str, pd.DataFrame],
    meta: dict[str, object],
    sources: dict[str, pd.DataFrame],
) -> None:
    st.subheader("RM Movement Control Flow")
    st.write(
        "One operational flow for Stores, PPC, and SCM: confirm the day-wise "
        "movement inputs, review escalations, select a part, then execute the "
        "recommended scan movement."
    )
    st.markdown(
        """
        <div class="agent-legend">
            <span class="agent-chip">1. Confirm inputs</span>
            <span class="agent-chip">2. Prioritize queue</span>
            <span class="agent-chip">3. Execute route</span>
            <span class="agent-chip">4. Escalate exceptions</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    today_view = views.get("Today", pd.DataFrame())
    movement_input = build_rm_movement_input(inventory, today_view, meta, sources)
    if movement_input.empty:
        st.info(
            "No movement candidates were found. A part appears here when it has "
            "positive in-transit stock or a same-day RM shortage."
        )
        return

    plan_date = pd.Timestamp(meta.get("plan_date", pd.Timestamp.now())).strftime("%Y-%m-%d")
    st.markdown("#### 1. Confirm movement inputs")
    controls = st.columns([1, 1, 3])
    with controls[0]:
        max_rows = st.selectbox("Rows to plan", [25, 50, 100, 250], index=1)
    with controls[1]:
        st.metric("Plan date", plan_date)
    with controls[2]:
        st.info(
            "Route equation: a Store->GA + b Store->SA + c Store->Shop + "
            "d Shop->SA + e Shop->GA + f SA->GA = Allocated Transit."
        )
        st.caption(
            "Check equation: Allocated Transit + Unallocated Transit = In Transit Qty. "
            "In Transit Qty now uses the higher of stock-difference transit and "
            "VIN-gap backlog unless you enter a manual override."
        )
    with st.expander("VIN-gap backlog logic", expanded=False):
        st.markdown(
            """
            This converts missed output into a part-level WIP/transit signal.

            ```text
            Daily VIN Delta = Planned or possible VINs - Actual VINs
            Cumulative VIN Backlog = max(previous backlog + Daily VIN Delta, 0)
            VIN Gap Transit Qty by part = Cumulative VIN Backlog x BOM qty per FG
            In Transit Qty = max(System-minus-store signal, VIN Gap Transit Qty)
            ```

            So if 10 VINs could have been produced and only 8 were produced,
            the backlog is 2 VINs. If the next day 20 could have been produced
            and only 16 were produced, the backlog becomes 6 VINs. If a later
            day over-produces versus plan, the backlog reduces. The optimizer
            then tries to allocate this suspected WIP/transit so the backlog
            does not keep bottling up.
            """
        )

    editable = movement_input.head(int(max_rows)).copy()
    edited = st.data_editor(
        editable,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        disabled=[
            "System Stock",
            "Store Stock",
            "In Transit Qty",
            "Stock Difference Transit Qty",
            "VIN Gap Transit Qty",
            "Transit Source",
        ],
        column_config={
            "System Stock": st.column_config.NumberColumn(format="%.0f"),
            "Store Stock": st.column_config.NumberColumn(format="%.0f"),
            "In Transit Qty": st.column_config.NumberColumn(format="%.0f"),
            "Stock Difference Transit Qty": st.column_config.NumberColumn(
                format="%.0f",
                help="System Stock minus Store/Physical Stock, floored at zero.",
            ),
            "VIN Gap Transit Qty": st.column_config.NumberColumn(
                format="%.0f",
                help="Cumulative planned/possible VIN gap exploded through BOM.",
            ),
            "In Transit Override": st.column_config.NumberColumn(
                format="%.0f",
                help=(
                    "Optional: override the prepared transit quantity for this "
                    "planning run."
                ),
            ),
            "GA Line Need": st.column_config.NumberColumn(format="%.0f"),
            "SA Line Need": st.column_config.NumberColumn(format="%.0f"),
            "Shop Need": st.column_config.NumberColumn(format="%.0f"),
            "GA Priority": st.column_config.NumberColumn(format="%.1f"),
            "SA Priority": st.column_config.NumberColumn(format="%.1f"),
            "Shop Priority": st.column_config.NumberColumn(format="%.1f"),
        },
        key="rm_movement_editor",
    )
    left, right = st.columns([1, 4])
    with left:
        if st.button("Save movement inputs", type="primary"):
            save_rm_movement_plan(edited)
            st.success("Movement inputs saved.")
            st.rerun()
    with right:
        st.caption(
            "GA has the highest default priority because it is closest to final "
            "vehicle output; SA and shop priorities can be adjusted per part."
        )

    allocations = build_rm_movement_allocations(edited)
    if allocations.empty:
        st.info("Enter line/shop needs to generate movement recommendations.")
        return

    st.markdown("#### 2. Escalation cockpit")
    total_in_transit = numeric(allocations["In Transit Qty"]).sum()
    total_vin_gap_transit = numeric(allocations["VIN Gap Transit Qty"]).sum()
    total_allocated = numeric(allocations["Allocated Transit"]).sum()
    total_uncovered = numeric(allocations["Uncovered Demand"]).sum()
    critical_count = int(allocations["Severity"].eq("Critical").sum())
    high_count = int(allocations["Severity"].eq("High").sum())
    watch_count = int(allocations["Severity"].eq("Watch").sum())
    ready_count = int(allocations["Severity"].eq("OK").sum())
    metrics = st.columns(7)
    with metrics[0]:
        render_metric("Critical line risk", f"{critical_count:,}", "bad" if critical_count else "ok")
    with metrics[1]:
        render_metric("High escalations", f"{high_count:,}", "warn" if high_count else "ok")
    with metrics[2]:
        render_metric("Trace / watch", f"{watch_count:,}", "warn" if watch_count else "ok")
    with metrics[3]:
        render_metric("Visible transit", display_qty(total_in_transit), "neutral")
    with metrics[4]:
        render_metric("VIN-gap transit", display_qty(total_vin_gap_transit), "warn" if total_vin_gap_transit else "ok")
    with metrics[5]:
        render_metric("Transit allocated", display_qty(total_allocated), "ok")
    with metrics[6]:
        render_metric("Uncovered demand", display_qty(total_uncovered), "bad" if total_uncovered else "ok")

    route_columns = [
        "a Store -> GA",
        "b Store -> SA",
        "c Store -> Shop",
        "d Shop -> SA",
        "e Shop -> GA",
        "f SA -> GA",
    ]
    queue_frames = {
        "Critical line risk": allocations[allocations["Severity"].eq("Critical")],
        "High escalation": allocations[allocations["Severity"].eq("High")],
        "Trace / demand input": allocations[allocations["Severity"].eq("Watch")],
        "Ready to execute": allocations[allocations["Severity"].eq("OK")],
        "All recommendations": allocations,
    }
    queue_labels = {
        name: f"{name} ({len(frame):,})"
        for name, frame in queue_frames.items()
    }
    default_queue = "Critical line risk" if critical_count else (
        "High escalation" if high_count else "Trace / demand input" if watch_count else "Ready to execute"
    )
    queue_cols = st.columns([1.2, 1, 1, 0.7])
    with queue_cols[0]:
        queue_name = st.selectbox(
            "Work queue",
            list(queue_frames),
            index=list(queue_frames).index(default_queue),
            format_func=lambda value: queue_labels[value],
            key="rm_movement_queue",
        )
    queue = queue_frames[queue_name].copy()
    with queue_cols[1]:
        buyers = sorted(
            queue.get("Buyer", pd.Series(dtype=str))
            .replace("", pd.NA)
            .dropna()
            .unique()
            .tolist()
        )
        selected_buyer = st.selectbox(
            "Buyer",
            ["All buyers"] + buyers,
            key="rm_movement_buyer",
        )
    supplier_source = queue
    if selected_buyer != "All buyers":
        supplier_source = supplier_source[supplier_source["Buyer"].eq(selected_buyer)]
    with queue_cols[2]:
        suppliers = sorted(
            supplier_source.get("Supplier", pd.Series(dtype=str))
            .replace("", pd.NA)
            .dropna()
            .unique()
            .tolist()
        )
        selected_supplier = st.selectbox(
            "Supplier",
            ["All suppliers"] + suppliers,
            key=f"rm_movement_supplier_{normalize_column_name(selected_buyer)}",
        )
    with queue_cols[3]:
        page_size = st.selectbox(
            "Rows",
            [10, 25, 50],
            index=1,
            key="rm_movement_page_size",
        )

    search = st.text_input(
        "Search movement queue",
        placeholder="part number, part name, supplier, buyer",
        key="rm_movement_search",
    )
    filtered = queue.copy()
    if selected_buyer != "All buyers":
        filtered = filtered[filtered["Buyer"].eq(selected_buyer)]
    if selected_supplier != "All suppliers":
        filtered = filtered[filtered["Supplier"].eq(selected_supplier)]
    if search.strip():
        term = search.strip().lower()
        search_columns = ["Part No.", "Part Name", "Supplier", "Buyer", "Decision"]
        filtered = filtered[
            filtered[search_columns]
            .astype(str)
            .apply(lambda column: column.str.lower().str.contains(term, na=False))
            .any(axis=1)
        ]
    if filtered.empty:
        st.success("No parts match this queue and filter combination.")
        return

    total_pages = max((len(filtered) + page_size - 1) // page_size, 1)
    page_cols = st.columns([1, 4])
    with page_cols[0]:
        page_number = st.number_input(
            "Page",
            min_value=1,
            max_value=total_pages,
            value=1,
            step=1,
            key=f"rm_movement_page_{normalize_column_name(queue_name)}",
        )
    with page_cols[1]:
        st.caption(
            f"{len(filtered):,} movement item(s) · page {page_number} of {total_pages}. "
            "Select a row to open the execution and escalation plan."
        )
    start = (int(page_number) - 1) * page_size
    page_frame = filtered.iloc[start : start + page_size].reset_index(drop=True)
    compact_columns = [
        "Severity",
        "Decision",
        "Part No.",
        "Part Name",
        "Supplier",
        "Buyer",
        "In Transit Qty",
        "VIN Gap Transit Qty",
        "Transit Source",
        "Demand Total",
        "Allocated Transit",
        "Uncovered Demand",
        "Escalation",
    ]
    compact = page_frame[compact_columns].copy()
    compact["Severity"] = compact["Severity"].map(
        {
            "Critical": "Critical",
            "High": "High",
            "Watch": "Watch",
            "OK": "Ready",
        }
    )
    selection = st.dataframe(
        compact,
        use_container_width=True,
        hide_index=True,
        height=min(510, 42 + len(compact) * 38),
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "In Transit Qty": st.column_config.NumberColumn(format="%.0f"),
            "VIN Gap Transit Qty": st.column_config.NumberColumn(format="%.0f"),
            "Demand Total": st.column_config.NumberColumn(format="%.0f"),
            "Allocated Transit": st.column_config.NumberColumn(format="%.0f"),
            "Uncovered Demand": st.column_config.NumberColumn(format="%.0f"),
        },
        key=f"rm_movement_selection_{normalize_column_name(queue_name)}_{page_number}",
    )
    selected_rows = (
        selection.selection.rows
        if hasattr(selection, "selection")
        else selection.get("selection", {}).get("rows", [])
    )
    if not selected_rows:
        route_summary = (
            allocations[route_columns]
            .sum()
            .rename_axis("Movement lane")
            .reset_index(name="Recommended Qty")
        )
        st.markdown("#### Route split summary")
        st.dataframe(
            route_summary,
            use_container_width=True,
            hide_index=True,
            column_config={"Recommended Qty": st.column_config.NumberColumn(format="%.0f")},
        )
        st.info("Select a row above to see the exact execution steps and escalation path.")
        st.download_button(
            "Download movement recommendations CSV",
            allocations.to_csv(index=False),
            file_name="rm_movement_control_flow.csv",
            mime="text/csv",
        )
        return

    selected = page_frame.iloc[selected_rows[0]].copy()
    st.markdown("#### 3. Execution and escalation plan")
    title = clean_text(selected["Part Name"]) or "Part name unavailable"
    st.markdown(
        f"### {escape(clean_text(selected['Part No.']))} · {escape(title)}"
    )
    evidence = st.columns(6)
    with evidence[0]:
        render_metric("System stock", display_qty(selected["System Stock"]), "neutral")
    with evidence[1]:
        render_metric("Store stock", display_qty(selected["Store Stock"]), "neutral")
    with evidence[2]:
        render_metric("In transit", display_qty(selected["In Transit Qty"]), "neutral")
    with evidence[3]:
        render_metric("VIN-gap transit", display_qty(selected["VIN Gap Transit Qty"]), "warn" if scalar_float(selected["VIN Gap Transit Qty"]) else "ok")
    with evidence[4]:
        render_metric("Allocated", display_qty(selected["Allocated Transit"]), "ok")
    with evidence[5]:
        render_metric(
            "Uncovered",
            display_qty(selected["Uncovered Demand"]),
            "bad" if scalar_float(selected["Uncovered Demand"]) else "ok",
        )

    route_rows = []
    for route in rm_mdp_route_specs():
        qty = scalar_float(selected.get(route["lane"], 0))
        if qty <= 0:
            continue
        route_rows.append(
            {
                "Movement lane": route["lane"],
                "From": route["from"],
                "To": route["to"],
                "Qty to move": qty,
                "SAP posting": route["sap"],
                "Scan control": "Scan-out at source, scan-in at destination",
            }
        )
    detail_cols = st.columns([1.25, 1])
    with detail_cols[0]:
        st.markdown("**Recommended route execution**")
        if route_rows:
            st.dataframe(
                pd.DataFrame(route_rows),
                use_container_width=True,
                hide_index=True,
                column_config={"Qty to move": st.column_config.NumberColumn(format="%.0f")},
            )
        else:
            st.warning("No route movement is recommended until demand or usable transit is confirmed.")
        st.markdown("**Demand coverage**")
        coverage = pd.DataFrame(
            [
                ("GA", selected["GA Need"], selected["GA Allocated"], selected["GA Gap"]),
                ("SA", selected["SA Need"], selected["SA Allocated"], selected["SA Gap"]),
                ("Shop", selected["Shop Need"], selected["Shop Allocated"], selected["Shop Gap"]),
            ],
            columns=["Destination", "Need", "Allocated", "Gap"],
        )
        st.dataframe(
            coverage,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Need": st.column_config.NumberColumn(format="%.0f"),
                "Allocated": st.column_config.NumberColumn(format="%.0f"),
                "Gap": st.column_config.NumberColumn(format="%.0f"),
            },
        )
    with detail_cols[1]:
        severity = clean_text(selected["Severity"])
        if severity == "Critical":
            st.error(f"Escalation: {clean_text(selected['Escalation'])}")
        elif severity == "High":
            st.warning(f"Escalation: {clean_text(selected['Escalation'])}")
        elif severity == "Watch":
            st.info(f"Escalation: {clean_text(selected['Escalation'])}")
        else:
            st.success(f"Escalation: {clean_text(selected['Escalation'])}")
        st.markdown(
            f"**Buyer:** {escape(clean_text(selected['Buyer']) or 'Unmapped')}  \n"
            f"**Supplier:** {escape(clean_text(selected['Supplier']) or 'Unmapped')}  \n"
            f"**Transit source:** {escape(clean_text(selected['Transit Source']) or 'Unavailable')}  \n"
            f"**Decision:** {escape(clean_text(selected['Decision']))}  \n"
            f"**Owner action:** {escape(clean_text(selected['Owner Action']))}"
        )
        st.markdown("**Closure rule**")
        st.write(
            "Close only after destination scan-in or after the exception is logged "
            "as retracted, rework/hold, or demand cancelled. Do not close from a manual remark alone."
        )

    with st.expander("4. Escalation ladder and exception handling", expanded=True):
        st.markdown(
            """
            - **Critical:** GA gap exists. PPC lead and Stores lead act immediately; SCM buyer supports supplier or alternate pull.
            - **High:** SA/shop gap exists. Area owner confirms whether downstream demand can still be protected.
            - **Watch:** surplus, unknown transit, or missing demand. Stores SPOC traces the material before release.
            - **Ready:** movement is fully allocated. Execute scan-out and scan-in; close only after receiving location confirms.
            - **Retraction/rework:** remove the quantity from usable transit and put it into an exception bucket until recovered or scrapped.
            """
        )
    st.download_button(
        "Download all movement recommendations CSV",
        allocations.to_csv(index=False),
        file_name="rm_movement_control_flow.csv",
        mime="text/csv",
    )

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

    workspace = st.radio(
        "RM Planning workspace",
        ["Shortage planning", "Movement control flow"],
        horizontal=True,
        key="rm_planning_workspace_v2",
    )

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

    if workspace == "Movement control flow":
        render_rm_material_movement_agent(inventory, views, meta, sources)
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
    source_label = google_sheet_read_method_label()

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
    if source_label == "CSV export link":
        st.info("No Google Sheets authorization is connected yet. Connect OAuth here to read private live sheets.")
        render_google_oauth_controls("live_google_sheet", expanded=True)

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


def render_supplier_owner_agent(parts: pd.DataFrame) -> None:
    st.subheader("Supplier Ownership Agent")
    st.write("Flags supplier-owner pockets where buyer follow-up is needed.")
    alerts = build_supplier_owner_alerts(parts)
    total_groups = len(build_supplier_buyer_summary(parts))
    critical_count = int(alerts["Severity"].eq("Critical").sum()) if not alerts.empty else 0
    watch_count = int(alerts["Severity"].eq("Watch").sum()) if not alerts.empty else 0

    cols = st.columns(4)
    with cols[0]:
        render_metric("Supplier groups", f"{total_groups:,}", "neutral")
    with cols[1]:
        render_metric("Need follow-up", f"{len(alerts):,}", "warn" if not alerts.empty else "ok")
    with cols[2]:
        render_metric("Critical owners", f"{critical_count:,}", "bad" if critical_count else "ok")
    with cols[3]:
        render_metric("Watch items", f"{watch_count:,}", "warn" if watch_count else "ok")

    if alerts.empty:
        st.success("No owner-level supplier follow-up is currently flagged.")
        return

    st.dataframe(
        alerts.head(AGENT_TABLE_LIMIT),
        use_container_width=True,
        hide_index=True,
        height=320,
    )
    st.download_button(
        "Download supplier owner alerts CSV",
        alerts.to_csv(index=False),
        file_name="supplier_owner_alerts.csv",
        mime="text/csv",
    )


def render_supplier_buyer_map() -> None:
    st.header(
        "Supplier Buyer Map",
        help=(
            "Maps each supplier and part to the buyer responsible for follow-up, "
            "using the saved SPOC Summary copy."
        ),
    )
    st.write("Buyer-supplier ownership from the saved SPOC Summary copy.")
    source_label = google_sheet_read_method_label()

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
    if source_label == "CSV export link":
        st.info("No Google Sheets authorization is connected yet. Connect OAuth here to read private live sheets.")
        render_google_oauth_controls("supplier_buyer_map", expanded=True)

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

    render_supplier_owner_agent(parts)
    st.divider()

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


def render_grn_quality_agent(grn_df: pd.DataFrame) -> None:
    st.subheader("GRN Data Quality Agent")
    st.write("Checks whether inwarding rows are usable for stock math before they affect inventory.")
    alerts = build_grn_quality_alerts(grn_df)
    critical_count = int(alerts["Severity"].eq("Critical").sum()) if not alerts.empty else 0
    watch_count = int(alerts["Severity"].eq("Watch").sum()) if not alerts.empty else 0
    issue_types = alerts["Issue"].nunique() if not alerts.empty else 0

    cols = st.columns(4)
    with cols[0]:
        render_metric("Rows checked", f"{len(grn_df):,}", "neutral")
    with cols[1]:
        render_metric("Issues", f"{len(alerts):,}", "warn" if not alerts.empty else "ok")
    with cols[2]:
        render_metric("Critical", f"{critical_count:,}", "bad" if critical_count else "ok")
    with cols[3]:
        render_metric("Issue types", f"{issue_types:,}", "warn" if watch_count else "ok")

    if alerts.empty:
        st.success("No GRN data quality issues found in the current filtered view.")
        return

    st.warning("Review these rows before using this GRN set as stock evidence.")
    st.dataframe(
        alerts.head(AGENT_TABLE_LIMIT),
        use_container_width=True,
        hide_index=True,
        height=340,
    )
    if len(alerts) > AGENT_TABLE_LIMIT:
        st.caption(f"Showing first {AGENT_TABLE_LIMIT:,} alerts out of {len(alerts):,}. Use filters above to narrow the GRN view.")
    st.download_button(
        "Download GRN quality alerts CSV",
        alerts.to_csv(index=False),
        file_name="grn_quality_alerts.csv",
        mime="text/csv",
    )


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

    credentials = load_google_credentials()
    if credentials is None:
        st.info(
            "Connect Google Sheets once here. The token is saved locally in `.streamlit/` "
            "and is not committed to Git."
        )
        credentials = render_google_oauth_controls("inwarding_live", expanded=True)
    else:
        st.success("Google Sheets authorization is connected.")

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

    render_grn_quality_agent(build_grn_display_frame(filtered))
    st.divider()

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


def render_outwarding_flagging_agent(combined: pd.DataFrame) -> None:
    st.subheader("Production Change Flagging Agent")
    st.write(
        "This agent compares the current production/BOM outwarding calculation against a saved baseline, "
        "then flags weekly production drops, extra part demand, and reduced outwarding demand."
    )

    baseline = load_outwarding_baseline()
    controls = st.columns([1.7, 1, 1, 1])
    with controls[0]:
        owners = st.text_input(
            "Alert owners",
            value=OUTWARDING_OWNER_DEFAULT,
            key="outwarding_alert_owners",
        )
    with controls[1]:
        reduction_pct_threshold = st.number_input(
            "Production change %",
            min_value=1.0,
            max_value=100.0,
            value=10.0,
            step=1.0,
            key="outwarding_alert_pct",
            help="Minimum weekly production percentage change before an alert is raised.",
        )
    with controls[2]:
        vehicle_delta_threshold = st.number_input(
            "Vehicle delta",
            min_value=1,
            value=50,
            step=10,
            key="outwarding_alert_vehicle_delta",
            help="Minimum weekly vehicle quantity change before an alert is raised.",
        )
    with controls[3]:
        part_delta_threshold = st.number_input(
            "Part qty delta",
            min_value=1,
            value=1000,
            step=100,
            key="outwarding_alert_part_delta",
            help="Minimum weekly part outwarding quantity change before a part alert is raised.",
        )

    action_cols = st.columns([1.4, 4.6])
    with action_cols[0]:
        if st.button("Save current plan as baseline", type="primary"):
            save_outwarding_baseline(combined)
            st.success("Saved current outwarding plan as the comparison baseline.")
            st.rerun()
    with action_cols[1]:
        if baseline.empty:
            st.caption("No baseline saved yet. Save the current plan once; later refreshes will be compared against it.")
        else:
            st.caption(
                f"Baseline: `{OUTWARDING_BASELINE_PATH.relative_to(APP_DIR)}`. "
                f"Last saved: {snapshot_age_label(OUTWARDING_BASELINE_PATH)}."
            )

    if baseline.empty:
        st.info(
            "The agent needs one baseline before it can flag changes. "
            "Click **Save current plan as baseline** after you trust the current production/BOM calculation."
        )
        return

    alerts = build_outwarding_agent_alerts(
        current_usage=combined,
        baseline_usage=baseline,
        owners=owners,
        reduction_pct_threshold=float(reduction_pct_threshold),
        vehicle_delta_threshold=float(vehicle_delta_threshold),
        part_delta_threshold=float(part_delta_threshold),
    )
    log = load_outwarding_alert_log()
    metric_cols = st.columns(4)
    with metric_cols[0]:
        render_metric("Active alerts", f"{len(alerts):,}", "warn" if not alerts.empty else "ok")
    with metric_cols[1]:
        critical_count = int(alerts["Severity"].eq("Critical").sum()) if not alerts.empty else 0
        render_metric("Critical", f"{critical_count:,}", "bad" if critical_count else "ok")
    with metric_cols[2]:
        production_alerts = int(alerts["Agent"].str.contains("Production", case=False, na=False).sum()) if not alerts.empty else 0
        render_metric("Production flags", f"{production_alerts:,}", "warn" if production_alerts else "ok")
    with metric_cols[3]:
        render_metric("Logged alerts", f"{len(log):,}", "neutral")

    if alerts.empty:
        st.success("No production or part outwarding changes crossed the selected thresholds.")
    else:
        st.warning(
            f"{len(alerts):,} active alert(s) found for {owners}. "
            "Review before releasing supplier calls or line-feed quantities."
        )
        st.dataframe(
            alerts.head(250),
            use_container_width=True,
            hide_index=True,
            height=420,
            column_config={
                "Baseline Qty": st.column_config.NumberColumn(format="%.0f"),
                "Current Qty": st.column_config.NumberColumn(format="%.0f"),
                "Delta Qty": st.column_config.NumberColumn(format="%.0f"),
                "Delta %": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
        log_cols = st.columns([1.3, 4.7])
        with log_cols[0]:
            if st.button("Log current alerts for owners", type="primary"):
                updated_log = append_outwarding_alert_log(alerts)
                st.success(f"Logged {len(alerts):,} alert(s). Alert log now has {len(updated_log):,} unique alert(s).")
                st.rerun()
        with log_cols[1]:
            st.download_button(
                "Download active alerts CSV",
                alerts.to_csv(index=False),
                file_name="outwarding_active_alerts.csv",
                mime="text/csv",
            )

    latest_log = load_outwarding_alert_log()
    if not latest_log.empty:
        with st.expander("Owner alert log"):
            st.dataframe(
                latest_log.sort_values("Logged At", ascending=False).head(200),
                use_container_width=True,
                hide_index=True,
                height=320,
            )
            st.download_button(
                "Download alert log CSV",
                latest_log.to_csv(index=False),
                file_name="outwarding_alert_log.csv",
                mime="text/csv",
            )


def render_inbound_coverage_agent(combined: pd.DataFrame) -> None:
    st.subheader("Inbound Coverage Agent")
    st.write(
        "Compares weekly outwarding from production/BOM against the saved GRN sheet copy. "
        "This is a supply-coverage warning, not a final closing-stock calculation."
    )
    grn_df = load_grn_sheet_display_snapshot()
    if grn_df.empty:
        st.info("No saved GRN copy is available yet. Open Inwarding Parts and press Create / update GRN copy.")
        return

    controls = st.columns([1.2, 4.8])
    with controls[0]:
        minimum_gap_qty = st.number_input(
            "Minimum gap qty",
            min_value=1,
            value=100,
            step=50,
            key="inbound_coverage_min_gap",
            help="Only show part-week rows where outwarding exceeds same-week GRN by at least this quantity, or where no GRN exists.",
        )
    with controls[1]:
        st.caption(
            f"GRN source: `{GRN_SHEET_SNAPSHOT_CSV.relative_to(APP_DIR)}`. "
            f"Last copied: {snapshot_age_label(GRN_SHEET_SNAPSHOT_CSV)}."
        )

    alerts = build_inbound_coverage_alerts(
        current_usage=combined,
        grn_df=grn_df,
        minimum_gap_qty=float(minimum_gap_qty),
    )
    critical_count = int(alerts["Severity"].eq("Critical").sum()) if not alerts.empty else 0
    gap_total = numeric(alerts["Gap Qty"]).clip(lower=0).sum() if not alerts.empty else 0
    parts_count = alerts["Part No."].nunique() if not alerts.empty else 0

    cols = st.columns(4)
    with cols[0]:
        render_metric("Coverage alerts", f"{len(alerts):,}", "warn" if not alerts.empty else "ok")
    with cols[1]:
        render_metric("Critical", f"{critical_count:,}", "bad" if critical_count else "ok")
    with cols[2]:
        render_metric("Parts affected", f"{parts_count:,}", "warn" if parts_count else "ok")
    with cols[3]:
        render_metric("Open gap qty", f"{gap_total:,.0f}", "bad" if gap_total else "ok")

    if alerts.empty:
        st.success("No same-week inwarding coverage gaps crossed the selected threshold.")
        return

    st.dataframe(
        alerts.head(AGENT_TABLE_LIMIT),
        use_container_width=True,
        hide_index=True,
        height=380,
        column_config={
            "Outwarding Qty": st.column_config.NumberColumn(format="%.0f"),
            "GRN Received Qty": st.column_config.NumberColumn(format="%.0f"),
            "Gap Qty": st.column_config.NumberColumn(format="%.0f"),
        },
    )
    if len(alerts) > AGENT_TABLE_LIMIT:
        st.caption(f"Showing first {AGENT_TABLE_LIMIT:,} alerts out of {len(alerts):,}.")
    st.download_button(
        "Download inbound coverage alerts CSV",
        alerts.to_csv(index=False),
        file_name="inbound_coverage_alerts.csv",
        mime="text/csv",
    )


def render_allocation_optimizer_agent(combined: pd.DataFrame) -> None:
    st.subheader("Production vs Servicing Allocation Optimizer")
    st.write(
        "Allocates available part quantity across production and servicing demand. "
        "Available quantity is treated as current stock plus same-week GRN receipts."
    )

    grn_df = load_grn_sheet_display_snapshot()
    if grn_df.empty:
        st.info("No saved GRN copy is available yet. Open Inwarding Parts and refresh the inwarding snapshot.")
        return

    controls = st.columns(4)
    with controls[0]:
        production_guard_pct = st.slider(
            "Production guard %",
            min_value=0,
            max_value=100,
            value=90,
            step=5,
            help="Minimum share of production demand to protect before weighted allocation starts.",
        )
    with controls[1]:
        servicing_guard_pct = st.slider(
            "Servicing guard %",
            min_value=0,
            max_value=100,
            value=20,
            step=5,
            help="Minimum share of servicing demand to protect so servicing is not starved.",
        )
    with controls[2]:
        production_priority_weight = st.number_input(
            "Production weight",
            min_value=0.1,
            value=3.0,
            step=0.5,
            help="Higher weight sends more remaining constrained stock to production.",
        )
    with controls[3]:
        servicing_priority_weight = st.number_input(
            "Servicing weight",
            min_value=0.1,
            value=1.0,
            step=0.5,
            help="Higher weight sends more remaining constrained stock to servicing.",
        )

    allocation = build_allocation_optimizer(
        current_usage=combined,
        grn_df=grn_df,
        production_guard_pct=float(production_guard_pct),
        servicing_guard_pct=float(servicing_guard_pct),
        production_priority_weight=float(production_priority_weight),
        servicing_priority_weight=float(servicing_priority_weight),
    )
    if allocation.empty:
        st.info("No production or servicing demand is available for allocation.")
        return

    critical_count = int(allocation["Severity"].eq("Critical").sum())
    watch_count = int(allocation["Severity"].eq("Watch").sum())
    production_shortfall = numeric(allocation["Production Shortfall"]).sum()
    servicing_shortfall = numeric(allocation["Servicing Shortfall"]).sum()
    cols = st.columns(4)
    with cols[0]:
        render_metric("Critical allocations", f"{critical_count:,}", "bad" if critical_count else "ok")
    with cols[1]:
        render_metric("Watch allocations", f"{watch_count:,}", "warn" if watch_count else "ok")
    with cols[2]:
        render_metric("Production shortfall", f"{production_shortfall:,.0f}", "bad" if production_shortfall else "ok")
    with cols[3]:
        render_metric("Servicing shortfall", f"{servicing_shortfall:,.0f}", "warn" if servicing_shortfall else "ok")

    st.caption(
        "Algorithm: starting stock + same-week GRN is allocated to production and servicing; "
        "projected closing stock carries forward as the next week's starting stock for that part."
    )
    st.dataframe(
        allocation.head(AGENT_TABLE_LIMIT),
        use_container_width=True,
        hide_index=True,
        height=420,
        column_config={
            "Starting Stock Qty": st.column_config.NumberColumn(format="%.0f"),
            "GRN Received Qty": st.column_config.NumberColumn(format="%.0f"),
            "Available Qty": st.column_config.NumberColumn(format="%.0f"),
            "Production Demand": st.column_config.NumberColumn(format="%.0f"),
            "Servicing Demand": st.column_config.NumberColumn(format="%.0f"),
            "Production Allocation": st.column_config.NumberColumn(format="%.0f"),
            "Servicing Allocation": st.column_config.NumberColumn(format="%.0f"),
            "Production Shortfall": st.column_config.NumberColumn(format="%.0f"),
            "Servicing Shortfall": st.column_config.NumberColumn(format="%.0f"),
            "Projected Closing Stock": st.column_config.NumberColumn(format="%.0f"),
        },
    )
    if len(allocation) > AGENT_TABLE_LIMIT:
        st.caption(f"Showing first {AGENT_TABLE_LIMIT:,} allocations out of {len(allocation):,}.")
    st.download_button(
        "Download allocation recommendations CSV",
        allocation.to_csv(index=False),
        file_name="production_servicing_allocation.csv",
        mime="text/csv",
    )


def render_outwarding_data_timeline(
    production: pd.DataFrame,
    manual_outwarding: pd.DataFrame,
    combined: pd.DataFrame,
) -> None:
    source_rows = [
        data_file_health_row(
            "Production planning weekly report",
            SOURCE_SHEETS["vin_details"]["cache"],
            "finished-goods output by day/shift",
        ),
        data_file_health_row(
            "FG / SKU mapping",
            SOURCE_SHEETS["sku_map"]["cache"],
            "maps produced variants to FG codes",
        ),
        data_file_health_row(
            "Exploded BOM",
            SOURCE_SHEETS["exploded_bom"]["cache"],
            "converts FG production into part demand",
        ),
        data_file_health_row(
            "Raw BOM",
            SOURCE_SHEETS["raw_bom"]["cache"],
            "fallback component attributes",
        ),
        data_file_health_row(
            "Part supplier mapping",
            SOURCE_SHEETS["suppliers"]["cache"],
            "supplier names for consumed parts",
        ),
        data_file_health_row(
            "Current buyer mapping",
            BUYER_MAPPING_CACHE_PATH,
            "buyer/supplier ownership",
        ),
        data_file_health_row(
            "GRN / gate entry snapshot",
            INWARDING_SNAPSHOT_PATH,
            "same-week incoming quantity",
        ),
        data_file_health_row(
            "SPOC onsite opening stock",
            SPOC_SUMMARY_SNAPSHOT_CSV,
            "opening stock for allocation",
        ),
        data_file_health_row(
            "CPD/PNA servicing tracker",
            SERVICING_SNAPSHOT_PATH,
            "part-wise servicing requirement, movement, and balance",
        ),
        data_file_health_row(
            "311 SR posting tracker",
            SR_POSTING_SNAPSHOT_PATH,
            "confirmed and pending internal Stock Request postings",
        ),
        data_file_health_row(
            "Manual servicing fallback",
            TABLES["outwarding_parts"]["file"],
            "used only when live servicing snapshot is unavailable",
        ),
        data_file_health_row(
            "Computed outwarding cache",
            COMPUTED_USAGE_CACHE_PATH,
            "last calculated production + servicing demand",
        ),
    ]

    production_demand = numeric(
        combined.get("Production Used Qty", pd.Series(index=combined.index))
    ).sum()
    production_split = pd.Series(dtype=float)
    if not production.empty and {"Production Source", "Produced Qty"}.issubset(production.columns):
        production_split = (
            production.assign(
                _bucket=production["Production Source"].map(production_bucket)
            )
            .groupby("_bucket")["Produced Qty"]
            .sum()
        )
    servicing_demand = numeric(
        combined.get("Servicing Demand Qty", pd.Series(index=combined.index))
    ).sum()
    servicing_used = numeric(
        combined.get("Servicing Used Qty", pd.Series(index=combined.index))
    ).sum()
    total_demand = numeric(
        combined.get("Total Demand Qty", pd.Series(index=combined.index))
    ).sum()
    total_outwarding = numeric(
        combined.get("Total Outwarding Qty", pd.Series(index=combined.index))
    ).sum()
    movement_311 = load_source_cache(SR_POSTING_SNAPSHOT_PATH)
    confirmed_311 = numeric(
        movement_311.get("Confirmed 311 Qty", pd.Series(index=movement_311.index))
    ).sum() if not movement_311.empty else 0
    pending_311 = numeric(
        movement_311.get("Pending 311 Qty", pd.Series(index=movement_311.index))
    ).sum() if not movement_311.empty else 0
    valid_servicing_rows = pd.DataFrame()
    if {"Part No.", "Servicing Used Qty"}.issubset(manual_outwarding.columns):
        valid_servicing_rows = manual_outwarding[
            manual_outwarding["Part No."].astype(str).str.strip().ne("")
            & (
                numeric(manual_outwarding["Servicing Used Qty"]).gt(0)
                | numeric(manual_outwarding.get("Servicing Demand Qty", pd.Series(index=manual_outwarding.index))).gt(0)
            )
        ]
    elif {"Part No.", "Used Qty"}.issubset(manual_outwarding.columns):
        valid_servicing_rows = manual_outwarding[
            manual_outwarding["Part No."].astype(str).str.strip().ne("")
            & numeric(manual_outwarding["Used Qty"]).gt(0)
        ]

    stock_source = build_part_available_stock()
    spoc_stock_rows = 0
    if not stock_source.empty and "Stock Basis" in stock_source.columns:
        spoc_stock_rows = int(
            stock_source["Stock Basis"]
            .astype(str)
            .str.contains("SPOC", case=False, na=False)
            .sum()
        )

    with st.expander("Data timeline and source health", expanded=True):
        st.caption(
            "Use this before trusting the agent output. If a source was changed in "
            "Google Sheets, the app will not use it until that source is refreshed "
            "or the servicing table is saved."
        )
        st.dataframe(
            pd.DataFrame(source_rows),
            use_container_width=True,
            hide_index=True,
        )

        metric_columns = st.columns(8)
        with metric_columns[0]:
            render_metric(
                "Production rows",
                f"{len(production):,}",
                "ok" if len(production) else "bad",
            )
        with metric_columns[1]:
            render_metric(
                "Production demand",
                f"{production_demand:,.0f}",
                "ok" if production_demand else "bad",
            )
        with metric_columns[2]:
            render_metric(
                "Servicing rows",
                f"{len(valid_servicing_rows):,}",
                "ok" if len(valid_servicing_rows) else "warn",
            )
        with metric_columns[3]:
            render_metric(
                "Servicing moved",
                f"{servicing_used:,.0f}",
                "ok" if servicing_used else "warn",
            )
        with metric_columns[4]:
            render_metric(
                "Servicing open",
                f"{servicing_demand:,.0f}",
                "ok" if servicing_demand else "warn",
            )
        with metric_columns[5]:
            render_metric(
                "311 posted",
                f"{confirmed_311:,.0f}",
                "ok" if confirmed_311 else "warn",
            )
        with metric_columns[6]:
            render_metric(
                "311 pending",
                f"{pending_311:,.0f}",
                "warn" if pending_311 else "ok",
            )
        with metric_columns[7]:
            render_metric(
                "Stock sources",
                f"{len(stock_source):,}",
                "ok" if len(stock_source) else "bad",
            )

        st.caption(
            f"Actual outwarding moved so far: {total_outwarding:,.0f}. "
            f"Open demand to cover: {total_demand:,.0f}. "
            f"SPOC opening-stock rows feeding allocation: {spoc_stock_rows:,}."
        )
        st.caption(
            "Production split feeding BOM: "
            f"P-VIN {production_split.get('P-VIN', 0):,.0f}, "
            f"VNA {production_split.get('VNA', 0):,.0f}, "
            f"Free VIN {production_split.get('Free VIN', 0):,.0f}."
        )
        if servicing_demand <= 0:
            st.warning(
                "Servicing open demand is currently zero. Refresh the CPD/PNA "
                "servicing tracker, or add fallback part-level servicing rows with "
                "Part No., Used Qty, and Usage Date, then press Save changes."
            )
        if not SERVICING_SNAPSHOT_PATH.exists() and not TABLES["outwarding_parts"]["file"].exists():
            st.info(
                "No live servicing snapshot or saved fallback input exists yet. "
                "Unsaved table edits are not treated as a stable data pipeline input."
            )
        if stock_source.empty:
            st.warning(
                "No opening-stock source is available, so allocation will behave "
                "like all parts start from zero stock plus GRN."
            )


def render_partwise_production_demand(combined: pd.DataFrame) -> None:
    columns = [
        "Part No.",
        "Part Name",
        "Buyer",
        "Supplier",
        "Material Type",
        "Production Demand Qty",
        "Demand Share %",
        "P-VIN Qty",
        "VNA Qty",
        "Free VIN Qty",
        "Servicing Open Qty",
        "Total Demand Qty",
    ]
    if combined.empty or "Production Used Qty" not in combined.columns:
        st.info("Part-wise production demand is not available yet.")
        return

    prepared = combined.copy()
    prepared["Part No."] = prepared["Part No."].apply(stock_part_key)
    prepared = prepared[prepared["Part No."].ne("")].copy()
    if prepared.empty:
        st.info("No valid part numbers were found for the part-wise demand view.")
        return

    for column in [
        "Production Used Qty",
        "P-VIN Production Used Qty",
        "VNA Production Used Qty",
        "Free VIN Production Used Qty",
        "Servicing Demand Qty",
        "Total Demand Qty",
    ]:
        if column not in prepared.columns:
            prepared[column] = 0
        prepared[column] = numeric(prepared[column])

    summary = (
        prepared.groupby("Part No.", as_index=False)
        .agg(
            **{
                "Part Name": ("Part Name", joined_text),
                "Buyer": ("Buyer", joined_text),
                "Supplier": ("Supplier", joined_text),
                "Material Type": ("Material Type", joined_text),
                "Production Demand Qty": ("Production Used Qty", "sum"),
                "P-VIN Qty": ("P-VIN Production Used Qty", "sum"),
                "VNA Qty": ("VNA Production Used Qty", "sum"),
                "Free VIN Qty": ("Free VIN Production Used Qty", "sum"),
                "Servicing Open Qty": ("Servicing Demand Qty", "sum"),
                "Total Demand Qty": ("Total Demand Qty", "sum"),
            }
        )
    )
    summary = summary[numeric(summary["Production Demand Qty"]).gt(0)].copy()
    if summary.empty:
        st.info("No part has production demand in the current computed outwarding data.")
        return

    total_production_demand = numeric(summary["Production Demand Qty"]).sum()
    summary["Demand Share %"] = (
        numeric(summary["Production Demand Qty"]) / max(total_production_demand, 1) * 100
    )
    summary = summary.sort_values(
        "Production Demand Qty",
        ascending=False,
    )[columns].reset_index(drop=True)

    with st.expander("Part-wise production demand", expanded=True):
        st.caption(
            "This breaks the total production demand into individual part numbers. "
            "It is calculated only from production actuals multiplied by BOM; "
            "servicing open demand is shown separately for context."
        )
        controls = st.columns([1, 1, 2])
        with controls[0]:
            top_n = st.number_input(
                "Rows to show",
                min_value=10,
                max_value=500,
                value=50,
                step=10,
                key="partwise_production_demand_top_n",
            )
        with controls[1]:
            render_metric("Parts with production demand", f"{len(summary):,}", "neutral")
        with controls[2]:
            st.caption(
                f"Total production demand covered by this table: "
                f"{total_production_demand:,.0f} part units."
            )

        st.dataframe(
            summary.head(int(top_n)),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Production Demand Qty": st.column_config.NumberColumn(format="%.0f"),
                "Demand Share %": st.column_config.NumberColumn(format="%.2f%%"),
                "P-VIN Qty": st.column_config.NumberColumn(format="%.0f"),
                "VNA Qty": st.column_config.NumberColumn(format="%.0f"),
                "Free VIN Qty": st.column_config.NumberColumn(format="%.0f"),
                "Servicing Open Qty": st.column_config.NumberColumn(format="%.0f"),
                "Total Demand Qty": st.column_config.NumberColumn(format="%.0f"),
            },
        )
        st.download_button(
            "Download part-wise production demand CSV",
            data=summary.to_csv(index=False).encode("utf-8"),
            file_name="partwise_production_demand.csv",
            mime="text/csv",
            key="partwise_production_demand_download",
        )


def render_sr_311_movement_evidence() -> None:
    credentials = load_google_credentials()
    refresh_cols = st.columns([1.2, 4])
    with refresh_cols[0]:
        refresh_clicked = st.button(
            "Refresh 311 SR postings",
            type="primary",
            disabled=credentials is None,
            key="refresh_311_sr_postings",
        )
    with refresh_cols[1]:
        st.caption(
            "Pulls the live SR Posting Google Sheet and rebuilds confirmed/pending "
            "SAP 311 movement evidence."
        )
        if credentials is None:
            st.caption("Connect Google in Setup first to enable this refresh.")

    if refresh_clicked and credentials is not None:
        try:
            with st.spinner("Refreshing 311 SR postings from Google Sheets..."):
                movement_df, movement_meta = refresh_sr_311_posting_google_sheet(credentials)
            st.success(
                f"311 SR postings refreshed: {len(movement_df):,} row(s) from "
                f"{clean_text(movement_meta.get('sheet_tab', 'SR Posting'))}."
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Could not refresh 311 SR postings: {exc}")

    movement = load_source_cache(SR_POSTING_SNAPSHOT_PATH)
    if movement.empty:
        st.info(
            "No 311 SR posting snapshot is available yet. Refresh from Google Sheets "
            "to load the SR Posting tab."
        )
        return

    movement = movement.copy()
    for column in ["Requested Qty", "Confirmed 311 Qty", "Pending 311 Qty"]:
        movement[column] = numeric(movement.get(column, pd.Series(index=movement.index)))
    movement["Movement Date Parsed"] = pd.to_datetime(movement.get("Movement Date", ""), errors="coerce")
    movement = movement[movement["Part No."].astype(str).str.strip().ne("")].copy()
    if movement.empty:
        st.info("The 311 SR posting snapshot has no usable part movement rows.")
        return

    summary = (
        movement.groupby(["Part No.", "Part Name", "Plant", "Route"], as_index=False)
        .agg(
            **{
                "Requested Qty": ("Requested Qty", "sum"),
                "Confirmed 311 Qty": ("Confirmed 311 Qty", "sum"),
                "Pending 311 Qty": ("Pending 311 Qty", "sum"),
                "Open SR Count": ("Pending 311 Qty", lambda values: numeric(values).gt(0).sum()),
                "Last Movement Date": ("Movement Date Parsed", "max"),
                "Destination Lines": ("Destination Line", joined_text),
                "Shops": ("Shop", joined_text),
            }
        )
    )
    summary["Last Movement Date"] = summary["Last Movement Date"].dt.strftime("%Y-%m-%d")
    summary = summary.sort_values(
        ["Pending 311 Qty", "Confirmed 311 Qty"],
        ascending=[False, False],
    )

    with st.expander("311 SR posting evidence", expanded=False):
        st.caption(
            "SR means Stock Request / Store Requisition. In this app, the SR Posting "
            "sheet is used as movement evidence for SAP 311 internal stock transfers."
        )
        cols = st.columns(4)
        with cols[0]:
            render_metric("SR rows", f"{len(movement):,}", "neutral")
        with cols[1]:
            render_metric("Confirmed 311", f"{numeric(movement['Confirmed 311 Qty']).sum():,.0f}", "ok")
        with cols[2]:
            render_metric(
                "Pending 311",
                f"{numeric(movement['Pending 311 Qty']).sum():,.0f}",
                "warn" if numeric(movement["Pending 311 Qty"]).sum() else "ok",
            )
        with cols[3]:
            render_metric(
                "Open SRs",
                f"{numeric(movement['Pending 311 Qty']).gt(0).sum():,}",
                "warn" if numeric(movement["Pending 311 Qty"]).gt(0).sum() else "ok",
            )

        st.dataframe(
            summary.head(150),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Requested Qty": st.column_config.NumberColumn(format="%.0f"),
                "Confirmed 311 Qty": st.column_config.NumberColumn(format="%.0f"),
                "Pending 311 Qty": st.column_config.NumberColumn(format="%.0f"),
                "Open SR Count": st.column_config.NumberColumn(format="%.0f"),
            },
        )
        st.download_button(
            "Download normalized 311 SR movement CSV",
            data=movement.drop(columns=["Movement Date Parsed"], errors="ignore").to_csv(index=False),
            file_name="sr_311_posting_movements.csv",
            mime="text/csv",
            key="sr_311_movement_download",
        )


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

    credentials = load_google_credentials()
    if credentials is None:
        st.info("Connect Google Sheets OAuth here to refresh private production and BOM sheets.")
        credentials = render_google_oauth_controls("outwarding", expanded=True)
    else:
        st.success("Google connected with read-only Sheets access.")

    refresh_clicked = st.button(
        "Refresh calculation from Google Sheets",
        type="primary",
        disabled=credentials is None,
    )
    if refresh_clicked:
        try:
            with st.spinner("Reading production, FG mapping, exploded BOM, servicing tracker, and 311 SR postings..."):
                for source in SOURCE_SHEETS.values():
                    source_df, _ = load_google_sheet_oauth(
                        source["url"],
                        credentials,
                    )
                    save_source_cache(source["cache"], source_df)
                servicing_df, servicing_meta = refresh_servicing_google_sheet(credentials)
                sr_df, sr_meta = refresh_sr_311_posting_google_sheet(credentials)
            st.success(
                "Latest source data loaded and the part-usage calculation was refreshed. "
                f"Servicing rows: {len(servicing_df):,}; latest tab: "
                f"{clean_text(servicing_meta.get('latest_tab', '')) or 'not found'}. "
                f"311 SR movement rows: {len(sr_df):,}; source tab: "
                f"{clean_text(sr_meta.get('sheet_tab', '')) or 'not found'}."
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
    servicing_snapshot = load_source_cache(SERVICING_SNAPSHOT_PATH)
    servicing_input = servicing_snapshot if not servicing_snapshot.empty else manual_outwarding
    combined = combine_manual_outwarding(production_usage, servicing_input)
    combined = enrich_outwarding_buyer_supplier(combined)
    if combined.empty:
        st.warning("No computable production or servicing outwarding rows were found.")
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

    if servicing_snapshot.empty:
        st.warning(
            "The live CPD/PNA servicing snapshot is not available, so this run is "
            "using the manual servicing fallback table."
        )
    else:
        servicing_meta = load_snapshot_meta(SERVICING_SNAPSHOT_META_PATH)
        tabs = servicing_meta.get("tabs", [])
        if isinstance(tabs, list) and tabs:
            st.caption(
                "Servicing source: CPD/PNA tracker tabs "
                + ", ".join(str(tab) for tab in tabs[-5:])
                + f"; refreshed {snapshot_age_label(SERVICING_SNAPSHOT_PATH)}."
            )

    render_outwarding_data_timeline(production, servicing_input, combined)
    render_sr_311_movement_evidence()
    render_partwise_production_demand(combined)

    render_outwarding_control_flow(combined, production, servicing_input)
    st.divider()

    filtered = combined.copy()
    min_date = filtered["Usage Date"].min().date()
    max_date = filtered["Usage Date"].max().date()
    filter_columns = st.columns([1.5, 1.8, 1.8, 1.8, 1.2])
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
        buyer_options = sorted(
            value
            for value in filtered["Buyer"].astype(str).unique()
            if value
        )
        selected_buyers = st.multiselect(
            "Buyer",
            buyer_options,
            placeholder="All buyers",
            key="computed_usage_buyers",
        )
    with filter_columns[3]:
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
    with filter_columns[4]:
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
    if selected_buyers:
        filtered = filtered[filtered["Buyer"].isin(selected_buyers)]
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
            "P-VIN Produced Qty": st.column_config.NumberColumn(format="%.0f"),
            "VNA Produced Qty": st.column_config.NumberColumn(format="%.0f"),
            "Free VIN Produced Qty": st.column_config.NumberColumn(format="%.0f"),
            "P-VIN Production Used Qty": st.column_config.NumberColumn(format="%.3f"),
            "VNA Production Used Qty": st.column_config.NumberColumn(format="%.3f"),
            "Free VIN Production Used Qty": st.column_config.NumberColumn(format="%.3f"),
            "Production Used Qty": st.column_config.NumberColumn(format="%.3f"),
            "Servicing Required Qty": st.column_config.NumberColumn(format="%.3f"),
            "Servicing Used Qty": st.column_config.NumberColumn(format="%.3f"),
            "Servicing Demand Qty": st.column_config.NumberColumn(format="%.3f"),
            "Servicing GRN Pending Qty": st.column_config.NumberColumn(format="%.3f"),
            "Servicing Allocation Qty": st.column_config.NumberColumn(format="%.3f"),
            "Total Outwarding Qty": st.column_config.NumberColumn(format="%.3f"),
            "Total Demand Qty": st.column_config.NumberColumn(format="%.3f"),
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
    st.write(
        "Production consumption is calculated from daily production × BOM. "
        "Servicing is read from the CPD/PNA part-wise tracker when refreshed, "
        "with the local table kept as a fallback."
    )
    with st.expander("Servicing outwarding input", expanded=False):
        st.caption(
            "Fallback only. Live CPD/PNA rows are preferred. If you use this table, "
            "`Used Qty` is treated as both servicing moved and open servicing demand."
        )
        manual_outwarding = render_editable_table("outwarding_parts")
    render_outwarding_sources(manual_outwarding)


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
        - Use Supplier Buyer Map to create a saved SPOC Summary copy and build buyer-supplier ownership cards.
        - Inwarding Parts keeps showing its previous Direct Gate Entry snapshot until you press Refresh.
        - For private Google Sheets, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`, paste the service-account JSON values, and share the sheet with that service-account email.
        - Configure `[google_oauth]` for the private inwarding, production, and BOM sheets.
        """
    )


def render_rm_material_movement_map_docs() -> None:
    st.subheader(
        "RM material movement map",
        help=(
            "Shows where HS01 and HS02 sit in the raw-material movement flow, "
            "and which movements feed the optimizer."
        ),
    )
    st.graphviz_chart(
        """
        digraph RM_Movement {
            graph [rankdir=LR, bgcolor="transparent", pad="0.25", nodesep="0.55", ranksep="0.75"];
            node [shape=box, style="rounded,filled", color="#CBD5E1", fillcolor="#F8FAFC", fontname="Arial", fontsize=12];
            edge [color="#334155", fontname="Arial", fontsize=10, arrowsize=0.8];

            HS02 [label="HS02\\nServicing / CPD stock", fillcolor="#EFF6FF", color="#93C5FD"];
            HS02Demand [label="CPD servicing demand\\npart-wise PNA / issue need", fillcolor="#F5F3FF", color="#C4B5FD"];

            subgraph cluster_hs01 {
                label="HS01 - Production plant";
                color="#BAE6FD";
                penwidth=1.5;
                style="rounded,dashed";
                fontname="Arial";
                fontsize=13;

                Store [label="HS01 Store\\nphysical production stock"];
                Shop [label="HS01 Shop\\nweld / battery / paint"];
                SA [label="HS01 SA line\\nsub-assembly"];
                GA [label="HS01 GA line\\nfinal assembly"];
                Vehicle [label="Production order / vehicle\\nactual consumption", fillcolor="#ECFDF5", color="#86EFAC"];
                Exception [label="HS01 exception bucket\\nretracted / rework / hold", fillcolor="#FEF2F2", color="#FCA5A5"];
            }

            HS02Demand -> HS02 [label="servicing pull\\nopen demand", color="#7C3AED"];
            HS02 -> Store [label="HS02 to HS01 transfer\\nplant/location movement", color="#2563EB", penwidth=1.4];

            Store -> GA [label="a: Store to GA\\n311"];
            Store -> SA [label="b: Store to SA\\n311"];
            Store -> Shop [label="c: Store to Shop\\n311"];
            Shop -> SA [label="d: Shop to SA\\n311"];
            Shop -> GA [label="e: Shop to GA\\n311"];
            SA -> GA [label="f: SA to GA\\n311"];

            GA -> Vehicle [label="consume part\\n261"];
            Vehicle -> GA [label="reverse issue\\n262", style=dashed, color="#64748B"];
            Store -> Exception [label="retract / hold\\n312 or reversal", style=dashed, color="#DC2626"];
            Shop -> Exception [label="rework / hold", style=dashed, color="#DC2626"];
            SA -> Exception [label="rework / hold", style=dashed, color="#DC2626"];
            Exception -> Store [label="recovered usable qty\\nRework to HS01", style=dashed, color="#16A34A"];
        }
        """,
        use_container_width=True,
    )
    st.caption(
        "HS01 is the production plant containing Store, Shop, SA, GA, production "
        "consumption, and rework/hold. HS02 is the servicing/CPD stock pool that "
        "can transfer material into HS01 Store. The six solid HS01 arrows remain "
        "the RM optimizer lanes and all use SAP movement type 311; dashed arrows "
        "are exception/recovery events."
    )
    st.dataframe(
        pd.DataFrame(
            [
                (
                    "HS02 transfer",
                    "HS02 CPD / servicing stock",
                    "HS01 Store",
                    "311 / plant-location transfer",
                    "Confirmed by posting number or closed SR status.",
                ),
                (
                    "a",
                    "HS01 Store",
                    "HS01 GA line",
                    "311",
                    "One-step internal transfer.",
                ),
                (
                    "b",
                    "HS01 Store",
                    "HS01 SA line",
                    "311",
                    "One-step internal transfer.",
                ),
                (
                    "c",
                    "HS01 Store",
                    "HS01 Shop",
                    "311",
                    "One-step internal transfer.",
                ),
                (
                    "d",
                    "HS01 Shop",
                    "HS01 SA line",
                    "311",
                    "One-step internal transfer.",
                ),
                (
                    "e",
                    "HS01 Shop",
                    "HS01 GA line",
                    "311",
                    "One-step internal transfer.",
                ),
                (
                    "f",
                    "HS01 SA line",
                    "HS01 GA line",
                    "311",
                    "One-step internal transfer.",
                ),
                (
                    "Consumption",
                    "HS01 line",
                    "Production order",
                    "261",
                    "Final consumption against vehicle or production order.",
                ),
                (
                    "Retraction",
                    "HS01 destination/source",
                    "HS01 exception bucket",
                    "312 or reversal",
                    "Material is held until recovered, reversed, or closed.",
                ),
                (
                    "Rework recovery",
                    "HS01 rework / hold",
                    "HS01 Store",
                    "Rework to HS01 movement",
                    "Recovered usable quantity becomes production stock again.",
                ),
                (
                    "Production reversal",
                    "Production order",
                    "HS01 line/storage",
                    "262",
                    "Use only when 261 consumption was reversed.",
                ),
            ],
            columns=[
                "Lane / event",
                "From",
                "To",
                "Likely SAP movement type",
                "Calculation use / evidence",
            ],
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.info(
        "Important: all six internal movement lanes use 311, so the movement "
        "type confirms an internal transfer but does not identify the lane by "
        "itself. The Store/Shop/SA/GA route must come from source-destination "
        "locations or from SR/remarks mapping when the live posting sheet does "
        "not carry explicit locations."
    )
    st.markdown(
        """
        **VIN-delta bottleneck rule**

        This is the RM Planning Agent's WIP/transit signal until scan data is
        complete. It converts missed VIN output into part-level suspected
        material holding.

        ```text
        Daily VIN Delta = Planned or possible VINs - Actual VINs
        Cumulative VIN Backlog = max(previous backlog + Daily VIN Delta, 0)
        VIN Gap Transit Qty by part = Cumulative VIN Backlog x BOM qty per FG
        Effective In Transit Qty = max(System-minus-store signal, VIN Gap Transit Qty)
        ```

        If 10 VINs could be made and only 8 are made, the backlog is 2 VINs.
        If the next day 20 could be made and only 16 are made, the backlog
        becomes 6 VINs. If a later day produces more than the possible/planned
        quantity, the backlog reduces. The optimizer should therefore choose
        movements that reduce this backlog instead of letting material remain
        bottled up in transit, WIP, rework, or line-side holding.
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
        {
            "Purpose": "Part-wise servicing requirement and movement",
            "Sheet / tab": "Daily PNA CPW Requirement Parts",
            "Link": SERVICING_SOURCE_SHEET_URL,
        },
        {
            "Purpose": "311 internal movement evidence",
            "Sheet / tab": "OLA - IBL Master Daily SR Posting · SR Posting",
            "Link": SR_POSTING_SOURCE_SHEET_URL,
        },
    ]
    st.dataframe(
        pd.DataFrame(source_rows),
        use_container_width=True,
        hide_index=True,
        column_config={"Link": st.column_config.LinkColumn("Source link")},
    )

    st.subheader("4. Outwarding Parts calculation")
    st.markdown(
        """
        The **Outwarding Parts** page estimates part-level material moving out of
        stores into production and servicing. Production demand is calculated
        from actual finished-good output and the exploded BOM. Servicing is
        calculated from the CPD/PNA daily part tracker when that sheet has been
        refreshed; the local table is only a fallback.

        **Production bucket math**

        For every production date, FG, and BOM component:

        1. **P-VIN Production Used Qty** = sum of `(P-VIN actual vehicles × BOM quantity per FG)`.
        2. **VNA Production Used Qty** = sum of `(VNA actual vehicles × BOM quantity per FG)`.
        3. **Free VIN Production Used Qty** = sum of `(Free VIN actual vehicles × BOM quantity per FG)`.
        4. **Production Used Qty** = `P-VIN Production Used Qty + VNA Production Used Qty + Free VIN Production Used Qty`.
        5. **Daily Total Production** = `P-VIN actuals + VNA actuals + Free VIN actuals`.

        The split is retained because P-VIN timing can explain part of the
        difference between system stock and physical stock.

        **Servicing and total outwarding math**

        Servicing rows are valid only when they have Usage Date and Part No.
        They are grouped by Usage Date + Part No.

        ```text
        Servicing Required Qty = CPD/PNA requirement from the daily tab
        Servicing Used Qty = Total moved so far, or A + B + C shift quantities
        Servicing Demand Qty = Balance, or max(Required - Used, 0)
        Total Outwarding Qty = Production Used Qty + Servicing Used Qty
        Total Demand Qty = Production Used Qty + Servicing Demand Qty
        ```

        `Total Outwarding Qty` answers what has already moved. `Total Demand Qty`
        answers what still needs stock coverage in the control queue.

        **311 SR posting math**

        SR means **Stock Request** or **Store Requisition**. The live SR Posting
        tab is treated as SAP 311 internal movement evidence.

        ```text
        Confirmed 311 Qty =
          Posted Qty, when Posted Qty is filled
          otherwise QTY, when Posting Status is Closed or POSTING NO exists

        Pending 311 Qty =
          Pending Qty, when Pending Qty is filled
          otherwise max(QTY - Confirmed 311 Qty, 0)

        Movement Coverage % =
          Confirmed 311 Qty / (Production Demand + Servicing Demand)
        ```

        The 311 sheet does not replace BOM demand. It proves whether the material
        movement request was posted. Since movement type 311 only says "internal
        stock transfer", the exact route is inferred from `Shop`, `STORAGE`,
        `PLANT`, and `LINE` until explicit source-destination storage locations
        are available.
        """
    )

    outwarding_math = pd.DataFrame(
        [
            ("P-VIN Production Used Qty", "P-VIN actual vehicles multiplied by BOM component quantity."),
            ("VNA Production Used Qty", "VNA actual vehicles multiplied by BOM component quantity."),
            ("Free VIN Production Used Qty", "Free VIN actual vehicles multiplied by BOM component quantity."),
            ("Production Used Qty", "Sum of the three production-bucket part quantities."),
            ("Servicing Required Qty", "CPD/PNA requirement from the servicing daily tab."),
            ("Servicing Used Qty", "Actual servicing movement till now: Total, or A + B + C shift quantities."),
            ("Servicing Demand Qty", "Remaining servicing balance to be covered."),
            ("Total Outwarding Qty", "Production Used Qty plus Servicing Used Qty."),
            ("Total Demand Qty", "Production Used Qty plus Servicing Demand Qty."),
            ("Confirmed 311 Qty", "SAP 311 movement confirmed by Posted Qty, Closed status, or posting number."),
            ("Pending 311 Qty", "Open Stock Request quantity that has not yet become confirmed 311 evidence."),
            ("Movement Coverage %", "Confirmed 311 Qty divided by production plus servicing demand."),
        ],
        columns=["Output", "How it is calculated"],
    )
    st.dataframe(outwarding_math, use_container_width=True, hide_index=True)

    st.markdown(
        """
        **Outwarding Control Flow**

        The Outwarding page now runs as one queue instead of separate mini-agents:

        1. **Demand:** production actuals and servicing rows are converted into
           weekly part demand.
        2. **Coverage:** demand is compared with opening stock and same-week GRN.
        3. **Allocation:** constrained stock is split between production and servicing.
        4. **Escalation:** only exceptions are shown as Critical, High, or Watch.
        5. **Closure:** an action is closed only with scan, MB51, GRN, stock-count,
           or plan-correction evidence.

        **Plan-change signal**

        Weekly vehicle change uses:

        ```text
        Current Vehicles - Baseline Vehicles
        ```

        Part-level change uses:

        ```text
        Current Total Demand Qty - Baseline Total Demand Qty
        ```

        Delta percentage uses:

        ```text
        ((Current Qty - Baseline Qty) / Baseline Qty) x 100
        ```

        If baseline is zero and current is positive, Delta % is treated as 100%.

        **Inbound coverage signal**

        ```text
        Gap Qty = Outwarding Qty - GRN Received Qty
        ```

        Here, Outwarding Qty uses `Total Demand Qty`, so servicing balance is
        included in the coverage check. A row becomes Critical when there is no
        same-week GRN, or when GRN covers less than half of demand. It becomes
        High when GRN exists but still does not cover the threshold.
        """
    )

    st.markdown(
        """
        **Production vs servicing allocation**

        The control flow decides how constrained stock should be split:

        ```text
        Available Qty = Starting Stock Qty + same-week GRN Received Qty
        Production Demand = weekly Production Used Qty
        Servicing Demand = weekly Servicing Demand Qty
        Projected Closing Stock = Available Qty - Production Allocation - Servicing Allocation
        ```

        Allocation happens in three steps:

        1. Protect production first using the selected **Production guard %**.
        2. Protect servicing next using the selected **Servicing guard %**.
        3. Split any remaining stock using the selected production and servicing priority weights.

        For the next week of the same part, projected closing stock becomes the
        next starting stock. This prevents the same opening stock from being
        counted repeatedly across weeks.

        **Escalation ladder**

        - **Critical:** production shortfall or severe inbound cover gap. PPC,
          Stores, and the buyer must act before release.
        - **High:** servicing shortfall or same-day coverage concern. Stores
          and SCM validate before issue.
        - **Watch:** baseline/source/stock signal needs validation before the
          next shift handover.
        - **Ready:** issue the recommended quantity and close only after posting
          or scan evidence is visible.
        """
    )

    render_rm_material_movement_map_docs()

    st.subheader("5. Inwarding and discrepancy agent")
    st.markdown(
        """
        - Inwarding rows are mapped to a buyer by part number first and supplier second.
        - Gate Entry No is retained so every issue can be checked against the main inwarding table.
        - Issues are grouped buyer-by-buyer and ordered by **Critical, High, Medium**, then age.
        - A problem is shown as **Verified resolved** only when a later refreshed snapshot no longer satisfies the discrepancy rule. Merely adding a note does not resolve it.
        - The action log keeps first-detected, last-checked, acknowledgement, resolution, notes, and escalation state.
        """
    )

    st.subheader("6. Column glossary")

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
            "Five-stage daily workflow",
            help="The shortest path from refreshed source data to assigned action.",
        )
        workflow_columns = st.columns(5)
        workflow_steps = [
            (
                "1 · Readiness",
                "Refresh and verify source freshness, coverage, and data health.",
            ),
            (
                "2 · Stock",
                "Use **Stock Health** for critical, short, missing, and delta-review queues.",
            ),
            (
                "3 · Requirements",
                "Review today, seven-day, month and potential-excess requirements.",
            ),
            (
                "4 · Action",
                "Use **Action Centre** for buyer queues, commitments, and PPC recovery.",
            ),
            (
                "5 · Verify",
                "Use **Audit & Evidence** to reconcile movements and verify resolution.",
            ),
        ]
        for column, (title, description) in zip(
            workflow_columns,
            workflow_steps,
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
                        "Management brief, top risks, supplier actions, excess signals, and data gaps",
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
                    ("Supplier Buyer Map", "Find who owns a supplier or part"),
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
                - **Refresh all data** updates production, BOM, SCM stock, outwarding,
                  inwarding, buyer mapping, and discrepancy checks.
                - A failed source keeps its previous saved copy.
                - Google access is **read-only**; this app does not edit the source sheets.
                - **Total production so far** is Visibility: P-VIN + VNA + Free
                  VIN at the source's latest update.
                - **Produced P-VIN** is read only from the explicit P-VIN
                  column. It is never inferred from total production.
                """
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
                        "Inventory Control",
                        "Active",
                        "Creates persistent unexplained-delta cases, verifies disappearance, and logs reason/requester/approver for correction requests.",
                    ),
                    (
                        "Shortage Prevention",
                        "Active",
                        "Calculates today/7-day/month requirements, required-by date, severity and buyer ownership.",
                    ),
                    (
                        "Supplier Follow-up",
                        "Active with approval",
                        "Tracks quantity, ETA and follow-up; drafts a message but requires a human to send it.",
                    ),
                    (
                        "Production Recovery",
                        "Planning estimate",
                        "Provides expedite, affected-production cap and resequencing scenarios.",
                    ),
                    (
                        "Movement Reconciliation",
                        "Active",
                        "Separates COGI, unexplained deltas, invoice/receipt differences and possible duplicates.",
                    ),
                    (
                        "Master Data",
                        "Detection active",
                        "Finds missing ownership, supplier, descriptions and SCM revision/match issues; edits require confirmation.",
                    ),
                    (
                        "Management Briefing",
                        "Active",
                        "Summarizes top risks, overdue commitments, delta reviews and decisions requiring attention.",
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

    servicing_for_usage = pd.DataFrame(columns=TABLES["outwarding_parts"]["columns"])
    try:
        servicing_for_usage, servicing_meta = refresh_servicing_google_sheet(credentials)
        completed.append(
            "CPD/PNA servicing tracker "
            f"({len(servicing_for_usage):,} rows; latest tab "
            f"{clean_text(servicing_meta.get('latest_tab', '')) or 'not found'})"
        )
    except Exception as exc:
        failed.append(f"CPD/PNA servicing tracker — {exc}")

    try:
        sr_posting, sr_meta = refresh_sr_311_posting_google_sheet(credentials)
        completed.append(
            "311 SR Posting tracker "
            f"({len(sr_posting):,} rows from "
            f"{clean_text(sr_meta.get('sheet_tab', 'SR Posting'))})"
        )
    except Exception as exc:
        failed.append(f"311 SR Posting tracker — {exc}")

    if refreshed_sources:
        try:
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
                servicing_for_usage,
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
        .supplier-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .rm-owner-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 720px) {
        .supplier-grid { grid-template-columns: 1fr; }
        .rm-owner-cards { grid-template-columns: 1fr; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


with st.sidebar:
    st.title(
        APP_TITLE,
        help=(
            "Use the navigation below to review stock, ownership, inwarding, "
            "outwarding, documentation, and setup."
        ),
    )
    page = st.radio(
        "Navigation",
        [
            "Inventory Management Agent",
            "RM Planning Agent",
            "Supplier Buyer Map",
            "Inwarding Parts",
            "Outwarding Parts",
            "Documentation",
            "Setup",
        ],
        label_visibility="collapsed",
    )


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
    command_bar = st.columns([1, 1, 1, 1.15, 1.15])
    with command_bar[0]:
        st.metric("Production date", selected_plan_date)
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
        )
    with command_bar[4]:
        master_refresh_clicked = st.button(
            "Refresh all data",
            type="primary",
            disabled=credentials is None,
            help=(
                "Refresh production, BOM, SCM stock, outwarding, inwarding, "
                "buyer mapping, and agent checks."
            ),
            width="stretch",
        )
        st.caption(
            "Previous copies remain if a source fails."
        )
    if credentials is None:
        st.caption(
            "Connect Google in Setup to enable refresh. Saved data remains available."
        )
    if master_refresh_clicked:
        with st.spinner("Refreshing all inventory sources and agent checks..."):
            completed, failed = perform_master_refresh(credentials)
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
    st.caption(
        "1 · Data readiness → 2 · Stock position → 3 · Shortage risk → "
        "4 · Supplier & PPC actions → 5 · Resolution & audit"
    )
    inventory_workspace = st.radio(
        "Inventory workflow",
        [
            "Overview",
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
    elif inventory_workspace == "Stock Health":
        render_stock_health_workspace()
    elif inventory_workspace == "Requirements":
        render_requirements_workspace()
    elif inventory_workspace == "Action Centre":
        render_action_centre()
    else:
        render_audit_evidence_workspace()
elif page == "RM Planning Agent":
    render_rm_planning_agent()

elif page == "Supplier Buyer Map":
    render_supplier_buyer_map()
elif page == "Inwarding Parts":
    render_inwarding()
elif page == "Outwarding Parts":
    render_outwarding()
elif page == "Documentation":
    render_documentation()
else:
    render_setup()
