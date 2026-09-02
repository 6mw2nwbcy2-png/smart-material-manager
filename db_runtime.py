"""Failure-safe central DB resolver for Streamlit Cloud.

Goals:
- Always prefer the existing central PostgreSQL DB configured in Streamlit Secrets.
- Close every probe connection immediately.
- If a Supabase direct IPv6 endpoint is unreachable, derive the same project's
  shared IPv4 pooler endpoints (session first, transaction second).
- Never expose credentials or raw driver errors to the UI.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, quote, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import psycopg2


@dataclass
class DBResolution:
    url: str
    connected: bool
    endpoint: str = ""
    reason: str = ""
    configured: bool = False
    secret_name: str = ""


def _normalize_scheme(url: str) -> str:
    url = str(url or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def _with_sslmode(url: str) -> str:
    url = _normalize_scheme(url)
    try:
        p = urlsplit(url)
        q = dict(parse_qsl(p.query, keep_blank_values=True))
        q.setdefault("sslmode", "require")
        q.setdefault("connect_timeout", "5")
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))
    except Exception:
        return url


def _friendly_reason(exc: Exception) -> str:
    msg = str(exc).lower()
    if "password authentication failed" in msg or "wrong password" in msg:
        return "인증 실패"
    if "tenant or user not found" in msg:
        return "Pooler 위치 확인 필요"
    if "too many clients" in msg or "remaining connection slots" in msg or "max client" in msg:
        return "DB 연결수 초과"
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
        value = _normalize_scheme(value)
        if value and all(existing_url != value for _, existing_url in values):
            values.append((name, value))

    add("DATABASE_URL", primary_url)
    if secrets is not None:
        for name in [
            "DATABASE_URL",
            "SUPABASE_DATABASE_URL",
            "POSTGRES_URL",
            "POSTGRESQL_URL",
            "SUPABASE_DB_URL",
        ]:
            try:
                add(name, secrets.get(name, ""))
            except Exception:
                pass
    return values


def _project_ref_from_url(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower()
        m = re.match(r"db\.([a-z0-9]+)\.supabase\.co$", host)
        if m:
            return m.group(1)
        # Already a shared pooler URL: username is normally postgres.<project-ref>
        user = unquote(urlsplit(url).username or "")
        if user.startswith("postgres.") and len(user.split(".", 1)) == 2:
            return user.split(".", 1)[1]
    except Exception:
        pass
    m = re.search(r"db\.([a-z0-9]+)\.supabase\.co", str(url or "").lower())
    return m.group(1) if m else ""


def _supabase_credentials(url: str):
    try:
        p = urlsplit(_normalize_scheme(url))
        project_ref = _project_ref_from_url(url)
        password = unquote(p.password or "")
        db_path = p.path or "/postgres"
        if project_ref and password:
            return project_ref, password, db_path
    except Exception:
        pass
    return "", "", "/postgres"


def _supabase_pooler_candidates(url: str):
    """Derive shared Supavisor endpoints for the SAME Supabase project.

    Supabase documents session mode on 5432 and transaction mode on 6543.  We try
    every current AWS region family because the original direct URL itself does not
    encode the project's region.
    """
    project_ref, password, db_path = _supabase_credentials(url)
    if not project_ref or not password:
        return []

    regions = [
        # Korea / Asia-Pacific first
        "ap-northeast-2", "ap-northeast-1", "ap-southeast-1", "ap-southeast-2",
        "ap-south-1", "ap-southeast-3", "ap-southeast-4",
        # North America
        "us-east-1", "us-east-2", "us-west-1", "us-west-2", "ca-central-1",
        # Europe
        "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1", "eu-central-2",
        "eu-north-1", "eu-south-1",
        # South America / Africa / Middle East
        "sa-east-1", "af-south-1", "me-south-1", "me-central-1",
    ]
    pool_user = f"postgres.{project_ref}"
    result = []
    for prefix in ("aws-0", "aws-1"):
        for region in regions:
            host = f"{prefix}-{region}.pooler.supabase.com"
            for port, mode in ((5432, "session"), (6543, "transaction")):
                netloc = (
                    f"{quote(pool_user, safe='.')}:"
                    f"{quote(password, safe='')}@{host}:{port}"
                )
                query = urlencode({
                    "sslmode": "require",
                    "connect_timeout": "4",
                    "application_name": "smart-material-manager",
                })
                candidate = urlunsplit(("postgresql", netloc, db_path, query, ""))
                result.append((candidate, f"pooler-{mode}"))
    return result


def _candidate_urls(url: str):
    url = _normalize_scheme(url)
    candidates = []
    seen = set()

    def add(candidate, endpoint):
        candidate = str(candidate or "").strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append((candidate, endpoint))

    host = ""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except Exception:
        pass

    add(_with_sslmode(url), "pooler-configured" if "pooler.supabase.com" in host else "direct")

    # If a pooler URL is already configured, also try the same host on the other
    # standard Supavisor port before deriving anything else.
    if "pooler.supabase.com" in host:
        try:
            p = urlsplit(url)
            alt_port = 6543 if (p.port or 5432) == 5432 else 5432
            netloc = p.netloc.rsplit(":", 1)[0] + f":{alt_port}"
            add(_with_sslmode(urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))), "pooler-configured")
        except Exception:
            pass

    if host.startswith("db.") and host.endswith(".supabase.co"):
        for candidate, endpoint in _supabase_pooler_candidates(url):
            add(candidate, endpoint)
    return candidates


def _probe(candidate: str):
    conn = None
    try:
        conn = psycopg2.connect(
            candidate,
            connect_timeout=4,
            application_name="smart-material-manager",
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=3,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True, ""
    except Exception as exc:
        return False, _friendly_reason(exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def resolve_database_url(primary_url: str = "", secrets=None) -> DBResolution:
    """Resolve and verify the existing central DB without leaking credentials."""
    configured = _configured_urls(primary_url, secrets)
    if not configured:
        return DBResolution("", False, reason="설정 없음", configured=False)

    reasons = []
    for secret_name, url in configured:
        candidates = _candidate_urls(url)
        if not candidates:
            continue

        # First try the explicitly configured endpoint alone. This keeps normal startup fast.
        candidate, endpoint = candidates[0]
        ok, reason = _probe(candidate)
        if ok:
            return DBResolution(candidate, True, endpoint=endpoint, configured=True, secret_name=secret_name)
        reasons.append(reason)

        # Pooler fallbacks are probed concurrently so a dead IPv6/direct route does not
        # turn every Streamlit rerun into a minute-long startup.
        fallback = candidates[1:]
        if fallback:
            ex = ThreadPoolExecutor(max_workers=12)
            futures = {ex.submit(_probe, cand): (cand, ep) for cand, ep in fallback}
            try:
                for fut in as_completed(futures):
                    cand, ep = futures[fut]
                    try:
                        ok, reason = fut.result()
                    except Exception as exc:
                        ok, reason = False, _friendly_reason(exc)
                    if ok:
                        for other in futures:
                            other.cancel()
                        ex.shutdown(wait=False, cancel_futures=True)
                        return DBResolution(cand, True, endpoint=ep, configured=True, secret_name=secret_name)
                    reasons.append(reason)
            finally:
                try:
                    ex.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass

    # Prefer the most actionable safe reason instead of whichever candidate failed last.
    priority = ["인증 실패", "DB 연결수 초과", "Pooler 위치 확인 필요", "주소 확인 필요", "연결 시간 초과", "네트워크 접근 불가", "연결 거부", "연결 불가"]
    last_reason = next((r for r in priority if r in reasons), reasons[-1] if reasons else "연결 불가")
    return DBResolution("", False, reason=last_reason, configured=True)
