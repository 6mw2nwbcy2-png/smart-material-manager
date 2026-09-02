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
