"""Smart Material Manager stable entrypoint.
Central DB is always preferred. If it is unavailable, the app opens in read-only
backup mode so budget/order/input data cannot diverge or be accidentally overwritten.
"""
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("app_snapshot.py")
source = SNAPSHOT.read_text(encoding="utf-8")

# Ensure every PostgreSQL connection opened by the historical snapshot is physically
# closed. psycopg2's connection context manager commits/rolls back but does not close.
# Repeated Streamlit reruns therefore used to leak connections and eventually exhaust
# the central DB/pooler.
source = source.replace(
    "import io\nimport os\n",
    "import io\nimport os\nfrom contextlib import closing\n",
    1,
)
source = source.replace(
    "with psycopg2.connect(DATABASE_URL) as c:",
    "with closing(psycopg2.connect(DATABASE_URL, connect_timeout=7, application_name='smart-material-manager')) as c:",
)

source = source.replace(
    "DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)",
    '''from db_runtime import resolve_database_url as _resolve_database_url\n_DB_RESOLUTION = _resolve_database_url(get_database_url(), st.secrets)\nDATABASE_URL = _DB_RESOLUTION.url\nUSE_POSTGRES = _DB_RESOLUTION.connected\nCENTRAL_DB_FALLBACK = not USE_POSTGRES\nCENTRAL_DB_ENDPOINT = _DB_RESOLUTION.endpoint\nCENTRAL_DB_REASON = _DB_RESOLUTION.reason''',
    1,
)

# Ensure overview/supply fields exist on the same central DB.
_migration_anchor = 'migrate_delivery_columns()\n\nseed()'
_migration_patch = '''migrate_delivery_columns()\n\ndef migrate_supply_columns():\n    if USE_POSTGRES:\n        with closing(psycopg2.connect(DATABASE_URL, connect_timeout=7, application_name="smart-material-manager")) as c:\n            with c.cursor() as cur:\n                cur.execute("ALTER TABLE budget_items ADD COLUMN IF NOT EXISTS planned_delivery_date TEXT DEFAULT ''")\n                cur.execute("ALTER TABLE budget_items ADD COLUMN IF NOT EXISTS storage_location TEXT DEFAULT ''")\n                cur.execute("""CREATE TABLE IF NOT EXISTS material_documents(\n                    id SERIAL PRIMARY KEY, item_id INTEGER, file_name TEXT NOT NULL,\n                    upload_date TEXT NOT NULL, extracted_text TEXT DEFAULT '',\n                    applied_qty DOUBLE PRECISION DEFAULT 0, status TEXT DEFAULT '검토대기'\n                )""")\n            c.commit()\n    else:\n        with sqlite3.connect(DB) as c:\n            cols = {r[1] for r in c.execute("PRAGMA table_info(budget_items)").fetchall()}\n            if "planned_delivery_date" not in cols:\n                c.execute("ALTER TABLE budget_items ADD COLUMN planned_delivery_date TEXT DEFAULT ''")\n            if "storage_location" not in cols:\n                c.execute("ALTER TABLE budget_items ADD COLUMN storage_location TEXT DEFAULT ''")\n            c.execute("""CREATE TABLE IF NOT EXISTS material_documents(\n                id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, file_name TEXT NOT NULL,\n                upload_date TEXT NOT NULL, extracted_text TEXT DEFAULT '',\n                applied_qty REAL DEFAULT 0, status TEXT DEFAULT '검토대기'\n            )""")\n            c.commit()\n\nmigrate_supply_columns()\n\nseed()'''
source = source.replace(_migration_anchor, _migration_patch, 1)

# 과거 잘못된 일괄 저장으로 예산 품목이 비활성화된 경우에만 안전 복구한다.
# 중앙 DB의 수량 자체는 절대 덮어쓰지 않고, 과거 저장된 budget_qty를 그대로 사용한다.
_recovery_anchor = 'seed()\n\n# ---------------- helpers ----------------'
_recovery_patch = '''seed()\n\n# -------- historical budget visibility safety recovery --------\nif USE_POSTGRES:\n    try:\n        _all_budget_n = int(read("SELECT COUNT(*) AS n FROM budget_items").iloc[0]["n"])\n        _active_budget_n = int(read("SELECT COUNT(*) AS n FROM budget_items WHERE active=1").iloc[0]["n"])\n        _active_positive_n = int(read("SELECT COUNT(*) AS n FROM budget_items WHERE active=1 AND COALESCE(budget_qty,0)>0").iloc[0]["n"])\n        _inactive_positive_n = int(read("SELECT COUNT(*) AS n FROM budget_items WHERE active=0 AND COALESCE(budget_qty,0)>0").iloc[0]["n"])\n        if _all_budget_n > 0 and _active_budget_n == 0:\n            execute("UPDATE budget_items SET active=1")\n        elif _active_positive_n == 0 and _inactive_positive_n > 0:\n            execute("UPDATE budget_items SET active=1 WHERE COALESCE(budget_qty,0)>0")\n    except Exception:\n        pass\n\n# 중앙 DB가 끊긴 경우 로컬 백업은 조회만 허용한다.\n# 예산/발주/입고/투입/상태/삭제가 백업 DB에 따로 저장되는 것을 원천 차단한다.\nif CENTRAL_DB_FALLBACK:\n    def execute(sql, params=()):\n        st.error("중앙 DB가 연결되지 않아 저장/수정/삭제를 차단했습니다. 기존 예산·발주·입고·투입 데이터 보호를 위한 조회 전용 모드입니다.")\n        st.stop()\n\n# ---------------- helpers ----------------'''
source = source.replace(_recovery_anchor, _recovery_patch, 1)

# 석재는 기능이 복구된 안정화 래퍼를 통해 실행.
source = source.replace(
    'runpy.run_path("pages/stone_impl.py", run_name="__main__")',
    'runpy.run_path("pages/4_Stone.py", run_name="__main__")',
)
source = source.replace(
    'runpy.run_path("pages/stone_impl_v2.py", run_name="__main__")',
    'runpy.run_path("pages/4_Stone.py", run_name="__main__")',
)

# DB status is explicit and includes only a safe reason, never credentials/raw errors.
source = source.replace(
    'st.caption("☁ 중앙 DB 연결" if USE_POSTGRES else "💻 로컬 SQLite 모드")',
    '''st.caption(("☁ 중앙 DB 연결" + (" · Pooler" if str(CENTRAL_DB_ENDPOINT).startswith("pooler") else "")) if USE_POSTGRES else "🔒 백업 DB 조회 전용")\nif CENTRAL_DB_FALLBACK:\n    st.warning(f"중앙 DB가 현재 연결되지 않았습니다 ({CENTRAL_DB_REASON}). 데이터 보호를 위해 저장/수정/삭제는 잠겨 있습니다. 연결이 회복되면 자동으로 기존 중앙 DB 데이터로 복귀합니다.")''',
    1,
)

# 한눈에 보기 확장 화면. 오류를 숨기지 않고 사용자가 기능 누락으로 오해하지 않도록
# 안전한 안내를 표시한다.
overview_anchor = '    st.info("일반 사용자는 자재 투입수량을 입력할 수 있고, 예산/품목/입고/발주상태 수정은 관리자만 가능합니다.")'
overview_extra = overview_anchor + '''\n\n    try:\n        _extra = Path("dashboard_extra.py")\n        exec(compile(_extra.read_text(encoding="utf-8"), str(_extra), "exec"), globals(), globals())\n    except Exception as _overview_exc:\n        st.warning("한눈에 보기 확장정보를 불러오는 중 일부 항목을 표시하지 못했습니다. 기본 자재 현황은 정상 사용할 수 있습니다.")'''
source = source.replace(overview_anchor, overview_extra, 1)

# 관리자 설정은 별도 안정화 모듈에서 관리.
admin_marker = 'elif menu == "관리자 설정":'
pos = source.find(admin_marker)
if pos >= 0:
    admin_block = '''elif menu == "관리자 설정":\n    _admin = Path("admin_settings_extra.py")\n    exec(compile(_admin.read_text(encoding="utf-8"), str(_admin), "exec"), globals(), globals())\n'''
    source = source[:pos] + admin_block

exec(compile(source, str(SNAPSHOT), "exec"), globals(), globals())
