"""Smart Material Manager production-stable entrypoint.

Production rules
- Streamlit Cloud uses the central PostgreSQL DATABASE_URL only.
- SQLite is allowed only when CI_LOCAL_DB=1 for automated CI tests.
- DB migrations are additive (CREATE/ALTER) and never DROP/TRUNCATE core data.
- Orders are soft-deleted and recoverable from 관리자 설정.
- PostgreSQL connections use a bounded threaded pool to prevent connection exhaustion.
"""
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("app_snapshot.py")
source = SNAPSHOT.read_text(encoding="utf-8")

# -----------------------------------------------------------------------------
# Central DB bootstrap + bounded connection pool
# -----------------------------------------------------------------------------
old_db_boot = "DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)"
new_db_boot = r'''DATABASE_URL = get_database_url()
CI_LOCAL_DB = os.environ.get("CI_LOCAL_DB", "").strip() == "1"
USE_POSTGRES = bool(DATABASE_URL)

if not USE_POSTGRES and not CI_LOCAL_DB:
    st.error("중앙 DB 연결정보(DATABASE_URL)가 없습니다. 데이터 보호를 위해 로컬 DB로 임의 전환하지 않습니다.")
    st.info("Streamlit Cloud → Manage app → Settings → Secrets의 DATABASE_URL을 확인해주세요.")
    st.stop()

if USE_POSTGRES:
    from psycopg2.pool import ThreadedConnectionPool

_DB_POOL = None


def _get_db_pool():
    global _DB_POOL
    if not USE_POSTGRES:
        return None
    if _DB_POOL is not None:
        return _DB_POOL

    import time as _time
    last_error = None
    for attempt in range(5):
        try:
            _DB_POOL = ThreadedConnectionPool(
                1,
                5,
                dsn=DATABASE_URL,
                connect_timeout=10,
                application_name="smart-material-manager",
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=3,
            )
            return _DB_POOL
        except psycopg2.OperationalError as exc:
            last_error = exc
            if attempt < 4:
                _time.sleep(1 + attempt)
    raise last_error


class _DBSession:
    def __enter__(self):
        self.pool = _get_db_pool()
        self.conn = self.pool.getconn()
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        close_conn = False
        try:
            if exc_type is not None:
                try:
                    self.conn.rollback()
                except Exception:
                    close_conn = True
            if getattr(self.conn, "closed", 0):
                close_conn = True
        finally:
            self.pool.putconn(self.conn, close=close_conn)
        return False


def db_connect():
    return _DBSession()
'''
if old_db_boot not in source:
    raise RuntimeError("DB bootstrap marker not found")
source = source.replace(old_db_boot, new_db_boot, 1)
source = source.replace("psycopg2.connect(DATABASE_URL)", "db_connect()")

# Friendly central-DB failure instead of a raw Streamlit traceback.
init_call = "\ninit_db()\n# ---------------- 납품정보 DB 확장 ----------------"
init_safe = r'''
try:
    init_db()
except psycopg2.OperationalError:
    st.error("중앙 DB 연결에 실패했습니다. 데이터 보호를 위해 임시 로컬 저장으로 전환하지 않습니다.")
    st.info("잠시 후 다시 접속해주세요. 문제가 지속되면 Streamlit의 DATABASE_URL 연결정보를 확인해주세요.")
    st.stop()
# ---------------- 납품정보 DB 확장 ----------------'''
if init_call in source:
    source = source.replace(init_call, "\n" + init_safe, 1)

# -----------------------------------------------------------------------------
# Additive data-protection schema
# -----------------------------------------------------------------------------
persistence_schema = r'''

def ensure_persistent_schema():
    """Add safety columns/tables. Existing rows are never dropped."""
    if USE_POSTGRES:
        with db_connect() as c:
            with c.cursor() as cur:
                cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS deleted_at TEXT DEFAULT ''")
                cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS deleted_by TEXT DEFAULT ''")
                cur.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS deleted_at TEXT DEFAULT ''")
                cur.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS deleted_by TEXT DEFAULT ''")
                cur.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS order_id INTEGER")
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS order_attachments(
                        id SERIAL PRIMARY KEY,
                        order_id INTEGER NOT NULL,
                        file_name TEXT NOT NULL,
                        mime_type TEXT DEFAULT '',
                        file_size BIGINT DEFAULT 0,
                        file_data BYTEA NOT NULL,
                        created_at TEXT DEFAULT ''
                    )"""
                )
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS data_change_log(
                        id BIGSERIAL PRIMARY KEY,
                        action TEXT NOT NULL,
                        entity_type TEXT NOT NULL,
                        entity_id TEXT DEFAULT '',
                        detail TEXT DEFAULT '',
                        changed_by TEXT DEFAULT '',
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )"""
                )
            c.commit()
    else:
        with sqlite3.connect(DB) as c:
            order_cols = {row[1] for row in c.execute("PRAGMA table_info(orders)").fetchall()}
            for name in ["deleted_at", "deleted_by"]:
                if name not in order_cols:
                    c.execute(f"ALTER TABLE orders ADD COLUMN {name} TEXT DEFAULT ''")

            tx_cols = {row[1] for row in c.execute("PRAGMA table_info(transactions)").fetchall()}
            for name, definition in [
                ("deleted_at", "TEXT DEFAULT ''"),
                ("deleted_by", "TEXT DEFAULT ''"),
                ("order_id", "INTEGER"),
            ]:
                if name not in tx_cols:
                    c.execute(f"ALTER TABLE transactions ADD COLUMN {name} {definition}")

            c.execute(
                """CREATE TABLE IF NOT EXISTS order_attachments(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    file_name TEXT NOT NULL,
                    mime_type TEXT DEFAULT '',
                    file_size INTEGER DEFAULT 0,
                    file_data BLOB NOT NULL,
                    created_at TEXT DEFAULT ''
                )"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS data_change_log(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT DEFAULT '',
                    detail TEXT DEFAULT '',
                    changed_by TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            c.commit()


def log_change(action, entity_type, entity_id="", detail="", changed_by="관리자"):
    execute(
        "INSERT INTO data_change_log(action,entity_type,entity_id,detail,changed_by) VALUES(?,?,?,?,?)",
        (str(action), str(entity_type), str(entity_id), str(detail), str(changed_by)),
    )
'''
call_marker = "migrate_delivery_columns()\n\nseed()"
if call_marker not in source:
    raise RuntimeError("schema migration marker not found")
source = source.replace(
    call_marker,
    persistence_schema
    + r'''

try:
    migrate_delivery_columns()
    ensure_persistent_schema()
except psycopg2.OperationalError:
    st.error("중앙 DB 연결이 일시적으로 불안정합니다. 저장 데이터 보호를 위해 쓰기 기능을 중단했습니다.")
    st.stop()

seed()''',
    1,
)

# Soft-deleted records do not affect active dashboards/totals.
source = source.replace(
    "LEFT JOIN transactions t ON b.id=t.item_id",
    "LEFT JOIN transactions t ON b.id=t.item_id AND COALESCE(t.deleted_at,'')=''",
)
source = source.replace(
    "SELECT * FROM orders ORDER BY id DESC",
    "SELECT * FROM orders WHERE COALESCE(deleted_at,'')='' ORDER BY id DESC",
)
source = source.replace(
    "WHERE o.order_complete=0",
    "WHERE o.order_complete=0 AND COALESCE(o.deleted_at,'')=''",
)

# -----------------------------------------------------------------------------
# Stable page routing
# -----------------------------------------------------------------------------
source = source.replace(
    'runpy.run_path("pages/stone_impl.py", run_name="__main__")',
    'runpy.run_path("pages/4_Stone.py", run_name="__main__")',
)
source = source.replace(
    'runpy.run_path("pages/stone_impl_v2.py", run_name="__main__")',
    'runpy.run_path("pages/4_Stone.py", run_name="__main__")',
)

source = source.replace(
    'st.caption("☁ 중앙 DB 연결" if USE_POSTGRES else "💻 로컬 SQLite 모드")',
    'st.caption("☁ 중앙 DB 연결 · 데이터 영구저장" if USE_POSTGRES else "🧪 CI 테스트 DB")',
    1,
)

# Administrator settings are isolated from the main app so future admin changes do
# not rewrite/truncate the rest of the application.
admin_marker = 'elif menu == "관리자 설정":'
pos = source.find(admin_marker)
if pos >= 0:
    admin_block = r'''elif menu == "관리자 설정":
    admin_file = Path("pages/admin_settings.py")
    exec(compile(admin_file.read_text(encoding="utf-8"), str(admin_file), "exec"), globals(), globals())
'''
    source = source[:pos] + admin_block

exec(compile(source, str(SNAPSHOT), "exec"), globals(), globals())
