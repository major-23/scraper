# run_guard.py
# Shared utility used by both the classic scraper and the browser-use scraper.
# It keeps a run log in SQLite and rate limits runs per URL host site: if the
# number of past runs for a host within a time window exceeds a limit, the
# caller should exit; otherwise the run is recorded and the caller continues.

import os
import sqlite3
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from dotenv import load_dotenv

# Load environment variables from .env file so the limit and time window can be
# configured without changing code.
load_dotenv()

RUN_DB_PATH = 'runs.sqlite3'
DEFAULT_MAX_RUNS = int(os.getenv('RUN_MAX_RUNS', '5'))
DEFAULT_WINDOW_MINUTES = int(os.getenv('RUN_WINDOW_MINUTES', '1440'))


def get_host(url):
    host = urlparse(url).netloc
    return host or url


def init_db(conn):
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host TEXT NOT NULL,
            url TEXT NOT NULL,
            source TEXT,
            run_at TEXT NOT NULL
        )
        '''
    )
    conn.commit()


def count_recent_runs(host, window_minutes, db_path=RUN_DB_PATH):
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        init_db(conn)
        row = conn.execute(
            'SELECT COUNT(*) FROM run_log WHERE host = ? AND run_at >= ?',
            (host, cutoff),
        ).fetchone()
        return row[0]
    finally:
        conn.close()


def register_run(url, source, db_path=RUN_DB_PATH):
    host = get_host(url)
    run_at = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        init_db(conn)
        conn.execute(
            'INSERT INTO run_log (host, url, source, run_at) VALUES (?, ?, ?, ?)',
            (host, url, source, run_at),
        )
        conn.commit()
    finally:
        conn.close()


def check_run_allowed(
    url,
    source,
    max_runs=None,
    window_minutes=None,
    db_path=RUN_DB_PATH,
):
    """
    Decide whether a new run is allowed for the host of url.

    Counts past runs for the host within the last window_minutes. If that count
    is greater than or equal to max_runs, the run is not allowed and the
    function returns False. Otherwise it records the run and returns True.

    When max_runs or window_minutes are not provided, the values from the
    RUN_MAX_RUNS and RUN_WINDOW_MINUTES environment variables are used.
    """
    if max_runs is None:
        max_runs = DEFAULT_MAX_RUNS
    if window_minutes is None:
        window_minutes = DEFAULT_WINDOW_MINUTES

    host = get_host(url)
    recent = count_recent_runs(host, window_minutes, db_path=db_path)

    if recent >= max_runs:
        print(
            'Run blocked for host {}: {} run(s) in the last {} minute(s) reached the limit of {}.'.format(
                host, recent, window_minutes, max_runs
            )
        )
        return False

    register_run(url, source, db_path=db_path)
    print(
        'Run allowed for host {}: {} previous run(s) in the last {} minute(s) (limit {}).'.format(
            host, recent, window_minutes, max_runs
        )
    )
    return True
