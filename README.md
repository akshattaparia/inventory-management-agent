# Inventory Management Agent

Clean Streamlit starter app for collaborative inventory work.

## What is inside

- Part Inventory editable table
- Supplier Buyer Map from a saved SPOC Summary sheet copy
- Saved Google Sheet copy viewer
- Inwarding Parts live Superset GRN viewer
- Outwarding Parts editable table
- Basic stock risk flags
- CSV-backed storage in `data/`
- Local Superset/Trino GRN exporter in `scripts/scheduled_grn_export.py`

## Run locally

```bash
git clone https://github.com/akshattaparia/inventory-management-agent.git
cd inventory-management-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Live Superset GRN inwarding

The **Inwarding Parts** page reads only this new app's live GRN export:

```text
data/live/grn_live.csv
```

It does not read the previous app and it does not fall back to sample data.

To configure it on your machine:

```bash
cp config/grn_export.env.example config/grn_export.env
```

Then fill `config/grn_export.env` with the Superset/Trino access details. Keep this file private; it is ignored by Git.

To refresh once from the terminal:

```bash
python scripts/scheduled_grn_export.py
```

You can also press **Run live export now** inside the **Inwarding Parts** page.

The exporter writes:

```text
data/live/grn_live.csv
data/live/grn_live.json
```

Those generated files are also ignored by Git. Each laptop/server should generate its own current live file from Superset.

## Live Google Sheets API

The app can create a saved copy of your SPOC / SCM Google Sheet through the Google Sheets API. This is better than public CSV export because the sheet can stay private.

Setup on the machine running Streamlit:

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

If API credentials are not configured, the app can only use the fallback CSV export link. For that fallback, the sheet must be shared as **Anyone with the link can view**.

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

For the API method, share the sheet with the service-account email. For the fallback CSV method, the Google Sheet must be shared as **Anyone with the link can view** or published to the web. After someone edits the sheet, press the copy/update button to pull a new snapshot into the app.

The **Inwarding Parts** page is different: it reads current GRN rows from the live Superset export. If Abhiraj runs the app locally, he must create his own local `config/grn_export.env`. If only one shared server runs the app, configure Superset once on that server.

For real two-person live data entry with private data, move the tables to authenticated Google Sheets access or a database so both users always see the same source of truth safely.
