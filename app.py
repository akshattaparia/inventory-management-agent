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


def sheet_url(spreadsheet_id: str, gid: int) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        f"?gid={gid}#gid={gid}"
    )


SOURCE_SHEETS = {
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
OUTWARDING_BASELINE_PATH = DATA_DIR / "outwarding_plan_baseline.csv"
OUTWARDING_ALERT_LOG_PATH = DATA_DIR / "outwarding_alert_log.csv"
OUTWARDING_OWNER_DEFAULT = "Akshat Taparia, Abhiraj Koslia"
AGENT_TABLE_LIMIT = 250
INWARDING_SHEET_URL = DEFAULT_GOOGLE_SHEET_URL
INWARDING_SNAPSHOT_PATH = DATA_DIR / "inwarding_sheet_snapshot.csv"
INWARDING_SNAPSHOT_META_PATH = DATA_DIR / "inwarding_sheet_snapshot.json"
BUYER_MAPPING_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "147vIBFZxf6aQddMG-cpQmuFtcM-6nH0pjn0HDHMyLhE/edit?gid=0#gid=0"
)
BUYER_MAPPING_CACHE_PATH = DATA_DIR / "buyer_mapping_source.csv"
AGENT_ACTIONS_PATH = DATA_DIR / "agent_actions.csv"
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


def parse_vin_detail_production(
    df: pd.DataFrame,
    sku_map: dict[tuple[str, str], str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = ["Usage Date", "FG", "Produced Qty", "Production Source"]
    unmatched_columns = ["Usage Date", "Model", "Color", "Produced Qty"]
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
    date_columns: list[tuple[list[int], pd.Timestamp]] = []
    current_year = pd.Timestamp.now(tz="Asia/Kolkata").year
    for index, value in enumerate(date_header):
        if re.fullmatch(r"\d{1,2}-[A-Za-z]{3}", value.strip()):
            parsed_date = pd.to_datetime(
                f"{value.strip()}-{current_year}",
                format="%d-%b-%Y",
                errors="coerce",
            )
            if pd.notna(parsed_date) and index + 7 < len(date_header):
                date_columns.append(
                    ([index + 1, index + 3, index + 5], parsed_date.normalize())
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
            actual_values = [
                pd.to_numeric(
                    str(row[column]).replace(",", ""),
                    errors="coerce",
                )
                for column in actual_columns
            ]
            quantity = sum(
                float(value) for value in actual_values if pd.notna(value)
            )
            if quantity <= 0:
                continue
            values = {
                "Usage Date": usage_date,
                "Model": current_model,
                "Color": color,
                "Produced Qty": float(quantity),
            }
            if fg:
                production_rows.append(
                    {
                        "Usage Date": usage_date,
                        "FG": fg,
                        "Produced Qty": float(quantity),
                        "Production Source": "VIN Details Daily",
                    }
                )
            else:
                unmatched_rows.append(values)

    production = pd.DataFrame(production_rows, columns=columns)
    if not production.empty:
        production = (
            production.groupby(
                ["Usage Date", "FG", "Production Source"],
                as_index=False,
            )["Produced Qty"]
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
        "Part No.",
        "Part Name",
        "Supplier",
        "Production Used Qty",
        "Servicing Used Qty",
        "Total Outwarding Qty",
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
        "Production Used Qty",
        "Servicing Used Qty",
        "Total Outwarding Qty",
    ]:
        result[column] = numeric(result[column])
    result["Part No."] = result["Part No."].astype(str).str.strip()
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
        "Part Name",
        "Supplier",
        "Production Used Qty",
        "Servicing Used Qty",
        "Total Outwarding Qty",
    ]
    if prepared.empty:
        return pd.DataFrame(columns=columns)
    return (
        prepared.groupby(["Plan Week", "Part No."], as_index=False)
        .agg(
            **{
                "Part Name": ("Part Name", joined_text),
                "Supplier": ("Supplier", joined_text),
                "Production Used Qty": ("Production Used Qty", "sum"),
                "Servicing Used Qty": ("Servicing Used Qty", "sum"),
                "Total Outwarding Qty": ("Total Outwarding Qty", "sum"),
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
        current_qty = scalar_float(row.get("Total Outwarding Qty_current", 0))
        baseline_qty = scalar_float(row.get("Total Outwarding Qty_baseline", 0))
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
            "Supplier": "Outward Supplier",
            "Total Outwarding Qty": "Outwarding Qty",
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
    for column in ["Buyer", "Mapped Supplier", "Outward Supplier", "Inward Supplier", "Part Name", "Last Arrival Date"]:
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
        buyer = clean_text(row.get("Buyer", "")) or "Akshat Taparia, Abhiraj Koslia"
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


def load_part_owner_lookup() -> pd.DataFrame:
    raw = load_sheet_snapshot(SPOC_SUMMARY_SNAPSHOT_CSV)
    if raw.empty:
        return pd.DataFrame(columns=["Part No.", "Buyer", "Mapped Supplier"])
    try:
        parts, _ = parse_spoc_summary_raw(raw)
    except Exception:
        return pd.DataFrame(columns=["Part No.", "Buyer", "Mapped Supplier"])
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
    st.header("Supplier Buyer Map")
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
        selected_buyer = st.selectbox("Buyer view", ["All buyers"] + buyers, index=0)
    with filter_cols[1]:
        selected_statuses = st.multiselect(
            "Status",
            sorted(parts["Status"].unique().tolist()),
            default=[],
        )
    with filter_cols[2]:
        selected_suppliers = st.multiselect("Supplier", supplier_values, default=[])
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
    st.subheader("Supplier Ownership Snapshot")
    st.markdown(supplier_cards_html(filtered_summary), unsafe_allow_html=True)
    if len(filtered_summary) > 24:
        st.caption(f"Showing first 24 supplier cards out of {len(filtered_summary):,}. Use filters to narrow the view.")

    st.subheader("Part-Level Mapping")
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
    st.header("Inwarding Parts")
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
        supplier_options = sorted(
            value
            for value in filtered.get(
                "Supplier Name",
                pd.Series(dtype=str),
            ).astype(str).unique()
            if value
        )
        selected_suppliers = st.multiselect(
            "Supplier",
            supplier_options,
            placeholder="All suppliers",
            key="inwarding_snapshot_suppliers",
        )
    with filter_columns[4]:
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


def render_outwarding_sources(manual_outwarding: pd.DataFrame) -> None:
    st.subheader("Computed Daily Part Usage")
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

    render_outwarding_flagging_agent(combined)
    st.divider()
    render_inbound_coverage_agent(combined)
    st.divider()

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
    st.header("Outwarding Parts")
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
    st.header("Inwarding Discrepancy Agent")
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
    st.header("Inwarding Discrepancy Agent")
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
    st.header("Setup")
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
    @media (max-width: 1000px) {
        .supplier-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 720px) {
        .supplier-grid { grid-template-columns: 1fr; }
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
            "Supplier Buyer Map",
            "Inwarding Parts",
            "Outwarding Parts",
            "Setup",
        ],
        label_visibility="collapsed",
    )


st.title(APP_TITLE)

if page == "Part Inventory":
    render_part_inventory()
elif page == "Supplier Buyer Map":
    render_supplier_buyer_map()
elif page == "Inwarding Parts":
    render_inwarding()
elif page == "Outwarding Parts":
    render_outwarding()
else:
    render_setup()
