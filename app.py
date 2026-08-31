"""Smart Material Manager stable entrypoint.
Uses a repository-pinned application snapshot so deployment does not depend on runtime
GitHub fetches or the central DB being available during startup.
"""
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("app_snapshot.py")
source = SNAPSHOT.read_text(encoding="utf-8")

# 안정화 1단계: 중앙 DB 장애가 사이트 전체를 막지 않도록 백업 DB로 고정 실행.
# 중앙 DB 재연결은 별도 검증 후 main에 반영합니다.
source = source.replace(
    "DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)",
    "DATABASE_URL = ''\nUSE_POSTGRES = False",
    1,
)

# 석재 메뉴는 PostgreSQL 전용 구현을 절대 호출하지 않고 안정화 페이지로 우회.
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
    'st.caption("🛡 안정화 모드 · 백업 DB")\nst.info("현재 사이트 안정화를 위해 백업 DB 모드로 운영 중입니다. 중앙 DB 재연결은 별도 검증 후 적용합니다.")',
    1,
)

exec(compile(source, str(SNAPSHOT), "exec"), globals(), globals())
