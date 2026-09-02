"""Failure-safe central DB resolver for Streamlit Cloud.

The app always prefers the configured central PostgreSQL database. For Supabase direct
URLs that are unreachable from an IPv4-only cloud runtime, the resolver can derive the
standard Session Pooler address from the SAME project reference/password already stored
in Streamlit Secrets. No new account, key, or external credential is required.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, quote, unquote
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
    if "network is unreachable" in msg or "no route to host" in msg:
        return "네트워크 접근 불가"
    if "connection refused" in msg:
        return "연결 거부"
    return "연결 불가"


def _configured_urls(primary_url: str = "", secrets=None):
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


def _supabase_pooler_candidates(url: str):
    """Derive standard Supabase Session Pooler URLs from an existing direct URL.

    Example direct host: db.<project-ref>.supabase.co
    Session pooler user: postgres.<project-ref>
    Session pooler port: 5432
    """
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        if not (host.startswith("db.") and host.endswith(".supabase.co")):
            return []

        project_ref = host[len("db.") : -len(".supabase.co")]
        if not project_ref:
            return []

        password = unquote(p.password or "")
        if not password:
            return []

        db_path = p.path or "/postgres"
        pool_user = f"postgres.{project_ref}"

        # Korea first because this project is operated in Korea; the rest are safe
        # standard Supabase AWS regions and are tried only if the earlier candidates fail.
        regions = [
            "ap-northeast-2",
            "ap-northeast-1",
            "ap-southeast-1",
            "ap-southeast-2",
            "ap-south-1",
            "us-east-1",
            "us-west-1",
            "ca-central-1",
            "eu-west-1",
            "eu-central-1",
            "sa-east-1",
        ]

        result = []
        for region in regions:
            pool_host = f"aws-0-{region}.pooler.supabase.com"
            netloc = (
                f"{quote(pool_user, safe='.')}:"
                f"{quote(password, safe='')}@{pool_host}:5432"
            )
            candidate = urlunsplit((
                p.scheme or "postgresql",
                netloc,
                db_path,
                urlencode({"sslmode": "require"}),
                "",
            ))
            result.append(candidate)
        return result
    except Exception:
        return []


def _candidate_urls(url: str):
    candidates = []

    def add(candidate):
        candidate = str(candidate or "").strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    add(_with_sslmode(url))
    for candidate in _supabase_pooler_candidates(url):
        add(candidate)
    return candidates


def resolve_database_url(primary_url: str = "", secrets=None) -> DBResolution:
    """Connect to the existing central DB, including an automatic Supabase pooler fallback."""
    configured = _configured_urls(primary_url, secrets)
    if not configured:
        return DBResolution("", False, reason="설정 없음", configured=False)

    last_reason = "연결 불가"
    for secret_name, url in configured:
        direct_host = (urlsplit(url).hostname or "").lower()
        for candidate in _candidate_urls(url):
            conn = None
            try:
                conn = psycopg2.connect(candidate, connect_timeout=4)
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()

                host = (urlsplit(candidate).hostname or "").lower()
                if "pooler.supabase.com" in host:
                    endpoint = "pooler"
                elif host == direct_host:
                    endpoint = "direct"
                else:
                    endpoint = "postgres"

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
