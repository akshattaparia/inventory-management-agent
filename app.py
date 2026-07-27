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
RM_FOLLOWUP_COLUMNS = [
    "Part No.",
    "Supplier Status",
    "Expected Delivery",
    "Next Follow-up",
    "Follow-up Owner",
    "Follow-up Notes",
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
            "Opening Stock",
            "System Stock",
            "Physical Stock",
            "SCM Stock Match",
            "Stock Data Status",
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
    """Read model-level Daily Plan values from Production Plan Breakup_Rev.1."""
    columns = ["Plan Date", "Model", "Planned Qty"]
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
    date_columns: list[tuple[int, pd.Timestamp]] = []
    for index, label in enumerate(label_row):
        if normalize_column_name(label) != "daily_plan":
            continue
        plan_date = parse_sheet_date(date_row[index] if index < len(date_row) else "")
        if pd.notna(plan_date):
            date_columns.append((index, plan_date.normalize()))

    records: list[dict[str, object]] = []
    for row in rows[plan_header + 3 :]:
        model = clean_text(row[0] if row else "")
        if normalize_column_name(model) in {"total_auto", "variant"}:
            if normalize_column_name(model) == "total_auto":
                break
            continue
        if not model:
            continue
        for column_index, plan_date in date_columns:
            value = row[column_index] if column_index < len(row) else ""
            quantity = pd.to_numeric(str(value).replace(",", ""), errors="coerce")
            if pd.notna(quantity) and float(quantity) > 0:
                records.append(
                    {
                        "Plan Date": plan_date,
                        "Model": model,
                        "Planned Qty": float(quantity),
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
    """Build FG-level plan and actuals while keeping the weekly total authoritative."""
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
    model_plan["Planned Qty"] = allocate_integer_quantities(
        model_plan["Planned Qty"],
        daily_target,
    )

    plan_rows: list[pd.DataFrame] = []
    fallback_dates: list[pd.Timestamp] = []
    missing_models: list[str] = []
    for _, model_row in model_plan.iterrows():
        model = str(model_row["Model"])
        model_key = canonical_model(model)
        quantity = float(model_row["Planned Qty"])
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
            quantity,
        )
        plan_rows.append(candidates[["FG", "Produced Qty"]])

    planned = (
        pd.concat(plan_rows, ignore_index=True)
        if plan_rows
        else pd.DataFrame(columns=["FG", "Produced Qty"])
    )
    if not planned.empty:
        planned = planned.groupby("FG", as_index=False)["Produced Qty"].sum()
        planned["Usage Date"] = plan_date
        planned["Production Source"] = "Daily plan × variant mix"

    actual = detail[
        detail["Plan Date"].eq(plan_date) & detail["Produced Qty"].gt(0)
    ].groupby("FG", as_index=False)["Produced Qty"].sum()
    if not actual.empty and produced_target >= 0:
        actual["Produced Qty"] = allocate_integer_quantities(
            actual["Produced Qty"],
            produced_target,
        )
        actual = actual[actual["Produced Qty"].gt(0)]
    if not actual.empty:
        actual["Usage Date"] = plan_date
        actual["Production Source"] = "P-VIN + VNA + Free VIN actuals so far"

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


def build_part_inventory_plan(
    saved_inventory: pd.DataFrame,
    sources: dict[str, pd.DataFrame],
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
        "Opening Stock",
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

    physical_raw = result["Physical Stock"].fillna("").astype(str).str.strip()
    physical_numeric = pd.to_numeric(physical_raw, errors="coerce")
    stock_available = physical_raw.ne("") & physical_numeric.notna()
    physical = physical_numeric.fillna(0)
    result["Stock Data Status"] = "Available"
    result.loc[~stock_available, "Stock Data Status"] = "Missing"
    result["Required Qty"] = (
        result["Remaining Part Need"] - physical
    ).clip(lower=0).apply(lambda value: int(-(-value // 1)))
    result["Closing Stock"] = physical - result["Remaining Part Need"]
    result["Plan Date"] = plan_date.strftime("%Y-%m-%d")
    result["Daily Production Plan"] = diagnostics.get("daily_target", 0)
    result["Produced So Far"] = diagnostics.get("produced_target", 0)
    result["Status"] = "Healthy"
    result.loc[result["Required Qty"].gt(0), "Status"] = "Below required"
    result.loc[result["Required Qty"].gt(0) & physical.le(0), "Status"] = "Critical"
    result.loc[~stock_available, "Required Qty"] = pd.NA
    result.loc[~stock_available, "Closing Stock"] = pd.NA
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
    if status == "delayed":
        eta = expected.strftime("%d %b") if pd.notna(expected) else "confirmed ETA"
        return (
            f"Protect unaffected builds; move {affected} after {eta} or secure an "
            "alternate/expedite supply."
        )
    if pd.notna(expected) and pd.notna(required_by) and expected > required_by:
        return (
            f"ETA is after line need. Reschedule {affected}, expedite the shortage, "
            "or approve an alternate source."
        )
    if status in {"confirmed", "in transit"}:
        return "No plan change yet; monitor delivery against the required-by date."
    return (
        "Get supplier quantity and ETA confirmation by the next follow-up; "
        "keep an alternate build sequence ready."
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
    physical_source = base["Physical Stock"].fillna("").astype(str).str.strip()
    base["Stock Known"] = (
        base.get("Stock Data Status", pd.Series("", index=base.index))
        .astype(str)
        .eq("Available")
        | (
            physical_source.ne("")
            & pd.to_numeric(physical_source, errors="coerce").notna()
        )
    )
    base["Physical Stock"] = numeric(base["Physical Stock"])
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
            "Enter the current physical count in Part Inventory, then save stock values."
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
            view["Gross RM Need"] - view["Physical Stock"]
        ).clip(lower=0).apply(lambda value: int(-(-value // 1)))
        view["Horizon"] = label
        view["Horizon Vehicle Plan"] = max(
            daily_target - produced_so_far,
            0,
        ) + future_vehicle_plan

        cumulative = view["Remaining Part Need"].astype(float).copy()
        shortage_dates = pd.Series(pd.NaT, index=view.index, dtype="datetime64[ns]")
        shortage_dates.loc[cumulative.gt(view["Physical Stock"])] = plan_date
        for _, plan_row in future_plan.sort_values("Plan Date").iterrows():
            cumulative += (
                view["Part per Planned Vehicle"]
                * float(plan_row["Daily Production Plan"])
            )
            newly_short = shortage_dates.isna() & cumulative.gt(view["Physical Stock"])
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
    stock_available = physical_raw.ne("") & pd.to_numeric(
        physical_raw,
        errors="coerce",
    ).notna()
    required = numeric(result["Required Qty"])
    closing = numeric(result["Closing Stock"])
    physical = numeric(result["Physical Stock"])
    stock = closing.where(closing != 0, physical)
    result["Status"] = "Healthy"
    result.loc[required <= 0, "Status"] = "Requirement missing"
    result.loc[(required > 0) & (stock < required), "Status"] = "Below required"
    result.loc[(required > 0) & (stock <= 0), "Status"] = "Critical"
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


def render_part_inventory() -> None:
    st.header("Part Inventory")
    st.write(
        "Part requirement for the selected production day. Actual production means "
        "production completed **so far**, while Physical Stock means stock available now."
    )

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
        )
        if diagnostics.get("error"):
            st.warning(str(diagnostics["error"]))

    cols = st.columns(5)

    if diagnostics:
        plan_date = diagnostics.get("fallback_mix_date")
        message = (
            f"Daily target: {display_qty(diagnostics.get('daily_target', 0))} vehicles · "
            f"Produced so far: {display_qty(diagnostics.get('produced_target', 0))} vehicles."
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
                f"SCM stock synced for {scm_mapped:,} parts from Summary → "
                f"{stock_label or 'System Opening Stock'}. The same value is used for "
                "System Stock and Physical Stock for now."
            )

    st.subheader("Part Requirement Table")
    st.caption(
        "Required Qty = max(Planned Part Consumption − Consumed So Far − current Physical Stock, 0). "
        "Enter current Physical Stock and save; blue/grey calculated columns are refreshed from source data."
    )
    filter_columns = st.columns([2, 1.3])
    with filter_columns[0]:
        search = st.text_input(
            "Search part",
            placeholder="part number, part name, buyer, or supplier",
            key="part_inventory_search",
        )
    suppliers = sorted(
        df.get("Supplier", pd.Series(dtype=str)).replace("", pd.NA).dropna().unique().tolist()
    )
    with filter_columns[1]:
        supplier_filter = st.selectbox(
            "Supplier",
            ["All suppliers"] + suppliers,
            key="part_inventory_supplier",
        )
    filtered = df.copy()
    if search.strip():
        term = search.strip().lower()
        searchable = ["Part No.", "Part Name", "Buyer", "Supplier"]
        filtered = filtered[
            filtered[searchable]
            .astype(str)
            .apply(lambda column: column.str.lower().str.contains(term, na=False))
            .any(axis=1)
        ]
    if supplier_filter != "All suppliers":
        filtered = filtered[filtered["Supplier"].eq(supplier_filter)]

    stock_input_columns = [
        "Part No.",
        "Part Name",
        "Physical Stock",
        "Opening Stock",
        "System Stock",
        "Remarks",
    ]
    st.markdown("**1. Update current stock**")
    scm_stock_active = int(diagnostics.get("scm_stock_rows_mapped", 0)) > 0
    if scm_stock_active:
        st.caption(
            "System Stock and Physical Stock are source-controlled from SCM Summary. "
            "Use the Missing stock queue in RM Planning Agent only for parts not found there."
        )
    else:
        st.caption(
            "Changing Physical Stock below immediately recalculates the requirement view in step 2."
        )
    st.caption(f"{len(filtered):,} of {len(df):,} parts shown.")
    edited_stock = st.data_editor(
        filtered[stock_input_columns],
        use_container_width=True,
        hide_index=True,
        disabled=(
            ["Part No.", "Part Name", "System Stock", "Physical Stock"]
            if scm_stock_active
            else ["Part No.", "Part Name"]
        ),
        key=(
            "part_inventory_editor_scm"
            if scm_stock_active
            else "part_inventory_editor"
        ),
        column_config={
            "Physical Stock": st.column_config.NumberColumn(
                "Physical Stock",
                help="Stock physically available now, after production completed so far.",
                min_value=0.0,
            ),
        },
        height=330,
    )

    recalculated = filtered.set_index("Part No.", drop=False)
    stock_updates = edited_stock.set_index("Part No.", drop=False)
    for column in ["Physical Stock", "Opening Stock", "System Stock", "Remarks"]:
        recalculated.loc[stock_updates.index, column] = stock_updates[column]
    live_physical_raw = recalculated["Physical Stock"].fillna("").astype(str).str.strip()
    live_stock_available = live_physical_raw.ne("") & pd.to_numeric(
        live_physical_raw,
        errors="coerce",
    ).notna()
    current_physical = pd.to_numeric(
        live_physical_raw,
        errors="coerce",
    ).fillna(0)
    recalculated["Required Qty"] = (
        numeric(recalculated["Remaining Part Need"]) - current_physical
    ).clip(lower=0).apply(lambda value: int(-(-value // 1)))
    recalculated["Closing Stock"] = (
        current_physical - numeric(recalculated["Remaining Part Need"])
    )
    recalculated["Status"] = "Healthy"
    recalculated.loc[recalculated["Required Qty"].gt(0), "Status"] = "Below required"
    recalculated.loc[
        recalculated["Required Qty"].gt(0) & current_physical.le(0),
        "Status",
    ] = "Critical"
    recalculated["Stock Data Status"] = "Available"
    recalculated.loc[~live_stock_available, "Stock Data Status"] = "Missing"
    recalculated.loc[~live_stock_available, "Required Qty"] = pd.NA
    recalculated.loc[~live_stock_available, "Closing Stock"] = pd.NA
    recalculated.loc[~live_stock_available, "Status"] = "Stock data missing"
    recalculated = recalculated.reset_index(drop=True)

    live_full = df.set_index("Part No.", drop=False)
    live_updates = recalculated.set_index("Part No.", drop=False)
    for column in [
        "Physical Stock",
        "Opening Stock",
        "System Stock",
        "Remarks",
        "Required Qty",
        "Closing Stock",
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

    st.markdown("**2. Live recalculated requirement**")
    st.dataframe(
        recalculated,
        use_container_width=True,
        hide_index=True,
        height=430,
        column_config={
            "Physical Stock": st.column_config.NumberColumn(
                help="The value currently entered in step 1."
            ),
            "Required Qty": st.column_config.NumberColumn(
                help="Immediately recalculated as max(Remaining Part Need − Physical Stock, 0)."
            ),
            "Closing Stock": st.column_config.NumberColumn(
                help="Physical Stock minus Remaining Part Need."
            ),
        },
    )
    action_columns = st.columns([1, 1, 4])
    with action_columns[0]:
        if st.button("Save stock values", type="primary"):
            merged = df.set_index("Part No.", drop=False)
            updates = edited_stock.set_index("Part No.", drop=False)
            editable_columns = [
                "Opening Stock",
                "System Stock",
                "Physical Stock",
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
            f"""
            <div class="rm-owner-card {tone}">
                <div class="rm-owner-name">{escape(str(row['Buyer']))}</div>
                <div class="rm-owner-grid">
                    <div><b>{int(row['Issues']):,}</b><span>parts</span></div>
                    <div><b>{int(row['Critical']):,}</b><span>critical</span></div>
                    <div><b>{int(row['Suppliers']):,}</b><span>suppliers</span></div>
                </div>
            </div>
            """
        )
    return f"<div class='rm-owner-cards'>{''.join(cards)}</div>"


def save_rm_followup_record(
    part_no: str,
    supplier_status: str,
    expected_delivery: str,
    next_followup: str,
    owner: str,
    notes: str,
) -> None:
    existing = load_rm_followups().set_index("Part No.", drop=False)
    existing.loc[part_no, "Part No."] = part_no
    existing.loc[part_no, "Supplier Status"] = supplier_status
    existing.loc[part_no, "Expected Delivery"] = expected_delivery
    existing.loc[part_no, "Next Follow-up"] = next_followup
    existing.loc[part_no, "Follow-up Owner"] = owner
    existing.loc[part_no, "Follow-up Notes"] = notes
    save_rm_followups(existing.reset_index(drop=True))


def render_rm_planning_agent() -> None:
    st.header("RM Planning Agent")
    st.write(
        "A decision workspace for PPC and SCM: see the parts that can constrain the "
        "plan, understand why, and assign the next supplier action."
    )

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
            "Physical Stock comes from Part Inventory."
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

    st.subheader("Management cockpit")
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
            "for both System Stock and Physical Stock."
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
            "- Known Physical Stock is required before a part can be called a shortage.\n"
            "- Future total vehicle plans use the current saved part-per-vehicle mix "
            "when a detailed future mix is unavailable.\n"
            "- Supplier messages are scheduled and tracked here but are not sent automatically."
        )
        if pd.notna(fallback_mix_date):
            st.write(
                f"Current variant-colour mix fallback: "
                f"**{pd.Timestamp(fallback_mix_date):%d %b %Y}**."
            )

    st.subheader("Priority workspace")
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
    suppliers = sorted(
        queue.get("Supplier", pd.Series(dtype=str))
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
    with filters[2]:
        selected_supplier = st.selectbox(
            "Supplier",
            ["All suppliers"] + suppliers,
            key="rm_agent_supplier",
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
                "Physical Stock",
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
    st.subheader("Selected issue")
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
            physical_entry = st.number_input(
                "Current Physical Stock",
                min_value=0.0,
                value=0.0,
                key=f"rm_missing_stock_{stock_part_key(selected['Part No.'])}",
                help="Enter the physical count available now, after production so far.",
            )
            if st.button("Save physical stock", type="primary"):
                updated = inventory.copy()
                updated.loc[
                    updated["Part No."].eq(selected["Part No."]),
                    "Physical Stock",
                ] = physical_entry
                save_table("part_inventory", updated)
                st.success("Physical Stock saved. The agent will recalculate this part.")
                st.rerun()
        return

    evidence_columns = st.columns(4)
    with evidence_columns[0]:
        render_metric("Physical stock", display_qty(selected["Physical Stock"]), "neutral")
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
            f"**{display_qty(selected['Gross RM Need'])}** units. Current Physical Stock "
            f"is **{display_qty(selected['Physical Stock'])}**, leaving a shortage of "
            f"**{display_qty(selected['RM Shortage'])}**."
        )
        st.markdown("#### Production impact")
        st.write(
            f"**Affected variants:** "
            f"{clean_text(selected['Affected Variants']) or 'Variant mapping unavailable'}"
        )
        confidence = (
            "High — physical stock and plan are available."
            if horizon_name == "Today"
            else "Planning estimate — future totals use the current saved variant mix."
        )
        st.caption(f"Data confidence: {confidence}")

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
            "Supplier status",
            statuses,
            index=statuses.index(current_status)
            if current_status in statuses
            else 0,
            key=f"rm_detail_status_{stock_part_key(selected['Part No.'])}",
        )
        expected_delivery = st.text_input(
            "Expected delivery",
            value=clean_text(selected["Expected Delivery"]),
            placeholder="YYYY-MM-DD",
            key=f"rm_detail_eta_{stock_part_key(selected['Part No.'])}",
        )
        next_followup = st.text_input(
            "Next follow-up",
            value=clean_text(selected["Next Follow-up"]),
            placeholder="YYYY-MM-DD",
            key=f"rm_detail_followup_{stock_part_key(selected['Part No.'])}",
        )
        owner = st.text_input(
            "Follow-up owner",
            value=clean_text(selected["Follow-up Owner"]) or clean_text(selected["Buyer"]),
            key=f"rm_detail_owner_{stock_part_key(selected['Part No.'])}",
        )
        notes = st.text_area(
            "Notes",
            value=clean_text(selected["Follow-up Notes"]),
            key=f"rm_detail_notes_{stock_part_key(selected['Part No.'])}",
        )
        recommendation_row = selected.copy()
        recommendation_row["Supplier Status"] = supplier_status
        recommendation_row["Expected Delivery"] = expected_delivery
        st.info("**Agent recommendation**  \n" + rm_recommendation(recommendation_row))
        if st.button("Save supplier action", type="primary"):
            save_rm_followup_record(
                clean_text(selected["Part No."]),
                supplier_status,
                expected_delivery,
                next_followup,
                owner,
                notes,
            )
            st.success("Supplier action saved.")
            st.rerun()


def render_live_google_sheet() -> None:
    st.header("Live Google Sheet")
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
    st.header("Supplier Buyer Map")
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


def render_inwarding() -> None:
    st.header("Inwarding Parts")
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
    st.subheader("Computed Daily Part Usage")
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


def render_documentation() -> None:
    st.header("Documentation")
    st.write(
        "A plain-language guide to the data sources, refresh rules, calculations, "
        "and discrepancy workflow used by this app."
    )

    st.subheader("1. The two refresh rules")
    st.markdown(
        """
        - **No automatic overwrite:** every page continues to show its last saved copy.
        - **Refresh means pull now:** a Google-backed page changes only after its Refresh button is clicked.
        - **Read-only access:** the app reads source sheets; it does not edit them.
        - **Produced so far is not final production:** it is the live total completed up to the latest source update.
        """
    )

    st.subheader("2. Part requirement calculation")
    st.info(
        "Physical Stock is the stock available now, after production completed so far. "
        "This timing is essential: consumed parts must not be subtracted from Physical Stock a second time."
    )
    st.markdown(
        """
        For each finished-good variant and every BOM component:

        1. **Planned Part Consumption** = sum of `(planned variant quantity × BOM quantity per variant)`.
        2. **Consumed So Far** = sum of `(actual variant quantity produced so far × BOM quantity per variant)`.
        3. **Remaining Part Need** = `max(Planned Part Consumption − Consumed So Far, 0)`.
        4. **Required Qty** = `max(Remaining Part Need − current Physical Stock, 0)`.

        Shared parts are first summed across **all variants**. Physical Stock is subtracted only once, after that aggregation.
        Required Qty is rounded up to a whole part so the recommendation never under-orders.
        """
    )
    with st.expander("Worked example", expanded=True):
        st.markdown(
            """
            A shared part is needed 1 per vehicle. The daily plan is 850 vehicles,
            300 vehicles have been produced so far, and current Physical Stock is 400.

            - Planned Part Consumption = `850 × 1 = 850`
            - Consumed So Far = `300 × 1 = 300`
            - Remaining Part Need = `850 − 300 = 550`
            - Required Qty = `max(550 − 400, 0) = 150`

            The app recommends 150 additional parts.
            """
        )

    st.subheader("3. How the production plan is mapped to the BOM")
    st.markdown(
        """
        - The **weekly plan/results tab** supplies the authoritative daily total and actual production so far.
        - The **production plan breakup** supplies the model-level daily plan.
        - The **VIN detail** supplies P-VIN + VNA + Free VIN actuals and the model/colour mix.
        - The **SKU map** converts model + colour to a finished-good (FG) number.
        - The **exploded BOM** converts every FG into component quantities.
        - If today's colour mix is not populated yet, the app uses the most recent saved non-zero colour mix for that model and clearly states the fallback date above the table.
        - Whole-vehicle allocation is used, so a normalized plan never creates a fractional vehicle.
        - SCM stock is joined only on an **exact part number**. The app never silently
          assigns a base part's stock to a revision-coded BOM part.
        - Unmatched stock is separated into **Possible revision mismatch** when a
          suffix such as `/B` or `_002` differs but the base part exists, and
          **Not found in SCM Summary** when no base candidate exists.
        - Both groups are excluded from shortage alerts until the stock mapping is
          verified, preventing missing master data from becoming a false line-risk alert.
        """
    )

    source_rows = [
        {
            "Purpose": "Daily plan and actual total",
            "Sheet / tab": "Weekly_Plan & Results_Rev.1",
            "Link": sheet_url(PRODUCTION_SHEET_ID, 1380714334),
        },
        {
            "Purpose": "Model-level plan breakup",
            "Sheet / tab": "Production Plan Breakup_Rev.1",
            "Link": sheet_url(PRODUCTION_SHEET_ID, 643919697),
        },
        {
            "Purpose": "P-VIN, VNA, Free VIN and colour mix",
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
            "Purpose": "System and temporary Physical Stock",
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
    st.dataframe(
        pd.DataFrame(source_rows),
        use_container_width=True,
        hide_index=True,
        column_config={"Link": st.column_config.LinkColumn("Source link")},
    )

    st.subheader("4. Inwarding and discrepancy agent")
    st.markdown(
        """
        - Inwarding rows are mapped to a buyer by part number first and supplier second.
        - Gate Entry No is retained so every issue can be checked against the main inwarding table.
        - Issues are grouped buyer-by-buyer and ordered by **Critical, High, Medium**, then age.
        - A problem is shown as **Verified resolved** only when a later refreshed snapshot no longer satisfies the discrepancy rule. Merely adding a note does not resolve it.
        - The action log keeps first-detected, last-checked, acknowledgement, resolution, notes, and escalation state.
        """
    )

    st.subheader("5. Column glossary")
    glossary = pd.DataFrame(
        [
            ("Daily Production Plan", "Vehicle target for the selected production date."),
            ("Produced So Far", "Vehicles completed so far: P-VIN + VNA + Free VIN, reconciled to the daily results total."),
            ("Planned Part Consumption", "Total part units needed for the complete daily variant plan."),
            ("Consumed So Far", "Part units already consumed by vehicles produced so far."),
            ("Remaining Part Need", "Part units still needed to finish the plan before considering current stock."),
            ("Physical Stock", "Count physically available now, after production so far."),
            ("Required Qty", "Additional part units required after subtracting Physical Stock."),
            ("Closing Stock", "Projected Physical Stock after completing the remaining plan; a negative value is a shortage."),
        ],
        columns=["Column", "Meaning"],
    )
    st.dataframe(glossary, use_container_width=True, hide_index=True)

    st.subheader("6. RM Planning Agent")
    st.markdown(
        """
        - **Today** compares current Physical Stock with the remaining part demand after production so far.
        - **Rolling 7 Days** adds the saved vehicle plans for the next six calendar days.
        - **Remaining Month** adds every remaining positive daily plan available through month-end.
        - When a future date has only a total vehicle plan, the current saved variant/part mix is scaled to that total and is treated as a planning estimate.
        - Blank Physical Stock is classified as **Stock data missing** and is excluded from shortage counts; it is never treated as zero stock.
        - For now, the app copies **Summary → System Opening Stock** into both System Stock and Physical Stock for every mapped part.
        - The first date when cumulative RM demand exceeds Physical Stock becomes **Required By**.
        - Critical means a possible shortage on the first plan day; High means within two days; Medium means later.
        - Use the focused work queues, then select one row to see calculation evidence, production impact, and supplier controls.
        - The agent creates a supplier follow-up schedule two days before the required date by default.
        - Mark a supplier **Delayed** or enter an ETA after Required By to receive a PPC plan-adjustment recommendation.
        - Follow-up schedules are saved locally. The app does not send supplier emails or messages automatically.
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
    st.title(APP_TITLE)
    page = st.radio(
        "Navigation",
        [
            "Part Inventory",
            "RM Planning Agent",
            "Supplier Buyer Map",
            "Inwarding Parts",
            "Outwarding Parts",
            "Documentation",
            "Setup",
        ],
        label_visibility="collapsed",
    )


st.title(APP_TITLE)

if page == "Part Inventory":
    render_part_inventory()
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
