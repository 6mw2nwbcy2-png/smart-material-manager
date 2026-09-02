"""Smart Material Manager production entrypoint.

Production policy:
- Central PostgreSQL is the only writable database.
- No production SQLite fallback is allowed, preventing split/duplicate data.
- Saved budget master rows are append-only. Only planned delivery date/storage location
  metadata may change after save.
- Saved material-use transactions (tx_type='투입') are immutable at PostgreSQL trigger level.
"""
# Redeploy trigger: 2026-09-02 public access recovery. No application logic changed.
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("app_snapshot.py")
source = SNAPSHOT.read_text(encoding="utf-8")

# -----------------------------------------------------------------------------
# Central DB resolution and connection lifecycle
# -----------------------------------------------------------------------------
source = source.replace(
    "import io\nimport os\n",
    "import io\nimport os\nfrom contextlib import closing\n",
    1,
)

_db_anchor = "DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)"
_db_patch = r'''from db_runtime import resolve_database_url as _resolve_database_url
_DB_RESOLUTION = _resolve_database_url(get_database_url(), st.secrets)
DATABASE_URL = _DB_RESOLUTION.url
USE_POSTGRES = bool(_DB_RESOLUTION.connected)
CENTRAL_DB_FALLBACK = not USE_POSTGRES
CENTRAL_DB_ENDPOINT = _DB_RESOLUTION.endpoint
CENTRAL_DB_REASON = _DB_RESOLUTION.reason
_CI_ALLOW_SQLITE = os.environ.get("CI_ALLOW_SQLITE", "") == "1"

if not USE_POSTGRES and not _CI_ALLOW_SQLITE:
    st.error("중앙 DB 연결에 실패했습니다. 데이터 보호를 위해 로컬 DB 저장은 사용하지 않습니다.")
    st.caption(f"연결 상태: {CENTRAL_DB_REASON or '연결 불가'}")
    st.stop()
'''
if _db_anchor not in source:
    raise RuntimeError("central DB bootstrap marker not found")
source = source.replace(_db_anchor, _db_patch, 1)

# Always physically close central PostgreSQL connections on Streamlit reruns.
source = source.replace(
    "with psycopg2.connect(DATABASE_URL) as c:",
    "with closing(psycopg2.connect(DATABASE_URL, connect_timeout=7, application_name='smart-material-manager')) as c:",
)

# -----------------------------------------------------------------------------
# Operational metadata schema + database-level immutable-data protection
# -----------------------------------------------------------------------------
_migration_anchor = "migrate_delivery_columns()\n\nseed()"
_migration_patch = r'''migrate_delivery_columns()

def migrate_supply_columns():
    if USE_POSTGRES:
        with closing(psycopg2.connect(DATABASE_URL, connect_timeout=7, application_name="smart-material-manager")) as c:
            with c.cursor() as cur:
                cur.execute("ALTER TABLE budget_items ADD COLUMN IF NOT EXISTS planned_delivery_date TEXT DEFAULT ''")
                cur.execute("ALTER TABLE budget_items ADD COLUMN IF NOT EXISTS storage_location TEXT DEFAULT ''")
                cur.execute("""CREATE TABLE IF NOT EXISTS material_documents(
                    id SERIAL PRIMARY KEY, item_id INTEGER, file_name TEXT NOT NULL,
                    upload_date TEXT NOT NULL, extracted_text TEXT DEFAULT '',
                    applied_qty DOUBLE PRECISION DEFAULT 0, status TEXT DEFAULT '검토대기'
                )""")
            c.commit()
    elif _CI_ALLOW_SQLITE:
        with sqlite3.connect(DB) as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(budget_items)").fetchall()}
            if "planned_delivery_date" not in cols:
                c.execute("ALTER TABLE budget_items ADD COLUMN planned_delivery_date TEXT DEFAULT ''")
            if "storage_location" not in cols:
                c.execute("ALTER TABLE budget_items ADD COLUMN storage_location TEXT DEFAULT ''")
            c.execute("""CREATE TABLE IF NOT EXISTS material_documents(
                id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, file_name TEXT NOT NULL,
                upload_date TEXT NOT NULL, extracted_text TEXT DEFAULT '',
                applied_qty REAL DEFAULT 0, status TEXT DEFAULT '검토대기'
            )""")
            c.commit()

migrate_supply_columns()

seed()

if USE_POSTGRES:
    from data_protection import apply_central_db_protection
    _protect_ok, _protect_message = apply_central_db_protection(DATABASE_URL)
    if not _protect_ok:
        st.error("중앙 DB 데이터 보호장치를 적용하지 못해 저장 기능을 중지했습니다.")
        st.caption(_protect_message)
        st.stop()
'''
if _migration_anchor not in source:
    raise RuntimeError("supply migration marker not found")
source = source.replace(_migration_anchor, _migration_patch, 1)

# -----------------------------------------------------------------------------
# Stone uses the feature-rich central DB wrapper.
# -----------------------------------------------------------------------------
source = source.replace(
    'runpy.run_path("pages/stone_impl.py", run_name="__main__")',
    'runpy.run_path("pages/4_Stone.py", run_name="__main__")',
)
source = source.replace(
    'runpy.run_path("pages/stone_impl_v2.py", run_name="__main__")',
    'runpy.run_path("pages/4_Stone.py", run_name="__main__")',
)

# -----------------------------------------------------------------------------
# Explicit DB status. Production never says/uses local DB.
# -----------------------------------------------------------------------------
source = source.replace(
    'st.caption("☁ 중앙 DB 연결" if USE_POSTGRES else "💻 로컬 SQLite 모드")',
    'st.caption(("☁ 중앙 DB 연결" + (" · Pooler" if str(CENTRAL_DB_ENDPOINT).startswith("pooler") else "")) if USE_POSTGRES else "🧪 CI 로컬 테스트 모드")',
    1,
)

# -----------------------------------------------------------------------------
# Enhanced overview: delivery schedule, storage, budget-vs-received charts, contacts.
# -----------------------------------------------------------------------------
_overview_anchor = '    st.info("일반 사용자는 자재 투입수량을 입력할 수 있고, 예산/품목/입고/발주상태 수정은 관리자만 가능합니다.")'
if _overview_anchor in source:
    source = source.replace(
        _overview_anchor,
        _overview_anchor + '''\n\n    _extra = Path("dashboard_extra.py")\n    exec(compile(_extra.read_text(encoding="utf-8"), str(_extra), "exec"), globals(), globals())''',
        1,
    )

# -----------------------------------------------------------------------------
# Admin screen: existing budget/use data are read-only; new budgets append only;
# saved orders retain status-edit/delete controls.
# -----------------------------------------------------------------------------
_admin_marker = 'elif menu == "관리자 설정":'
_admin_pos = source.find(_admin_marker)
if _admin_pos < 0:
    raise RuntimeError("admin marker not found")
source = source[:_admin_pos] + '''elif menu == "관리자 설정":
    _admin = Path("admin_settings_extra.py")
    exec(compile(_admin.read_text(encoding="utf-8"), str(_admin), "exec"), globals(), globals())
'''

exec(compile(source, str(SNAPSHOT), "exec"), globals(), globals())
