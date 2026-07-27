# Inventory Management Agent

Clean Streamlit starter app for collaborative inventory work.

## What is inside

- Part Inventory editable table
- Supplier Buyer Map from a saved SPOC Summary sheet copy
- Saved Google Sheet copy viewer
- Inwarding Parts GRN viewer from the live gate-entry Google Sheet
- Outwarding Parts production/BOM consumption calculator and editable servicing table
- GRN Data Quality Agent for missing receipt fields, quantity issues, discrepancies, and duplicate GRN lines
- Production Change Flagging Agent for outwarding-plan fluctuations and owner alert logs
- Inbound Coverage Agent comparing weekly outwarding demand against saved GRN receipts
- Supplier Ownership Agent mapping risky supplier/part pockets to buyer follow-up owners
- Basic stock risk flags
- CSV-backed storage in `data/`
- Local Superset/Trino exporter files kept for backend reference, not used by the app UI

## Run locally

```bash
git clone https://github.com/akshattaparia/inventory-management-agent.git
cd inventory-management-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at:

```text
http://localhost:8501
```

## Google Sheets OAuth authorization

Use this when the app needs to read private Google Sheets directly from your
Google account. This is not an app login; it is only read-only authorization for
Google Sheets data.

First-time setup:

1. Create a Google OAuth web client in Google Cloud.
2. Add this authorized redirect URI:

```text
http://localhost:8501/
```

If you run Streamlit on another port, use that exact URL instead.

3. Start the app.
4. Open **Supplier Buyer Map**, **Live Google Sheet**, or **Outwarding Parts**.
5. Open the **Google Sheets authorization** panel.
6. Paste the OAuth **Client ID** and **Client Secret**.
7. Click **Save Google OAuth settings**.
8. Click **Connect Google account for Sheets**.

The app saves the OAuth client config locally at:

```text
.streamlit/google_oauth.json
```

That file is ignored by Git and should not be pushed to GitHub.

## Google Sheet GRN inwarding

The **Inwarding Parts** page reads GRN from this Google Sheet:

```text
https://docs.google.com/spreadsheets/d/1V3ic-5Dfcz0PoX-0Z0gXdIrFIIOB_lSh-gM20RzLUKs/edit?gid=2111379627#gid=2111379627
```

The app treats the sheet column `Receipt Qty` as GRN received quantity.

Open **Inwarding Parts** and press:

```text
Create / update GRN copy
```

The app saves the current sheet copy into:

```text
data/live/grn_sheet_snapshot.csv
```

The website keeps showing this saved copy until you press **Create / update GRN copy** again. Superset GRN files may remain locally for backend checks, but the app UI does not use Superset GRN data.

## Live Google Sheets

The app can create a saved copy of your SPOC / SCM Google Sheet through Google authorization. This is better than public CSV export because the sheet can stay private.

Recommended OAuth setup on the machine running Streamlit:

1. Open **Supplier Buyer Map**, **Live Google Sheet**, or **Outwarding Parts**.
2. Open the **Google Sheets authorization** panel.
3. Save the Google OAuth Client ID and Client Secret.
4. Click **Connect Google account for Sheets**.
5. Sign in with a Google account that has Viewer access to the sheet.

Optional service-account file setup:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Paste the Google service-account JSON values into `.streamlit/secrets.toml`.

Then open the Google Sheet, click **Share**, and add the service-account `client_email` as a **Viewer**.

After that:

```bash
streamlit run app.py
```

Open **Supplier Buyer Map** and press **Create / update SPOC copy**. The app saves the current sheet into:

```text
data/live/spoc_summary_snapshot.csv
```

The website shows this saved copy by default. If the Google Sheet changes tomorrow, the website will still show the old copy until you press **Create / update SPOC copy** again.

The **Live Google Sheet** page works the same way. Press **Create / update sheet copy** to save the latest sheet into:

```text
data/live/google_sheet_snapshot.csv
```

If neither OAuth nor service-account credentials are configured, the app can only use the fallback CSV export link. For that fallback, the sheet must be shared as **Anyone with the link can view**.

## Production and BOM calculation

The **Outwarding Parts** page uses the same Google OAuth token with read-only
Sheets access. Connect a Google account that can view both the production sheet
and BOM sheet.

The calculation uses:

```text
daily production = P-VIN actual + VNA actual + Free VIN actual
part usage = daily FG production × exploded BOM quantity
```

The **Production Change Flagging Agent** compares the current outwarding
calculation against a saved baseline. It flags:

- weekly production increases or reductions,
- part-level outwarding quantity changes from the BOM explosion,
- new or removed part demand.

Use **Save current plan as baseline** once when the current plan is trusted.
After later refreshes, the agent shows active alerts for Akshat/Abhiraj and can
write them to:

```text
data/outwarding_alert_log.csv
```

The comparison baseline is stored locally at:

```text
data/outwarding_plan_baseline.csv
```

The **Inbound Coverage Agent** then compares weekly outwarding quantity against
the saved GRN sheet copy. It flags parts where same-week GRN receipt visibility
does not cover the outwarding requirement. This is a warning signal only; final
stock should still consider opening stock, physical stock, and approved
adjustments.

OAuth tokens and downloaded source caches remain local and are ignored by Git.

## Agent summary

- **GRN Data Quality Agent**: checks saved GRN rows before they affect stock.
- **Production Change Flagging Agent**: compares the current outwarding plan to a saved baseline.
- **Inbound Coverage Agent**: checks whether inwarding visibility covers outwarding pressure.
- **Supplier Ownership Agent**: turns risky supplier/part groups into buyer follow-up rows.

## Let another person open your running app

Run Streamlit on your network:

```bash
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

Then share:

```text
http://YOUR_LOCAL_IP:8501
```

This works only while your laptop is awake and Streamlit is running.

## Collaboration workflow

Use GitHub for code changes:

```bash
git checkout -b your-name/change-name
git add .
git commit -m "Describe change"
git push origin your-name/change-name
```

Then open a pull request or tell the owner before merging.

## Shared data note

The starter app saves data to local CSV files. That is fine for a first shared laptop/server demo.

The **Live Google Sheet** page reads this sheet by default:

```text
https://docs.google.com/spreadsheets/d/1V3ic-5Dfcz0PoX-0Z0gXdIrFIIOB_lSh-gM20RzLUKs/edit?gid=2111379627#gid=2111379627
```

For the OAuth method, connect a Google account that can view the sheet. For the service-account method, share the sheet with the service-account email. For the fallback CSV method, the Google Sheet must be shared as **Anyone with the link can view** or published to the web. After someone edits the sheet, press the copy/update button to pull a new snapshot into the app.

The **Inwarding Parts** page uses the same Google Sheet as the GRN source. Connect Google Sheets OAuth, then press **Create / update GRN copy** whenever you want to pull the latest sheet values into the app.

For real two-person live data entry with private data, move the tables to authenticated Google Sheets access or a database so both users always see the same source of truth safely.
