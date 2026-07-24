from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urlparse, urlunparse

import pandas as pd
import requests
import streamlit as st
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow


APP_TITLE = "Inventory Management Agent"
DATA_DIR = Path("data")
DEFAULT_GOOGLE_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1V3ic-5Dfcz0PoX-0Z0gXdIrFIIOB_lSh-gM20RzLUKs/edit?gid=2111379627#gid=2111379627"
)
SHEET_LINK_PATH = DATA_DIR / "google_sheet_link.txt"
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
GOOGLE_OAUTH_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
GOOGLE_TOKEN_PATH = Path(".streamlit/google_oauth_token.json")
GOOGLE_STATE_PATH = Path(".streamlit/google_oauth_state.txt")

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


def is_google_sheet_link(url: str) -> bool:
    parsed = urlparse(url.strip())
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc == "docs.google.com"
        and re.match(r"^/spreadsheets/d/[^/]+", parsed.path) is not None
    )


def save_sheet_link(url: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = SHEET_LINK_PATH.with_suffix(".tmp")
    tmp_path.write_text(url.strip(), encoding="utf-8")
    tmp_path.replace(SHEET_LINK_PATH)


def load_sheet_link() -> str:
    if not SHEET_LINK_PATH.exists():
        return ""
    return SHEET_LINK_PATH.read_text(encoding="utf-8").strip()


def embedded_sheet_url(url: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"rm": "minimal", "widget": "true"})
    return urlunparse(parsed._replace(query=urlencode(query)))


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


def build_google_oauth_flow(settings: dict[str, str], state: str | None = None) -> Flow:
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


def parse_google_sheet_url(url: str) -> tuple[str, str | None]:
    match = re.search(r"/spreadsheets/d/([^/]+)", url)
    if not match:
        raise ValueError("This does not look like a Google Sheets link.")
    spreadsheet_id = match.group(1)
    parsed = urlparse(url)
    query_gid = parse_qs(parsed.query).get("gid", [None])[0]
    fragment_gid_match = re.search(r"gid=(\d+)", parsed.fragment or "")
    gid = fragment_gid_match.group(1) if fragment_gid_match else query_gid
    return spreadsheet_id, gid


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


def load_google_sheet(url: str, credentials: Credentials) -> tuple[pd.DataFrame, str]:
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

    if gid is None:
        selected_properties = min(
            (item["properties"] for item in sheets),
            key=lambda properties: properties.get("index", 0),
        )
    else:
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
        timeout=30,
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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
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
                # Actual daily production = P-VIN + VNA + Free VINs.
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
    sku_map = parse_sku_map(sku_mapping)
    production, unmatched = parse_vin_detail_production(vin_details, sku_map)
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

    bom = exploded_bom[list(required_bom)].copy()
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
        type_map = type_map.drop_duplicates("Part No.")
        usage = usage.merge(type_map, on="Part No.", how="left")
    else:
        usage["Material Type"] = ""

    raw_columns = {
        "Component number",
        "Object description",
        "Material type",
    }
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
        supplier_map = (
            supplier_map.groupby("Part No.", as_index=False)
            .agg({"Supplier Part Name": joined_text, "Supplier": joined_text})
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


def render_linked_google_sheet() -> None:
    st.header("Linked Google Sheet")
    st.write(
        "Add a Google Sheets link to display the live sheet inside the app. "
        "You can interact with it using your browser's signed-in Google account."
    )

    saved_link = load_sheet_link()
    entered_link = st.text_input(
        "Google Sheet link",
        value=saved_link or DEFAULT_GOOGLE_SHEET_URL,
        placeholder="https://docs.google.com/spreadsheets/d/...",
    )
    if st.button("Add link and display", type="primary"):
        if not is_google_sheet_link(entered_link):
            st.error("Enter a valid docs.google.com Google Sheets link.")
        else:
            save_sheet_link(entered_link)
            st.success("Google Sheet link saved.")
            st.rerun()

    saved_link = load_sheet_link()
    if not saved_link:
        st.info("Add a Google Sheet link to display it here.")
        return

    left, right = st.columns([1, 5])
    with left:
        st.link_button("Open in new tab", saved_link)
    with right:
        st.caption(
            "This is the live sheet, not a copied file. Google controls viewing and editing permissions."
        )

    st.components.v1.iframe(
        embedded_sheet_url(saved_link),
        height=780,
        scrolling=True,
    )


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
        st.caption("Save these values in .streamlit/secrets.toml, then restart Streamlit.")
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
                loaded_tabs = []
                for source in SOURCE_SHEETS.values():
                    source_df, source_tab = load_google_sheet(
                        source["url"],
                        credentials,
                    )
                    save_source_cache(source["cache"], source_df)
                    loaded_tabs.append(source_tab)
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
    filter_columns = st.columns([2, 2, 3])
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
        material_options = sorted(
            value
            for value in filtered["Material Type"].astype(str).unique()
            if value
        )
        selected_materials = st.multiselect(
            "Material type",
            material_options,
            placeholder="All material types",
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
            "FG code and were excluded. Review the diagnostic below."
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
    st.write(
        "Production consumption will be calculated from daily production × BOM. "
        "Servicing issues remain a separate outwarding source."
    )
    df = load_table("outwarding_parts")
    render_outwarding_sources(df)
    st.divider()
    st.subheader("Servicing and Other Manual Outwarding")
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
    st.write("This app stores editable tables locally and can embed a linked Google Sheet.")
    st.markdown(
        """
        For two people working together:

        - Code changes should happen through GitHub branches.
        - App usage can happen through one shared Streamlit URL.
        - Add a Google Sheets URL on the Linked Google Sheet page.
        - Access and editing are handled by the Google account signed into your browser.
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
            "Linked Google Sheet",
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
elif page == "Linked Google Sheet":
    render_linked_google_sheet()
elif page == "Inwarding Parts":
    render_inwarding()
elif page == "Outwarding Parts":
    render_outwarding()
elif page == "Agentic Flow":
    render_agentic_flow()
else:
    render_setup()
