"""Smart Material Manager stable entrypoint.
Central DB is always preferred. If it is unavailable, the app opens in read-only
backup mode so budget/order/input data cannot diverge or be accidentally overwritten.
"""
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("app_snapshot.py")
source = SNAPSHOT.read_text(encoding="utf-8")

source = source.replace(
    "DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)",
    '''from db_runtime import resolve_database_url as _resolve_database_url\n_DB_RESOLUTION = _resolve_database_url(get_database_url(), st.secrets)\nDATABASE_URL = _DB_RESOLUTION.url\nUSE_POSTGRES = _DB_RESOLUTION.connected\nCENTRAL_DB_FALLBACK = not USE_POSTGRES\nCENTRAL_DB_ENDPOINT = _DB_RESOLUTION.endpoint\nCENTRAL_DB_REASON = _DB_RESOLUTION.reason''',
    1,
)

# 과거 잘못된 일괄 저장으로 모든 예산 품목이 active=0 처리된 경우에만 복구한다.
# 중앙 DB 연결 상태에서만 실행하며 행 자체를 삭제하거나 수량을 변경하지 않는다.
_recovery_anchor = 'seed()\n\n# ---------------- helpers ----------------'
_recovery_patch = '''seed()\n\n# -------- budget visibility safety recovery --------\nif USE_POSTGRES:\n    try:\n        _all_budget_n = int(read("SELECT COUNT(*) AS n FROM budget_items").iloc[0]["n"])\n        _active_budget_n = int(read("SELECT COUNT(*) AS n FROM budget_items WHERE active=1").iloc[0]["n"])\n        if _all_budget_n > 0 and _active_budget_n == 0:\n            execute("UPDATE budget_items SET active=1")\n    except Exception:\n        pass\n\n# 중앙 DB가 끊긴 경우 로컬 백업은 조회만 허용한다.\n# 예산/발주/입고/투입/상태/삭제가 백업 DB에 따로 저장되는 것을 원천 차단한다.\nif CENTRAL_DB_FALLBACK:\n    def execute(sql, params=()):\n        st.error("중앙 DB가 연결되지 않아 저장/수정/삭제를 차단했습니다. 기존 예산·발주·입고·투입 데이터 보호를 위한 조회 전용 모드입니다.")\n        st.stop()\n\n# ---------------- helpers ----------------'''
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

# DB 상태를 오해하지 않도록 명확히 표시.
source = source.replace(
    'st.caption("☁ 중앙 DB 연결" if USE_POSTGRES else "💻 로컬 SQLite 모드")',
    '''st.caption(("☁ 중앙 DB 연결" + (" · Pooler" if CENTRAL_DB_ENDPOINT == "pooler" else "")) if USE_POSTGRES else "🔒 백업 DB 조회 전용")\nif CENTRAL_DB_FALLBACK:\n    st.warning("중앙 DB가 현재 연결되지 않았습니다. 데이터 보호를 위해 예산·발주·입고·투입의 저장/수정/삭제는 모두 잠겨 있습니다. 중앙 DB가 다시 연결되면 기존 데이터로 자동 복귀합니다.")''',
    1,
)

# 한눈에 보기 확장 화면 유지.
overview_anchor = '    st.info("일반 사용자는 자재 투입수량을 입력할 수 있고, 예산/품목/입고/발주상태 수정은 관리자만 가능합니다.")'
overview_extra = overview_anchor + '''\n\n    try:\n        _extra = Path("dashboard_extra.py")\n        exec(compile(_extra.read_text(encoding="utf-8"), str(_extra), "exec"), globals(), globals())\n    except Exception:\n        pass'''
source = source.replace(overview_anchor, overview_extra, 1)

# 관리자 설정은 별도 안정화 모듈에서 관리.
admin_marker = 'elif menu == "관리자 설정":'
pos = source.find(admin_marker)
if pos >= 0:
    admin_block = '''elif menu == "관리자 설정":\n    _admin = Path("admin_settings_extra.py")\n    exec(compile(_admin.read_text(encoding="utf-8"), str(_admin), "exec"), globals(), globals())\n'''
    source = source[:pos] + admin_block

exec(compile(source, str(SNAPSHOT), "exec"), globals(), globals())
