#!/usr/bin/env python3
"""
Simple browser-use agent script for the scraper project.

This uses the browser-use module to run a simple task: open a web page using
natural language input.

To run this script, paste `python scraper-browser-use.py` in the terminal.
"""

import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Add the src directory to the path
sys.path.append(str(Path(__file__).parent / "src"))

from dotenv import load_dotenv
from src.agent.computer_use_agent import ComputerUseAgent, ComputerUseConfig

import run_guard

# Load environment variables from .env file
load_dotenv()

DB_PATH = "hockey_browser.sqlite3"
DATA_DIR = "data"
TABLE_ROW_SELECTOR = "tr.team"
PAGE_PARAM = "page_num"
START_PAGE = 1

# Fields extracted from each row, mapped to the CSS class on the page cell.
COLUMN_SELECTORS = {
    "team_name": ".name",
    "year": ".year",
    "wins": ".wins",
    "losses": ".losses",
    "ot_losses": ".ot-losses",
    "win_pct": ".pct",
    "goals_for": ".gf",
    "goals_against": ".ga",
    "diff": ".diff",
}


def to_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


async def get_cell_text(row, selector):
    cell = await row.query_selector(selector)
    if cell is None:
        return ""
    text = await cell.inner_text()
    return text.strip()


async def extract_table_from_page(page, page_num):
    """Read the hockey table rows from the page elements and return records."""
    # Wait briefly for the table rows to appear. If none show up (e.g. we went
    # past the last page), return an empty list so the caller can stop.
    try:
        await page.wait_for_selector(TABLE_ROW_SELECTOR, timeout=5000)
    except Exception:
        return []

    records = []
    rows = await page.query_selector_all(TABLE_ROW_SELECTOR)
    for row in rows:
        record = {"page_num": page_num}
        for field, selector in COLUMN_SELECTORS.items():
            record[field] = await get_cell_text(row, selector)
        record["year"] = to_int(record["year"])
        record["wins"] = to_int(record["wins"])
        record["losses"] = to_int(record["losses"])
        record["ot_losses"] = to_int(record["ot_losses"])
        record["win_pct"] = to_float(record["win_pct"])
        record["goals_for"] = to_int(record["goals_for"])
        record["goals_against"] = to_int(record["goals_against"])
        record["diff"] = to_int(record["diff"])
        records.append(record)
    return records


async def scrape_all_pages(page, base_url, start_page=START_PAGE):
    """Loop over ?page_num={page} starting from start_page until a page is empty."""
    records = []
    page_num = start_page

    while True:
        target = "{}?{}={}".format(base_url, PAGE_PARAM, page_num)
        await page.goto(target, wait_until="domcontentloaded")
        page_records = await extract_table_from_page(page, page_num)

        if not page_records:
            print("Page {}: no data, stopping.".format(page_num))
            break

        records.extend(page_records)
        print("Page {}: {} records".format(page_num, len(page_records)))
        page_num += 1

    return records


def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            source_url TEXT NOT NULL,
            record_count INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            page_num INTEGER,
            team_name TEXT,
            year INTEGER,
            wins INTEGER,
            losses INTEGER,
            ot_losses INTEGER,
            win_pct REAL,
            goals_for INTEGER,
            goals_against INTEGER,
            diff INTEGER,
            FOREIGN KEY (run_id) REFERENCES runs (id)
        )
        """
    )
    conn.commit()


def store(conn, records, source_url, started_at):
    cursor = conn.execute(
        "INSERT INTO runs (started_at, source_url, record_count) VALUES (?, ?, ?)",
        (started_at, source_url, len(records)),
    )
    run_id = cursor.lastrowid

    conn.executemany(
        """
        INSERT INTO teams (
            run_id, page_num, team_name, year, wins, losses,
            ot_losses, win_pct, goals_for, goals_against, diff
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                run_id,
                r.get("page_num"),
                r["team_name"],
                r["year"],
                r["wins"],
                r["losses"],
                r["ot_losses"],
                r["win_pct"],
                r["goals_for"],
                r["goals_against"],
                r["diff"],
            )
            for r in records
        ],
    )
    conn.commit()
    return run_id


def export_json(records, run_id, source_url, started_at):
    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {
        "run_id": run_id,
        "started_at": started_at,
        "source_url": source_url,
        "record_count": len(records),
        "teams": records,
    }
    file_path = os.path.join(DATA_DIR, "hockey_browser_run_{}.json".format(run_id))
    with open(file_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return file_path


def store_records(records, source_url):
    started_at = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        init_db(conn)
        run_id = store(conn, records, source_url, started_at)
    finally:
        conn.close()
    json_path = export_json(records, run_id, source_url, started_at)
    return run_id, json_path


async def run_browser_task(**kwargs):
    """Run a natural language browser task using the ComputerUseAgent"""

    print("Starting browser-use agent")
    print("=" * 60)

    files_path = kwargs.get("files_path", [])

    # Configuration
    config = ComputerUseConfig(
        headless=False,  # Keep browser visible to see what's happening
        window_width=1280,
        window_height=1100,
        max_steps=50,
        save_agent_history_path="./tmp/browser_use_task",
        available_file_paths=files_path,
    )

    # Create agent
    if not kwargs.get("agent"):
        agent = ComputerUseAgent(config)
        print("Initializing agent...")
        await agent.initialize()
    else:
        agent = kwargs.get("agent")
        print("Agent initialized")

    try:

        if agent.browser_context:
            print("Browser context initialized successfully")

            # Run the natural language task
            print("Running browser task...")
            tasks = kwargs.get("tasks")
            task = "/n/n".join(tasks)

            # Define a step callback to monitor progress
            async def step_callback(state, output, step_num):
                try:
                    url = getattr(state, 'url', None)
                    if url:
                        print(f"Step {step_num}: current URL: {url}")
                    else:
                        print(f"Step {step_num} completed")
                except Exception as e:
                    print(f"Step {step_num}: Error in callback - {e}")

            # Define a done callback
            def done_callback(history):
                try:
                    print(f"Task completed! Final result: {history.final_result()}")
                except Exception as e:
                    print(f"Task completed! Error getting result - {e}")

            # Run the task
            history = await agent.run_task(task, step_callback, done_callback)

            print(f"Task completed with {len(history.history)} history entries")

            # Take a screenshot after the task
            print("Taking final screenshot...")
            screenshot_path = await agent.take_screenshot("final_screenshot.png")

            if screenshot_path:
                print(f"Final screenshot saved to: {screenshot_path}")
                if os.path.exists(screenshot_path):
                    file_size = os.path.getsize(screenshot_path)
                    print(f"File size: {file_size} bytes")
            else:
                print("Failed to take final screenshot")

            return agent, history, screenshot_path
        else:
            print("Browser context not available")
            return None, None, None

    except Exception as e:
        print(f"Task failed: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None

    finally:
        print('Task completed')


async def main():
    """Main function - open a web page using natural language input"""

    # Check if OpenAI API key is set
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Warning: OPENAI_API_KEY environment variable not set!")
        print("   Set it in your .env file or environment:")
        print("   OPENAI_API_KEY=your-api-key-here")
        print("   The task will fail.\n")
        return

    agent = None

    # Natural language instructions for the task
    url = "https://www.scrapethissite.com/pages/forms/"

    if not run_guard.check_run_allowed(url, "browser-use"):
        print("Exiting without running the browser task.")
        return

    instructions = [
        f"Open the web page {url}.",
        "Wait for the page to load completely.",
        "Exit the task. Do not click on any other button/perform any action.",
    ]

    agent, _, _ = await run_browser_task(tasks=instructions, agent=agent)

    # Once on the page, use the page elements to extract and store the table data.
    # Loop over ?page_num={page} from START_PAGE until a page has no more data.
    if agent and agent.browser_context:
        print("\nExtracting table data from the page elements...")
        page = await agent.browser_context.get_current_page()
        records = await scrape_all_pages(page, url, START_PAGE)
        print("Extracted {} rows across all pages.".format(len(records)))

        if records:
            run_id, json_path = store_records(records, url)
            print(
                "Stored {} records as run #{} in {}".format(len(records), run_id, DB_PATH)
            )
            print("Exported JSON to {}".format(json_path))

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    if agent:
        await agent.close()

    print("Task completed!")


if __name__ == "__main__":
    # Run the task
    asyncio.run(main())
