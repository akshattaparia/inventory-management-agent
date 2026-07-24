from __future__ import annotations

import re
import json
import os
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
INWARDING_SHEET_URL = DEFAULT_GOOGLE_SHEET_URL
INWARDING_SNAPSHOT_PATH = DATA_DIR / "inwarding_sheet_snapshot.csv"
INWARDING_SNAPSHOT_META_PATH = DATA_DIR / "inwarding_sheet_snapshot.json"

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
        "Refresh inwarding from Google Sheet",
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
                cleaned_df = clean_inwarding_snapshot(source_df)
                save_inwarding_snapshot(cleaned_df, tab_name)
            st.success(
                f"Saved the latest '{tab_name}' snapshot with "
                f"{len(cleaned_df):,} rows."
            )
        except Exception as exc:
            st.error(
                "Refresh failed. The previous saved snapshot is still being shown. "
                f"Details: {exc}"
            )

    snapshot = clean_inwarding_snapshot(
        load_source_cache(INWARDING_SNAPSHOT_PATH)
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
    filter_columns = st.columns([1.8, 2, 2, 1.5])
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
        part_search = st.text_input(
            "Part number",
            placeholder="Search part number",
            key="inwarding_snapshot_part",
        )
    with filter_columns[2]:
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
    with filter_columns[3]:
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
    if selected_suppliers and "Supplier Name" in filtered.columns:
        filtered = filtered[
            filtered["Supplier Name"].isin(selected_suppliers)
        ]
    if selected_statuses and "Unloading Status" in filtered.columns:
        filtered = filtered[
            filtered["Unloading Status"].isin(selected_statuses)
        ]

    receipt_total = numeric(
        filtered.get("Receipt Qty", pd.Series(dtype=str))
    ).sum()
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
            "Agentic Flow",
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
elif page == "Agentic Flow":
    render_agentic_flow()
else:
    render_setup()
