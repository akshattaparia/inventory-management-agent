# Inventory Management Agent

Clean Streamlit starter app for collaborative inventory work.

## What is inside

- Part Inventory editable table
- Embedded live Google Sheet link
- Inwarding Parts editable table
- Outwarding Parts editable table
- Basic stock risk flags
- CSV-backed storage in `data/`

## Run locally

```bash
git clone https://github.com/akshattaparia/inventory-management-agent.git
cd inventory-management-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

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

## Linked Google Sheet

Open **Linked Google Sheet**, paste a standard Google Sheets URL, and click
**Add link and display**. The URL is stored locally and the live sheet is embedded
inside the Streamlit page.

The embedded sheet uses the Google account signed into the viewer's browser.
Google continues to control whether that person can view or edit it. An
**Open in new tab** button is provided if Google does not allow the sheet to render
inside an iframe.

## Read-only production and BOM sources

The **Outwarding Parts** page can connect to the private daily-production and BOM
Google Sheets using read-only OAuth. To configure it:

1. Enable the Google Sheets API in a Google Cloud project.
2. Configure the OAuth consent screen and add the intended Google account as a
   test user while the OAuth app is in testing.
3. Create an OAuth client of type **Web application**.
4. Add `http://localhost:8501/` as an authorized redirect URI.
5. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and insert
   the OAuth client ID and client secret.
6. Restart Streamlit, open **Outwarding Parts**, and connect a Google account that
   can view both sheets.

The app requests only the `spreadsheets.readonly` scope. Source previews are cached
locally in `data/` and are ignored by Git. The original Google Sheets cannot be
modified through this connection.

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

For real two-person live data entry, move the tables to Google Sheets or a database so both users always see the same source of truth.
