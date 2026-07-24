# Inventory Management Agent

Clean Streamlit starter app for collaborative inventory work.

## What is inside

- Part Inventory editable table
- Live Google Sheet viewer
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

For the simple live-read method to work, the Google Sheet must be shared as **Anyone with the link can view** or published to the web. After someone edits the sheet, refresh the Streamlit page or press **Reload sheet**.

For real two-person live data entry with private data, move the tables to authenticated Google Sheets access or a database so both users always see the same source of truth safely.
