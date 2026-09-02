"""Smart Material Manager stable entrypoint.
Central DB is preferred. If it is unavailable, the app falls back immediately to the
backup DB without exposing raw driver errors or blocking the UI.
"""
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("app_snapshot.py")
source = SNAPSHOT.read_text(encoding="utf-8")

source = source.replace(
    "DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)",
    '''from db_runtime import resolve_database_url as _resolve_database_url\n_DB_RESOLUTION = _resolve_database_url(get_database_url(), st.secrets)\nDATABASE_URL = _DB_RESOLUTION.url\nUSE_POSTGRES = _DB_RESOLUTION.connected\nCENTRAL_DB_FALLBACK = not USE_POSTGRES\nCENTRAL_DB_ENDPOINT = _DB_RESOLUTION.endpoint''',
    1,
)

# 중앙 DB/백업 DB 어느 쪽이든, 과거 잘못된 일괄 저장으로 모든 예산 품목이
# active=0 처리된 경우 앱 시작 시 즉시 다시 표시한다. 실제 행은 삭제하지 않는다.
_recovery_anchor = 'seed()\n\n# ---------------- helpers ----------------'
_recovery_patch = '''seed()\n\n# -------- budget visibility safety recovery --------\ntry:\n    _all_budget_n = int(read("SELECT COUNT(*) AS n FROM budget_items").iloc[0]["n"])\n    _active_budget_n = int(read("SELECT COUNT(*) AS n FROM budget_items WHERE active=1").iloc[0]["n"])\n    if _all_budget_n > 0 and _active_budget_n == 0:\n        execute("UPDATE budget_items SET active=1")\nexcept Exception:\n    pass\n\n# ---------------- helpers ----------------'''
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

# DB 장애 상세를 사용자 화면에 노출하지 않는다. 사이트는 안전모드로 계속 사용 가능.
source = source.replace(
    'st.caption("☁ 중앙 DB 연결" if USE_POSTGRES else "💻 로컬 SQLite 모드")',
    '''st.caption(("☁ 중앙 DB 연결" + (" · Pooler" if CENTRAL_DB_ENDPOINT == "pooler" else "")) if USE_POSTGRES else "🛡 안정화 DB 연결")''',
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
