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
