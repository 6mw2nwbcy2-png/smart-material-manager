"""Smart Material Manager stable entrypoint.
Central DB is preferred so the original budget/order data is shown again.
If the central DB is temporarily unavailable, the app falls back to the repository
SQLite backup instead of crashing.
"""
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("app_snapshot.py")
source = SNAPSHOT.read_text(encoding="utf-8")

# 중앙 DB 우선 + 연결 실패 시에만 백업 DB 자동 전환.
source = source.replace(
    "DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)",
    '''DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)\nCENTRAL_DB_FALLBACK = False\n\nif USE_POSTGRES:\n    _probe = None\n    try:\n        _probe = psycopg2.connect(DATABASE_URL, connect_timeout=5)\n    except Exception:\n        USE_POSTGRES = False\n        CENTRAL_DB_FALLBACK = True\n    finally:\n        if _probe is not None:\n            try:\n                _probe.close()\n            except Exception:\n                pass''',
    1,
)

# 석재는 안정화 래퍼를 통해 실행.
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
    '''st.caption("☁ 중앙 DB 연결" if USE_POSTGRES else "🛟 백업 DB 모드")\nif CENTRAL_DB_FALLBACK:\n    st.warning("중앙 DB 연결이 일시적으로 불가하여 백업 DB로 표시 중입니다. 중앙 DB가 정상화되면 기존 예산/발주 내역이 다시 표시됩니다.")''',
    1,
)

# 한눈에 보기 확장 화면 유지.
overview_anchor = '    st.info("일반 사용자는 자재 투입수량을 입력할 수 있고, 예산/품목/입고/발주상태 수정은 관리자만 가능합니다.")'
overview_extra = overview_anchor + '''\n\n    try:\n        _extra = Path("dashboard_extra.py")\n        exec(compile(_extra.read_text(encoding="utf-8"), str(_extra), "exec"), globals(), globals())\n    except Exception as _overview_error:\n        st.warning(f"담당자/업체별 현황을 표시하지 못했습니다: {_overview_error}")'''
source = source.replace(overview_anchor, overview_extra, 1)

# 관리자 설정은 별도 안정화 모듈에서 관리.
# 예산/품목 일괄편집 + 저장된 발주서 상태변경/선택삭제 기능 포함.
admin_marker = 'elif menu == "관리자 설정":'
pos = source.find(admin_marker)
if pos >= 0:
    admin_block = '''elif menu == "관리자 설정":\n    _admin = Path("admin_settings_extra.py")\n    exec(compile(_admin.read_text(encoding="utf-8"), str(_admin), "exec"), globals(), globals())\n'''
    source = source[:pos] + admin_block

exec(compile(source, str(SNAPSHOT), "exec"), globals(), globals())
