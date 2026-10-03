# scraper.py
# Scrapes the Hockey Teams table from scrapethissite.com across all pages,
# stores the structured data in SQLite (one record set per run) and also
# exports the run to a JSON file.
# To run this script, paste `python scraper.py` in the terminal.

import json
import os
import sqlite3
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from requests.exceptions import SSLError
from urllib3.exceptions import InsecureRequestWarning

import run_guard

BASE_URL = 'https://www.scrapethissite.com/pages/forms/'
PAGE_PARAM = 'page_num'
DB_PATH = 'hockey.sqlite3'
DATA_DIR = 'data'
REQUEST_DELAY = 0.5
START_PAGE = 1

# Fields scraped from each row, mapped to the <td> class used on the page.
COLUMN_CLASSES = {
    'team_name': 'name',
    'year': 'year',
    'wins': 'wins',
    'losses': 'losses',
    'ot_losses': 'ot-losses',
    'win_pct': 'pct',
    'goals_for': 'gf',
    'goals_against': 'ga',
    'diff': 'diff',
}


def get_cell_text(row, css_class):
    cell = row.find('td', class_=css_class)
    if cell is None:
        return ''
    return cell.get_text(strip=True)


def to_int(value):
    if value is None or value == '':
        return None
    try:
        return int(value)
    except ValueError:
        return None


def to_float(value):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except ValueError:
        return None


def fetch(url, params=None):
    # The network may sit behind a proxy with a self-signed certificate, so
    # fall back to an unverified request if the verified one fails.
    try:
        return requests.get(url, params=params, timeout=30)
    except SSLError:
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        return requests.get(url, params=params, timeout=30, verify=False)


def parse_rows(soup, page_num):
    rows = []
    for row in soup.find_all('tr', class_='team'):
        record = {'page_num': page_num}
        for field, css_class in COLUMN_CLASSES.items():
            record[field] = get_cell_text(row, css_class)
        record['year'] = to_int(record['year'])
        record['wins'] = to_int(record['wins'])
        record['losses'] = to_int(record['losses'])
        record['ot_losses'] = to_int(record['ot_losses'])
        record['win_pct'] = to_float(record['win_pct'])
        record['goals_for'] = to_int(record['goals_for'])
        record['goals_against'] = to_int(record['goals_against'])
        record['diff'] = to_int(record['diff'])
        rows.append(record)
    return rows


def scrape(start_page=START_PAGE):
    records = []
    page_num = start_page

    while True:
        response = fetch(BASE_URL, params={PAGE_PARAM: page_num})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        page_records = parse_rows(soup, page_num)

        if not page_records:
            print('Page {}: no data, stopping.'.format(page_num))
            break

        records.extend(page_records)
        print('Page {}: {} records'.format(page_num, len(page_records)))

        page_num += 1
        time.sleep(REQUEST_DELAY)

    return records


def init_db(conn):
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            source_url TEXT NOT NULL,
            record_count INTEGER NOT NULL
        )
        '''
    )
    conn.execute(
        '''
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
        '''
    )
    conn.commit()


def store(conn, records, started_at):
    cursor = conn.execute(
        'INSERT INTO runs (started_at, source_url, record_count) VALUES (?, ?, ?)',
        (started_at, BASE_URL, len(records)),
    )
    run_id = cursor.lastrowid

    conn.executemany(
        '''
        INSERT INTO teams (
            run_id, page_num, team_name, year, wins, losses,
            ot_losses, win_pct, goals_for, goals_against, diff
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        [
            (
                run_id,
                r['page_num'],
                r['team_name'],
                r['year'],
                r['wins'],
                r['losses'],
                r['ot_losses'],
                r['win_pct'],
                r['goals_for'],
                r['goals_against'],
                r['diff'],
            )
            for r in records
        ],
    )
    conn.commit()
    return run_id


def export_json(records, run_id, started_at):
    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {
        'run_id': run_id,
        'started_at': started_at,
        'source_url': BASE_URL,
        'record_count': len(records),
        'teams': records,
    }
    file_name = 'hockey_run_{}.json'.format(run_id)
    file_path = os.path.join(DATA_DIR, file_name)
    with open(file_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2)
    return file_path


def main():
    if not run_guard.check_run_allowed(BASE_URL, 'static-scraper'):
        print('Exiting without scraping.')
        return

    started_at = datetime.now(timezone.utc).isoformat()
    records = scrape(START_PAGE)

    conn = sqlite3.connect(DB_PATH)
    try:
        init_db(conn)
        run_id = store(conn, records, started_at)
    finally:
        conn.close()

    json_path = export_json(records, run_id, started_at)

    print('Stored {} records as run #{} in {}'.format(len(records), run_id, DB_PATH))
    print('Exported JSON to {}'.format(json_path))


if __name__ == '__main__':
    main()
