"""Smart Material Manager stable entrypoint.
Central DB is preferred so the original budget/order data is shown again.
If the direct central DB endpoint is unavailable, the app automatically tries
Supabase session-pooler endpoints before using the repository SQLite backup.
"""
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("app_snapshot.py")
source = SNAPSHOT.read_text(encoding="utf-8")

# 중앙 DB 우선. 기존 DATABASE_URL이 Supabase direct 주소라 접속이 안 되는 경우
# 서울/아시아 session pooler 후보도 자동으로 시도한 뒤에만 백업 DB로 전환한다.
source = source.replace(
    "DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)",
    '''DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)\nCENTRAL_DB_FALLBACK = False\nCENTRAL_DB_ERROR = ""\nCENTRAL_DB_ENDPOINT = ""\n\nif USE_POSTGRES:\n    import time as _db_time\n    from urllib.parse import urlsplit as _urlsplit, urlunsplit as _urlunsplit, quote as _urlquote\n\n    def _db_candidates(_url):\n        _result = []\n        if _url:\n            _result.append(_url)\n        try:\n            _p = _urlsplit(_url)\n            _host = (_p.hostname or "").lower()\n            _user = _p.username or "postgres"\n            _password = _p.password or ""\n            _dbpath = _p.path or "/postgres"\n            _query = _p.query\n\n            # Supabase direct: db.<project-ref>.supabase.co -> session pooler\n            if _host.startswith("db.") and _host.endswith(".supabase.co"):\n                _ref = _host.split(".")[1]\n                _pool_user = f"postgres.{_ref}"\n                for _region in ["ap-northeast-2", "ap-northeast-1", "ap-southeast-1", "ap-southeast-2"]:\n                    _pool_host = f"aws-0-{_region}.pooler.supabase.com"\n                    _auth = _urlquote(_pool_user, safe="")\n                    if _password:\n                        _auth += ":" + _urlquote(_password, safe="")\n                    _netloc = f"{_auth}@{_pool_host}:5432"\n                    _candidate = _urlunsplit((_p.scheme or "postgresql", _netloc, _dbpath, _query, ""))\n                    if _candidate not in _result:\n                        _result.append(_candidate)\n\n            # 이미 pooler 주소인데 transaction port(6543)라면 session port(5432)도 시도\n            if "pooler.supabase.com" in _host and (_p.port or 0) != 5432:\n                _auth = _urlquote(_user, safe="")\n                if _password:\n                    _auth += ":" + _urlquote(_password, safe="")\n                _netloc = f"{_auth}@{_host}:5432"\n                _candidate = _urlunsplit((_p.scheme or "postgresql", _netloc, _dbpath, _query, ""))\n                if _candidate not in _result:\n                    _result.append(_candidate)\n        except Exception:\n            pass\n        return _result\n\n    _connected = False\n    for _candidate in _db_candidates(DATABASE_URL):\n        for _attempt in range(2):\n            _probe = None\n            try:\n                _probe = psycopg2.connect(_candidate, connect_timeout=6)\n                with _probe.cursor() as _cur:\n                    _cur.execute("SELECT 1")\n                    _cur.fetchone()\n                DATABASE_URL = _candidate\n                CENTRAL_DB_ENDPOINT = "pooler" if "pooler.supabase.com" in _candidate else "direct"\n                _connected = True\n                break\n            except Exception as _db_exc:\n                CENTRAL_DB_ERROR = f"{type(_db_exc).__name__}: {_db_exc}"\n                if _attempt == 0:\n                    _db_time.sleep(0.5)\n            finally:\n                if _probe is not None:\n                    try:\n                        _probe.close()\n                    except Exception:\n                        pass\n        if _connected:\n            break\n\n    if not _connected:\n        USE_POSTGRES = False\n        CENTRAL_DB_FALLBACK = True''',
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
    '''st.caption(("☁ 중앙 DB 연결" + (" · Pooler" if CENTRAL_DB_ENDPOINT == "pooler" else "")) if USE_POSTGRES else "🛟 백업 DB 모드")\nif CENTRAL_DB_FALLBACK:\n    st.warning("중앙 DB의 direct/pooler 연결을 모두 시도했지만 연결되지 않아 백업 DB로 표시 중입니다.")''',
    1,
)

# 한눈에 보기 확장 화면 유지.
overview_anchor = '    st.info("일반 사용자는 자재 투입수량을 입력할 수 있고, 예산/품목/입고/발주상태 수정은 관리자만 가능합니다.")'
overview_extra = overview_anchor + '''\n\n    try:\n        _extra = Path("dashboard_extra.py")\n        exec(compile(_extra.read_text(encoding="utf-8"), str(_extra), "exec"), globals(), globals())\n    except Exception as _overview_error:\n        st.warning(f"담당자/업체별 현황을 표시하지 못했습니다: {_overview_error}")'''
source = source.replace(overview_anchor, overview_extra, 1)

# 관리자 설정은 별도 안정화 모듈에서 관리.
admin_marker = 'elif menu == "관리자 설정":'
pos = source.find(admin_marker)
if pos >= 0:
    admin_block = '''elif menu == "관리자 설정":\n    _admin = Path("admin_settings_extra.py")\n    exec(compile(_admin.read_text(encoding="utf-8"), str(_admin), "exec"), globals(), globals())\n'''
    source = source[:pos] + admin_block

exec(compile(source, str(SNAPSHOT), "exec"), globals(), globals())