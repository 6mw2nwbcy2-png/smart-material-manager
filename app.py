"""Smart Material Manager emergency-stable entrypoint.
Loads the last known-good application and keeps the full site available even when the
central PostgreSQL connection is temporarily unavailable.
"""
import base64
import json
import urllib.request

BASE_REF = "7f0acc4a0afc991c314ba6d40cad865a7cc2d414"
RAW_URL = f"https://api.github.com/repos/6mw2nwbcy2-png/smart-material-manager/contents/app.py?ref={BASE_REF}"

req = urllib.request.Request(
    RAW_URL,
    headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "smart-material-manager",
    },
)
with urllib.request.urlopen(req, timeout=20) as resp:
    payload = json.loads(resp.read().decode("utf-8"))

source = base64.b64decode(payload["content"]).decode("utf-8")

# 중앙 DB 연결 정보는 보존하되 현재 장애가 사이트 전체를 막지 않도록
# 정상 화면은 저장소의 SQLite 백업 DB로 우선 구동합니다.
source = source.replace(
    "DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)",
    "DATABASE_URL = ''\nUSE_POSTGRES = False",
    1,
)

source = source.replace(
    'st.caption("☁ 중앙 DB 연결" if USE_POSTGRES else "💻 로컬 SQLite 모드")',
    'st.caption("🛟 백업 DB 복구 모드")\nst.warning("중앙 DB 연결 장애로 사이트를 백업 DB 모드로 복구했습니다. 화면과 기존 기능은 사용할 수 있으며, 중앙 DB는 별도로 정상화 후 재연결합니다.")',
    1,
)

exec(compile(source, "app.py", "exec"), globals(), globals())
