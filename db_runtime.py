"""Failure-safe central DB resolver for Streamlit Cloud.

Only explicitly configured database URLs are tried. The resolver never invents or
guesses a database endpoint, and it does not expose credentials or raw driver errors.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import psycopg2


@dataclass
class DBResolution:
    url: str
    connected: bool
    endpoint: str = ""
    reason: str = ""
    configured: bool = False
    secret_name: str = ""


def _with_sslmode(url: str) -> str:
    try:
        p = urlsplit(url)
        q = dict(parse_qsl(p.query, keep_blank_values=True))
        q.setdefault("sslmode", "require")
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))
    except Exception:
        return url


def _friendly_reason(exc: Exception) -> str:
    msg = str(exc).lower()
    if "password authentication failed" in msg:
        return "인증 실패"
    if "could not translate host name" in msg or "name or service not known" in msg:
        return "주소 확인 필요"
    if "timeout" in msg or "timed out" in msg:
        return "연결 시간 초과"
    if "network is unreachable" in msg:
        return "네트워크 접근 불가"
    return "연결 불가"


def _configured_urls(primary_url: str = "", secrets=None):
    """Return unique, explicitly configured URLs in priority order."""
    values = []

    def add(name, value):
        value = str(value or "").strip()
        if value and all(existing_url != value for _, existing_url in values):
            values.append((name, value))

    add("DATABASE_URL", primary_url)

    if secrets is not None:
        for name in [
            "DATABASE_URL",
            "SUPABASE_DATABASE_URL",
            "POSTGRES_URL",
            "POSTGRESQL_URL",
        ]:
            try:
                add(name, secrets.get(name, ""))
            except Exception:
                pass

    return values


def resolve_database_url(primary_url: str = "", secrets=None) -> DBResolution:
    """Try every explicitly configured DB URL; never guess an endpoint."""
    configured = _configured_urls(primary_url, secrets)
    if not configured:
        return DBResolution("", False, reason="설정 없음", configured=False)

    last_reason = "연결 불가"
    for secret_name, url in configured:
        candidates = []
        for candidate in (url, _with_sslmode(url)):
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        for candidate in candidates:
            conn = None
            try:
                conn = psycopg2.connect(candidate, connect_timeout=5, sslmode="require")
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                host = (urlsplit(candidate).hostname or "").lower()
                endpoint = "pooler" if "pooler.supabase.com" in host else "direct"
                return DBResolution(
                    candidate,
                    True,
                    endpoint=endpoint,
                    configured=True,
                    secret_name=secret_name,
                )
            except Exception as exc:
                last_reason = _friendly_reason(exc)
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

    return DBResolution(
        "",
        False,
        reason=last_reason,
        configured=True,
    )
