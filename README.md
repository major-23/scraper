# scraper

Two approaches for scraping web pages.
First is the classic response hook interpreter.
The second one is something that I have presonally created production solutions (since there were some restrictions on the APIs and responses that come up) that uses an open-source software bowser-use, a way to interact with web pages using natural language commands and LLMs. 

## 1. Static scraper (requests + BeautifulSoup)

Fetches pages over HTTP and parses the HTML directly. Fast and cheap, best for
structured pages with a stable layout.

- `scraper-basic.py` - minimal example that fetches a page and prints the HTML.
- `scraper.py` - scrapes the Hockey Teams table across all pages, stores each run
  in SQLite (`hockey.sqlite3`) and exports a JSON file per run to `data/`.

```powershell
.\venv\Scripts\python.exe scraper.py
```

## 2. Browser-use agent (LLM + Playwright)

Drives a real Chromium browser using natural language instructions, powered by
the browser-use module (under `src/`).
Best for dynamic pages, forms, logins, and flows that are hard to script by hand.

- `scraper-browser-use.py` - opens a web page from a natural language task.
- Requires `OPENAI_API_KEY` in a `.env` file (see `.env.example`).

```powershell
.\venv\Scripts\python.exe scraper-browser-use.py
```

## Setup

```powershell
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m playwright install chromium
```

Note: Python 3.11 is required for the browser-use stack.

### The scraper should be rate limited per page - don't overload the server:
Added a helper function that checks runs in last n minutes and exits if the run count above allowed limit. Can be set from RUN_MAX_RUNS
RUN_WINDOW_MINUTES in .env

### Consider what should happen if the website has changed its format and the scraper fails to pull data. What should the system do?
There should be some alert system in case some required fields in response are missing, can use an LLM judge as well. 
This can be solved to some extent where we use browser-use approach to navigate pages and use LLM to scrape data from entire content.

### Consider what happens if the data ingestion fails for some reason (e.g., the database is down)
Couple of things that can be done:
- Add a retry mechannism before raising alerts
- Store a local dump on the disk before saving the entries in database and have an ingestion mechanism based on that.

### If the scraper crashes halfway through scraping, we should be able to resume from the partial state of the failed session
Have checkpoints per page and persist the data per page and check the last successful checkpoints for the runs. The approaches implemented have input parameter of START_PAGE (defaults to 1) that can start the next from midway from a checkpoint.

### It would be good to check that the data seems ok before we load it into the database and start serving it to customers. How can we perform sanity checks on the scraped data?
Depends a lot on the data. For e.g. wins/losses must be >=0, win pct must be b/w 0-1 and stuff like that. So need to be data-based verifiers for that.

### The data on the sample website is currently in a pretty easy format to ingest, but what if it wasn't? What if we have PDFs or data that requires some pre-processing? How would that affect your scraper architecture?
The 2nd approach with browser-use can download such data and use LLM to extract.

### How can we monitor the health of scrapers?
- Have run level tracking of failures
- Keep track of run-time to ensure there is no part of scraper stuck for a long time
- Data level sanity checks and verifiers