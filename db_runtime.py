"""Fast, failure-safe central DB resolver for Streamlit Cloud.

A configured PostgreSQL URL is tested briefly. If it is unavailable, the caller can
immediately fall back to the local backup DB instead of spending a long time probing
many guessed endpoints. No credentials or raw driver errors are exposed to users.
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


def _with_sslmode(url: str) -> str:
    try:
        p = urlsplit(url)
        q = dict(parse_qsl(p.query, keep_blank_values=True))
        q.setdefault("sslmode", "require")
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))
    except Exception:
        return url


def _secret_candidate(secrets, names):
    for name in names:
        try:
            value = secrets.get(name, "")
            if value:
                return str(value).strip()
        except Exception:
            pass
    return ""


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


def resolve_database_url(primary_url: str = "", secrets=None) -> DBResolution:
    """Resolve only explicitly configured DB endpoints, quickly and safely."""
    url = str(primary_url or "").strip()
    if not url and secrets is not None:
        url = _secret_candidate(
            secrets,
            ["DATABASE_URL", "SUPABASE_DATABASE_URL", "POSTGRES_URL", "POSTGRESQL_URL"],
        )

    if not url:
        return DBResolution("", False, reason="설정 없음", configured=False)

    candidates = []
    for candidate in (url, _with_sslmode(url)):
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    last_reason = "연결 불가"
    for candidate in candidates:
        conn = None
        try:
            conn = psycopg2.connect(candidate, connect_timeout=3, sslmode="require")
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            host = (urlsplit(candidate).hostname or "").lower()
            endpoint = "pooler" if "pooler.supabase.com" in host else "direct"
            return DBResolution(candidate, True, endpoint=endpoint, configured=True)
        except Exception as exc:
            last_reason = _friendly_reason(exc)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    return DBResolution("", False, reason=last_reason, configured=True)
