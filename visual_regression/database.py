import os
from pathlib import Path
from typing import Any

def get_store(db_path: Path) -> Any:
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PATH")
    if db_url and db_url.startswith("sqlite:///"):
        # Strip the sqlite:/// prefix and use the remainder as a file path
        sqlite_path = Path(db_url[len("sqlite:///"):])
        from .sqlite_store import SqliteStore
        return SqliteStore(sqlite_path)
    if db_url and (db_url.startswith("postgresql://") or db_url.startswith("postgres://")):
        try:
            import time
            from .postgres_store import PostgresStore
            
            max_retries = 5
            for attempt in range(1, max_retries + 1):
                try:
                    return PostgresStore(db_url)
                except Exception as e:
                    # Check if psycopg2 is available and if it is an operational connection error
                    try:
                        import psycopg2
                        is_db_err = isinstance(e, psycopg2.OperationalError)
                    except ImportError:
                        is_db_err = True
                        
                    if not is_db_err or attempt == max_retries:
                        raise e
                    
                    backoff = attempt * 2.0
                    print(
                        f"[Database] PostgreSQL connection attempt {attempt} failed: {e}. "
                        f"Retrying in {backoff} seconds...",
                        flush=True
                    )
                    time.sleep(backoff)
        except ImportError:
            import sys
            print(
                "WARNING: psycopg2-binary not installed but DATABASE_URL is set. "
                "Falling back to SQLite. Run: pip install psycopg2-binary",
                flush=True,
            )
            print(
                "\n⚠️  [DATABASE ERROR] PostgreSQL URL is configured, but the required database driver 'psycopg2' is not installed.\n"
                "   Please run: pip install psycopg2-binary\n"
                "   Falling back to SQLite temporarily to prevent server crash.\n",
                file=sys.stderr,
                flush=True,
            )
            from .sqlite_store import SqliteStore
            return SqliteStore(db_path)
    else:
        from .sqlite_store import SqliteStore
        return SqliteStore(db_path)
