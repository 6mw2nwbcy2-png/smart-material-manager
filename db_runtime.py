"""Central DB resolver for Streamlit Cloud.

Prefers the configured PostgreSQL URL and tries safe Supabase pooler alternatives.
Returns a resolved URL only after SELECT 1 succeeds. No credentials are logged.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit, quote, parse_qsl, urlencode
import time
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


def _pooler_candidates(url: str):
    out = []
    if not url:
        return out
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        user = p.username or "postgres"
        password = p.password or ""
        dbpath = p.path or "/postgres"
        query = p.query

        if host.startswith("db.") and host.endswith(".supabase.co"):
            ref = host.split(".")[1]
            pool_user = f"postgres.{ref}"
            regions = [
                "ap-northeast-2", "ap-northeast-1", "ap-southeast-1",
                "ap-southeast-2", "ap-south-1", "eu-central-1",
                "eu-west-1", "us-east-1", "us-west-1",
            ]
            for cluster in (0, 1):
                for region in regions:
                    pool_host = f"aws-{cluster}-{region}.pooler.supabase.com"
                    auth = quote(pool_user, safe="")
                    if password:
                        auth += ":" + quote(password, safe="")
                    for port in (5432, 6543):
                        netloc = f"{auth}@{pool_host}:{port}"
                        candidate = urlunsplit((p.scheme or "postgresql", netloc, dbpath, query, ""))
                        out.append(candidate)

        if "pooler.supabase.com" in host:
            auth = quote(user, safe="")
            if password:
                auth += ":" + quote(password, safe="")
            for port in (5432, 6543):
                netloc = f"{auth}@{host}:{port}"
                out.append(urlunsplit((p.scheme or "postgresql", netloc, dbpath, query, "")))
    except Exception:
        pass
    return out


def resolve_database_url(primary_url: str = "", secrets=None) -> DBResolution:
    """Resolve a working PostgreSQL endpoint without exposing credentials."""
    url = str(primary_url or "").strip()
    if not url and secrets is not None:
        url = _secret_candidate(
            secrets,
            ["DATABASE_URL", "SUPABASE_DATABASE_URL", "POSTGRES_URL", "POSTGRESQL_URL"],
        )

    if not url:
        return DBResolution("", False, reason="DATABASE_URL 없음", configured=False)

    candidates = []
    for candidate in [url, _with_sslmode(url), *_pooler_candidates(url)]:
        candidate = _with_sslmode(candidate)
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    last_reason = "연결 실패"
    for candidate in candidates:
        for attempt in range(2):
            conn = None
            try:
                conn = psycopg2.connect(candidate, connect_timeout=6, sslmode="require")
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                host = (urlsplit(candidate).hostname or "").lower()
                endpoint = "pooler" if "pooler.supabase.com" in host else "direct"
                return DBResolution(candidate, True, endpoint=endpoint, configured=True)
            except Exception as exc:
                name = type(exc).__name__
                msg = str(exc).lower()
                if "password authentication failed" in msg:
                    last_reason = "DB 비밀번호 인증 실패"
                elif "could not translate host name" in msg or "name or service not known" in msg:
                    last_reason = "DB 주소/DNS 연결 실패"
                elif "timeout" in msg or "timed out" in msg:
                    last_reason = "DB 연결 시간 초과"
                elif "network is unreachable" in msg:
                    last_reason = "DB 네트워크 접근 불가"
                else:
                    last_reason = name
                if attempt == 0:
                    time.sleep(0.35)
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

    return DBResolution("", False, reason=last_reason, configured=True)
