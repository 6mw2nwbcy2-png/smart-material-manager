"""Stable stone entrypoint.
Runs the original feature-rich stone UI, but swaps its PostgreSQL-only bootstrap for
SQLite-compatible storage while the central DB connection is being stabilized.
"""
from pathlib import Path

SRC = Path(__file__).with_name("stone_impl_v2.py")
source = SRC.read_text(encoding="utf-8")

start = source.index("DATABASE_URL = get_database_url()")
end = source.index("def seed_stone_items():")

sqlite_bootstrap = '''DATABASE_URL = ""
USE_POSTGRES = False


def _pg_sql(sql):
    return sql


def execute(sql, params=()):
    with sqlite3.connect(DB) as c:
        c.execute(sql, params)
        c.commit()


def read(sql, params=()):
    with sqlite3.connect(DB) as c:
        return pd.read_sql_query(sql, c, params=params)


def ensure_schema():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS budget_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            vendor TEXT DEFAULT '',
            item_name TEXT NOT NULL,
            spec TEXT DEFAULT '',
            unit TEXT NOT NULL,
            budget_qty REAL DEFAULT 0,
            tile_type TEXT DEFAULT '',
            application_type TEXT DEFAULT '',
            default_destination TEXT DEFAULT '',
            active INTEGER DEFAULT 1
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_date TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            tx_type TEXT NOT NULL,
            qty REAL NOT NULL,
            destination TEXT DEFAULT '',
            note TEXT DEFAULT '',
            input_user TEXT DEFAULT ''
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT UNIQUE,
            category TEXT NOT NULL,
            vendor TEXT DEFAULT '',
            order_date TEXT NOT NULL,
            partner_confirm INTEGER DEFAULT 0,
            internal_approval INTEGER DEFAULT 0,
            order_complete INTEGER DEFAULT 0,
            note TEXT DEFAULT ''
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS order_lines(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            qty REAL NOT NULL,
            requested_delivery_date TEXT DEFAULT '',
            destination TEXT DEFAULT ''
        )""")
        existing = {row[1] for row in c.execute("PRAGMA table_info(order_lines)").fetchall()}
        for name in ["delivery_recipient", "delivery_phone", "delivery_address", "storage_location"]:
            if name not in existing:
                c.execute(f"ALTER TABLE order_lines ADD COLUMN {name} TEXT DEFAULT ''")
        c.execute("""CREATE TABLE IF NOT EXISTS order_attachments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            mime_type TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            file_data BLOB NOT NULL,
            created_at TEXT DEFAULT ''
        )""")
        c.commit()

'''

source = source[:start] + sqlite_bootstrap + source[end:]
source = source.replace('st.caption("☁ 중앙 DB 연결")', 'st.caption("🛡 안정화 모드 · 원래 석재 기능 복구")', 1)
exec(compile(source, str(SRC), "exec"), globals(), globals())
