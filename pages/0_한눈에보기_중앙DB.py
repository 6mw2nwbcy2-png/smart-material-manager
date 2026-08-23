import streamlit as st
import pandas as pd
import psycopg2
from datetime import date

st.set_page_config(page_title="한눈에 보기", page_icon="📊", layout="wide")

SITE_NAME = "힐스테이트 레이크송도5차"


def get_database_url():
    try:
        if "DATABASE_URL" in st.secrets:
            return str(st.secrets["DATABASE_URL"]).strip()
    except Exception:
        pass
    return ""

DATABASE_URL = get_database_url()

if not DATABASE_URL:
    st.error("중앙 DB 연결이 설정되지 않았습니다. 이 화면은 중앙 PostgreSQL DB만 사용합니다.")
    st.stop()


def read(sql, params=()):
    with psycopg2.connect(DATABASE_URL) as c:
        return pd.read_sql_query(sql, c, params=params)


def execute(sql, params=()):
    with psycopg2.connect(DATABASE_URL) as c:
        with c.cursor() as cur:
            cur.execute(sql, params)
        c.commit()


def ensure_schema():
    # 기존 DB를 유지하면서 보관위치만 안전하게 추가
    with psycopg2.connect(DATABASE_URL) as c:
        with c.cursor() as cur:
            cur.execute(
                "ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS storage_location TEXT DEFAULT ''"
            )
        c.commit()


ensure_schema()

st.title("한눈에 보기")
st.caption(f"{SITE_NAME} · 중앙 PostgreSQL DB 기준")

# ---------------- 현황 집계 ----------------
totals = read(
    """
    SELECT
        b.id,
        b.category,
        b.vendor,
        b.item_name,
        b.spec,
        b.unit,
        COALESCE(b.budget_qty, 0) AS budget_qty,
        COALESCE(SUM(CASE WHEN t.tx_type='발주' THEN t.qty ELSE 0 END), 0) AS ordered,
        COALESCE(SUM(CASE WHEN t.tx_type='입고' THEN t.qty ELSE 0 END), 0) AS received,
        COALESCE(SUM(CASE WHEN t.tx_type='투입' THEN t.qty ELSE 0 END), 0) AS used
    FROM budget_items b
    LEFT JOIN transactions t ON b.id=t.item_id
    WHERE b.active=1
    GROUP BY b.id
    ORDER BY b.category, b.vendor, b.spec, b.item_name
    """
)

if len(totals):
    totals["재고"] = totals["received"] - totals["used"]
    totals["입고율"] = totals.apply(
        lambda r: (r["received"] / r["budget_qty"] * 100) if r["budget_qty"] else 0,
        axis=1,
    )
else:
    totals["재고"] = []
    totals["입고율"] = []

orders = read(
    """
    SELECT
        o.id AS order_id,
        o.order_no,
        o.category,
        o.vendor,
        o.order_date,
        o.order_complete,
        b.item_name,
        b.spec,
        b.unit,
        ol.qty,
        ol.requested_delivery_date,
        ol.destination,
        ol.storage_location
    FROM order_lines ol
    JOIN orders o ON ol.order_id=o.id
    JOIN budget_items b ON ol.item_id=b.id
    WHERE COALESCE(o.order_complete,0)=0
    ORDER BY ol.requested_delivery_date, o.id, ol.id
    """
)

# ---------------- 상단 KPI ----------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("등록 예산 품목", f"{len(totals):,}종")

received_total = float(totals["received"].sum()) if len(totals) else 0
used_total = float(totals["used"].sum()) if len(totals) else 0
ordered_total = float(totals["ordered"].sum()) if len(totals) else 0

c2.metric("누적 입고", f"{received_total:,.1f}")
c3.metric("누적 투입", f"{used_total:,.1f}")
c4.metric("진행 중 발주 품목", f"{len(orders):,}건")

# ---------------- 자재별 현장 반입 일정 ----------------
st.markdown("## 자재별 현장 반입 일정")

if not len(orders):
    st.info("현재 진행 중인 발주/반입 예정 품목이 없습니다.")
else:
    schedule = orders.copy()
    schedule["반입일"] = pd.to_datetime(schedule["requested_delivery_date"], errors="coerce")
    today = date.today()
    schedule["D-Day"] = schedule["반입일"].apply(
        lambda x: "미정" if pd.isna(x) else (
            "D-Day" if (x.date() - today).days == 0 else
            (f"D-{(x.date()-today).days}" if (x.date()-today).days > 0 else f"D+{abs((x.date()-today).days)}")
        )
    )
    schedule["반입일"] = schedule["반입일"].dt.strftime("%Y-%m-%d").fillna("미정")
    schedule["보관위치"] = schedule["storage_location"].fillna("").replace("", "미지정")
    schedule["납품처"] = schedule["destination"].fillna("").replace("", "미지정")

    show = schedule[[
        "category", "item_name", "spec", "vendor", "qty", "unit",
        "반입일", "D-Day", "납품처", "보관위치", "order_no"
    ]].copy()
    show.columns = [
        "공종", "품명", "규격", "협력사", "수량", "단위",
        "현장 반입 예정일", "일정", "납품처", "보관위치", "발주번호"
    ]
    st.dataframe(show, use_container_width=True, hide_index=True)

# ---------------- 예산 대비 입고 그래프 ----------------
st.markdown("## 예산 수량 대비 누적 입고")

if len(totals):
    chart = totals.copy()
    chart["품목"] = chart.apply(
        lambda r: f"{r['category']} | {r['item_name']}" + (f" ({r['spec']})" if str(r['spec']).strip() else ""),
        axis=1,
    )
    chart = chart.sort_values(["category", "item_name", "spec"]).set_index("품목")
    st.bar_chart(chart[["budget_qty", "received"]].rename(columns={"budget_qty": "예산수량", "received": "누적입고"}), use_container_width=True)

    detail = totals[[
        "category", "vendor", "item_name", "spec", "unit",
        "budget_qty", "received", "ordered", "used", "재고", "입고율"
    ]].copy()
    detail["입고율"] = detail["입고율"].round(1).astype(str) + "%"
    detail.columns = [
        "공종", "협력사", "품명", "규격", "단위",
        "예산수량", "누적입고", "누적발주", "누적투입", "현재재고", "입고율"
    ]
    st.dataframe(detail, use_container_width=True, hide_index=True)
else:
    st.info("등록된 예산 품목이 없습니다.")

# ---------------- 보관위치 관리자 입력 ----------------
st.markdown("## 반입/보관 위치 관리")
st.caption("보관위치는 중앙 DB의 발주 품목별로 저장됩니다. 일반 사용자는 조회만 가능합니다.")

if st.session_state.get("is_admin", False):
    if len(orders):
        location_df = orders[[
            "order_id", "order_no", "item_name", "spec", "qty",
            "requested_delivery_date", "storage_location"
        ]].copy()
        location_df.columns = [
            "order_id", "발주번호", "품명", "규격", "수량", "반입예정일", "보관위치"
        ]
        edited = st.data_editor(
            location_df,
            use_container_width=True,
            hide_index=True,
            disabled=["order_id", "발주번호", "품명", "규격", "수량", "반입예정일"],
            column_config={"order_id": None, "보관위치": st.column_config.TextColumn("보관위치")},
            key="central_storage_location_editor",
        )
        if st.button("보관위치 저장", type="primary"):
            for _, r in edited.iterrows():
                order_id = int(r["order_id"])
                # 같은 발주에 같은 품목이 여러 줄일 수 있으므로 발주번호+품명+규격 기준으로 업데이트
                execute(
                    """
                    UPDATE order_lines ol
                    SET storage_location=%s
                    FROM budget_items b
                    WHERE ol.order_id=%s
                      AND ol.item_id=b.id
                      AND b.item_name=%s
                      AND COALESCE(b.spec,'')=%s
                    """,
                    (str(r.get("보관위치", "") or "").strip(), order_id,
                     str(r["품명"]), str(r["규격"] or "")),
                )
            st.success("보관위치가 중앙 DB에 저장되었습니다.")
            st.rerun()
    else:
        st.info("진행 중 발주가 없어 보관위치를 입력할 품목이 없습니다.")
else:
    st.caption("보관위치 수정은 관리자만 가능합니다.")
