#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


PROJECT_DIR = Path(__file__).resolve().parents[1]
REQUIRED_EXPORT_COLUMNS = {"grn_no", "movement_type", "part_no", "po_no", "received_qty"}
EXPORT_COLUMN_ALIASES = {
    "mblnr": "grn_no",
    "bwart": "movement_type",
    "matnr": "part_no",
    "ebeln": "po_no",
    "menge": "received_qty",
}
DEFAULT_CATALOG_CANDIDATES = ("hudi", "hive-az", "system")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required setting: {name}")
    return value


def project_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_DIR / path
    return path


def read_sql(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"SQL file not found: {path}")
    return path.read_text(encoding="utf-8").strip().rstrip(";")


def sql_schema_names(sql: str) -> list[str]:
    schema_names = []
    for match in re.finditer(r"\b(?:from|join)\s+([a-zA-Z_][\w]*)\.[a-zA-Z_][\w]*", sql, flags=re.IGNORECASE):
        schema = match.group(1)
        if schema.lower() not in {"select", "where"} and schema not in schema_names:
            schema_names.append(schema)
    return schema_names


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def write_output(frame: pd.DataFrame, output_path: Path, source: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    frame.to_csv(tmp_path, index=False)
    tmp_path.replace(output_path)

    meta = {
        "source": source,
        "rows": int(len(frame)),
        "columns": list(frame.columns),
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_csv": str(output_path),
    }
    output_path.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def export_from_trino(sql: str) -> pd.DataFrame:
    try:
        import pandas as pd
        import trino
        from trino.auth import BasicAuthentication, JWTAuthentication
    except ImportError as exc:
        raise SystemExit("Install dependencies first: python -m pip install -r requirements.txt") from exc

    host = env_required("TRINO_HOST")
    port = int(os.getenv("TRINO_PORT", "443"))
    user = os.getenv("TRINO_USER", "").strip() or os.getenv("USER", "inventory-agent")
    http_scheme = os.getenv("TRINO_HTTP_SCHEME", "https").strip() or "https"
    catalog = os.getenv("TRINO_CATALOG", "").strip() or None
    schema = os.getenv("TRINO_SCHEMA", "").strip() or None
    verify_ssl = os.getenv("TRINO_SSL_VERIFY", "true").strip().lower() not in {"0", "false", "no"}

    auth_mode = os.getenv("TRINO_AUTH", "none").strip().lower()
    auth = None
    if auth_mode == "basic":
        auth = BasicAuthentication(user, env_required("TRINO_PASSWORD"))
    elif auth_mode in {"jwt", "token", "bearer"}:
        auth = JWTAuthentication(env_required("TRINO_TOKEN"))

    def connect_with_catalog(catalog_name: str | None):
        return trino.dbapi.connect(
            host=host,
            port=port,
            user=user,
            catalog=catalog_name,
            schema=schema,
            http_scheme=http_scheme,
            auth=auth,
            verify=verify_ssl,
        )

    conn = connect_with_catalog(catalog)
    if catalog is None:
        schema_names = sql_schema_names(sql)
        if schema_names:
            catalog = resolve_trino_catalog(conn, schema_names[0])
            conn.close()
            conn = connect_with_catalog(catalog)

    cursor = conn.cursor()
    cursor.execute(sql)
    rows = cursor.fetchall()
    columns = [col[0] for col in cursor.description]
    return pd.DataFrame(rows, columns=columns)


def resolve_trino_catalog(conn: Any, schema_name: str) -> str:
    cursor = conn.cursor()
    cursor.execute("SHOW CATALOGS")
    catalogs = [str(row[0]) for row in cursor.fetchall()]

    ordered_catalogs = [
        catalog for catalog in DEFAULT_CATALOG_CANDIDATES if catalog in catalogs
    ] + [catalog for catalog in catalogs if catalog not in DEFAULT_CATALOG_CANDIDATES]

    matches = []
    for catalog in ordered_catalogs:
        try:
            cursor.execute(f"SHOW SCHEMAS FROM {quote_identifier(catalog)}")
            schemas = {str(row[0]).lower() for row in cursor.fetchall()}
        except Exception:
            continue
        if schema_name.lower() in schemas:
            matches.append(catalog)

    if not matches:
        raise SystemExit(
            f"Could not find schema '{schema_name}' in any Trino catalog. "
            "Set TRINO_CATALOG manually in config/grn_export.env."
        )

    selected = matches[0]
    print(f"Resolved Trino catalog for schema '{schema_name}' to '{selected}'.")
    return selected


def _canonical_column(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    return EXPORT_COLUMN_ALIASES.get(normalized, normalized)


def _columns_from_superset(columns: Any) -> Optional[list[str]]:
    if not isinstance(columns, list):
        return None
    names = []
    for index, column in enumerate(columns):
        if isinstance(column, dict):
            name = column.get("name") or column.get("column_name") or column.get("label") or column.get("key")
        else:
            name = column
        name = str(name or "").strip() or f"column_{index + 1}"
        names.append(name)
    return names


def _single_nested_payload(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        return False
    nested = value[0]
    return any(key in nested for key in ("data", "result", "rows", "records")) and any(
        key in nested for key in ("columns", "colnames", "data", "result", "rows", "records")
    )


def _frame_from_rows(rows: list[Any], columns: Optional[list[str]] = None) -> pd.DataFrame:
    import pandas as pd

    if _single_nested_payload(rows):
        return _frame_from_payload(rows[0])
    if not rows:
        return pd.DataFrame(columns=columns or None)
    if all(isinstance(row, dict) for row in rows):
        return pd.DataFrame(rows)
    if columns:
        return pd.DataFrame(rows, columns=columns)
    return pd.DataFrame(rows)


def _frame_from_payload(payload: Any) -> pd.DataFrame:
    import pandas as pd

    if isinstance(payload, list):
        return _frame_from_rows(payload)

    if not isinstance(payload, dict):
        raise ValueError("Superset API response did not contain tabular data.")

    columns = _columns_from_superset(payload.get("columns") or payload.get("colnames"))

    for key in ("data", "rows", "records", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return _frame_from_rows(value, columns)
        if isinstance(value, dict):
            try:
                return _frame_from_payload(value)
            except ValueError:
                pass

    raise ValueError("Superset API response did not contain rows/columns.")


def validate_export_frame(frame: pd.DataFrame) -> None:
    canonical_columns = {_canonical_column(column) for column in frame.columns}
    missing = sorted(REQUIRED_EXPORT_COLUMNS - canonical_columns)
    if missing:
        columns = ", ".join(str(column) for column in frame.columns)
        raise SystemExit(
            "GRN export did not return the required columns "
            f"({', '.join(missing)}). Returned columns: {columns or 'none'}."
        )
    if "grn_date" not in canonical_columns:
        print(
            "Warning: GRN export has no grn_date/posting date column. "
            "Use sql/mseg_grn_with_mkpf_export.sql when MKPF is available."
        )


def _superset_result_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result")
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    if isinstance(result, dict):
        for key in ("data", "result"):
            rows = result.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    rows = payload.get("data")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def resolve_superset_database_id(session: Any, base_url: str, verify_ssl: bool) -> int:
    configured_id = os.getenv("SUPERSET_DATABASE_ID", "").strip()
    if configured_id:
        return int(configured_id)

    database_name = os.getenv("SUPERSET_DATABASE_NAME", "").strip()
    if not database_name:
        raise SystemExit("Set SUPERSET_DATABASE_ID or SUPERSET_DATABASE_NAME in config/grn_export.env.")

    query = {
        "filters": [{"col": "database_name", "opr": "eq", "value": database_name}],
        "page_size": 100,
    }
    responses = [
        session.get(
            f"{base_url}/api/v1/database/",
            params={"q": json.dumps(query)},
            timeout=45,
            verify=verify_ssl,
        ),
        session.get(
            f"{base_url}/api/v1/database/",
            params={"page_size": 1000},
            timeout=45,
            verify=verify_ssl,
        ),
    ]

    matches: list[dict[str, Any]] = []
    target = database_name.strip().lower()
    for response in responses:
        if not response.ok:
            continue
        for row in _superset_result_rows(response.json()):
            names = [
                str(row.get("database_name", "")).strip().lower(),
                str(row.get("database", "")).strip().lower(),
                str(row.get("name", "")).strip().lower(),
            ]
            if target in names and row.get("id") is not None:
                matches.append(row)

    unique_ids = sorted({int(row["id"]) for row in matches})
    if len(unique_ids) == 1:
        print(f"Resolved Superset database '{database_name}' to id {unique_ids[0]}.")
        return unique_ids[0]
    if len(unique_ids) > 1:
        raise SystemExit(
            f"Superset returned multiple database IDs for {database_name}: {unique_ids}. "
            "Set SUPERSET_DATABASE_ID explicitly."
        )
    raise SystemExit(
        f"Could not find Superset database named {database_name}. "
        "Check SUPERSET_DATABASE_NAME or ask the Superset admin for SUPERSET_DATABASE_ID."
    )


def export_from_superset_api(sql: str) -> pd.DataFrame:
    try:
        import requests
    except ImportError as exc:
        raise SystemExit("Install dependencies first: python -m pip install -r requirements.txt") from exc

    base_url = env_required("SUPERSET_BASE_URL").rstrip("/")
    verify_ssl = os.getenv("SUPERSET_VERIFY_SSL", "true").strip().lower() not in {"0", "false", "no"}

    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    login_payload = {
        "username": env_required("SUPERSET_USERNAME"),
        "password": env_required("SUPERSET_PASSWORD"),
        "provider": os.getenv("SUPERSET_PROVIDER", "ldap").strip() or "ldap",
        "refresh": True,
    }
    login = session.post(f"{base_url}/api/v1/security/login", json=login_payload, timeout=45, verify=verify_ssl)
    login.raise_for_status()
    token = login.json().get("access_token")
    if not token:
        raise SystemExit("Superset login succeeded but did not return an access_token.")

    session.headers.update({"Authorization": f"Bearer {token}"})
    csrf = session.get(f"{base_url}/api/v1/security/csrf_token/", timeout=45, verify=verify_ssl)
    if csrf.ok:
        csrf_token = csrf.json().get("result")
        if csrf_token:
            session.headers.update({"X-CSRFToken": csrf_token})

    database_id = resolve_superset_database_id(session, base_url, verify_ssl)
    execute_payload = {
        "database_id": database_id,
        "sql": sql,
        "schema": os.getenv("SUPERSET_SCHEMA", "").strip() or None,
        "json": True,
        "runAsync": False,
        "queryLimit": int(os.getenv("SUPERSET_QUERY_LIMIT", "50000")),
        "expand_data": True,
        "tab": "Inventory GRN Export",
    }
    response = session.post(
        f"{base_url}/api/v1/sqllab/execute/",
        json=execute_payload,
        timeout=120,
        verify=verify_ssl,
    )
    response.raise_for_status()
    return _frame_from_payload(response.json())


def main() -> None:
    parser = argparse.ArgumentParser(description="Export SAP MSEG GRN rows to a CSV consumed by the Streamlit app.")
    parser.add_argument("--env", default="config/grn_export.env", help="Path to local env config file.")
    parser.add_argument("--source", choices=["trino", "superset_api"], help="Override GRN_EXPORT_SOURCE.")
    parser.add_argument("--sql", help="Override GRN_SQL_FILE.")
    parser.add_argument("--output", help="Override GRN_OUTPUT_CSV.")
    args = parser.parse_args()

    load_env_file(project_path(args.env))
    source = args.source or os.getenv("GRN_EXPORT_SOURCE", "trino").strip().lower()
    sql_path = project_path(args.sql or os.getenv("GRN_SQL_FILE", "sql/mseg_grn_export.sql"))
    output_path = project_path(args.output or os.getenv("GRN_OUTPUT_CSV", "data/live/grn_live.csv"))
    sql = read_sql(sql_path)

    if source == "trino":
        frame = export_from_trino(sql)
    elif source == "superset_api":
        frame = export_from_superset_api(sql)
    else:
        raise SystemExit("GRN_EXPORT_SOURCE must be trino or superset_api.")

    row_count = len(frame)
    frame = frame.drop_duplicates().reset_index(drop=True)
    if len(frame) != row_count:
        print(f"Dropped {row_count - len(frame)} exact duplicate GRN export rows.")

    validate_export_frame(frame)
    write_output(frame, output_path, source)
    print(f"Exported {len(frame)} GRN rows to {output_path}")


if __name__ == "__main__":
    main()
