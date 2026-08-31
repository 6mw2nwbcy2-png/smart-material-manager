import sqlite3
from pathlib import Path
from datetime import date

import pandas as pd
import streamlit as st

DB = Path("material_manager_v11.db")
CATEGORY = "석재"
STONE_TYPES = ["인조석", "천연가공석"]


def execute(sql, params=()):
    with sqlite3.connect(DB) as c:
        c.execute(sql, params)
        c.commit()


def read(sql, params=()):
    with sqlite3.connect(DB) as c:
        return pd.read_sql_query(sql, c, params=params)


def ensure_schema():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS budget_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            vendor TEXT DEFAULT '',
            item_name TEXT NOT NULL,
            spec TEXT DEFAULT '',
            unit TEXT NOT NULL,
            budget_qty REAL DEFAULT 0,
            tile_type TEXT DEFAULT '',
            application_type TEXT DEFAULT '',
            default_destination TEXT DEFAULT '',
            active INTEGER DEFAULT 1
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_date TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            tx_type TEXT NOT NULL,
            qty REAL NOT NULL,
            destination TEXT DEFAULT '',
            note TEXT DEFAULT '',
            input_user TEXT DEFAULT ''
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT UNIQUE,
            category TEXT NOT NULL,
            vendor TEXT DEFAULT '',
            order_date TEXT NOT NULL,
            partner_confirm INTEGER DEFAULT 0,
            internal_approval INTEGER DEFAULT 0,
            order_complete INTEGER DEFAULT 0,
            note TEXT DEFAULT ''
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS order_lines(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            qty REAL NOT NULL,
            requested_delivery_date TEXT DEFAULT '',
            destination TEXT DEFAULT '',
            delivery_recipient TEXT DEFAULT '',
            delivery_phone TEXT DEFAULT '',
            delivery_address TEXT DEFAULT ''
        )""")
        existing = {r[1] for r in c.execute("PRAGMA table_info(order_lines)").fetchall()}
        for name in ["delivery_recipient", "delivery_phone", "delivery_address"]:
            if name not in existing:
                c.execute(f"ALTER TABLE order_lines ADD COLUMN {name} TEXT DEFAULT ''")
        n = c.execute("SELECT COUNT(*) FROM budget_items WHERE category=? AND active=1", (CATEGORY,)).fetchone()[0]
        if n == 0:
            for stone_type in STONE_TYPES:
                c.execute(
                    """INSERT INTO budget_items(
                        category,vendor,item_name,spec,unit,budget_qty,tile_type,
                        application_type,default_destination,active
                    ) VALUES(?,?,?,?,?,?,?,?,?,1)""",
                    (CATEGORY, "", stone_type, "", "M", 0.0, stone_type, "", "현장"),
                )
        c.commit()


def stone_totals():
    df = read(
        """
        SELECT b.id,b.vendor,b.item_name,b.spec,b.unit,b.budget_qty,
               b.tile_type AS stone_type,b.default_destination,
               COALESCE(SUM(CASE WHEN t.tx_type='발주' THEN t.qty ELSE 0 END),0) AS ordered,
               COALESCE(SUM(CASE WHEN t.tx_type='입고' THEN t.qty ELSE 0 END),0) AS received,
               COALESCE(SUM(CASE WHEN t.tx_type='투입' THEN t.qty ELSE 0 END),0) AS used
        FROM budget_items b
        LEFT JOIN transactions t ON b.id=t.item_id
        WHERE b.category=? AND b.active=1
        GROUP BY b.id
        ORDER BY b.vendor,b.tile_type,b.item_name,b.spec
        """,
        (CATEGORY,),
    )
    if len(df):
        df["재고"] = df["received"] - df["used"]
        df["잔여예산"] = df["budget_qty"] - df["used"]
    return df


def next_order_no(order_date):
    prefix = order_date.strftime("%Y%m%d")
    rows = read("SELECT order_no FROM orders WHERE category=? AND order_no LIKE ?", (CATEGORY, f"{prefix}-%"))
    nums = []
    for x in rows["order_no"] if len(rows) else []:
        try:
            nums.append(int(str(x).split("-")[-1]))
        except Exception:
            pass
    return f"{prefix}-{(max(nums)+1 if nums else 1):03d}"


ensure_schema()

st.title("석재 관리")
st.caption("힐스테이트 레이크송도5차 · 인조석 / 천연가공석")
st.info("🛟 현재 사이트 안정화 기간에는 석재 화면을 백업 DB 모드로 운영합니다.")

totals = stone_totals()

c1, c2, c3 = st.columns(3)
c1.metric("등록 석재 품목", f"{len(totals)}종")
c2.metric("누적 입고", f"{totals['received'].sum():,.1f}" if len(totals) else "0")
c3.metric("누적 투입", f"{totals['used'].sum():,.1f}" if len(totals) else "0")

st.markdown("### 석재 예산 / 품목 관리")
base = totals[["id","vendor","stone_type","item_name","spec","unit","budget_qty","default_destination"]].copy()
base.columns = ["id","협력사","석재구분","품명","규격","단위","예산수량","기본납품처"]
edited = st.data_editor(
    base,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    disabled=["id"],
    column_config={
        "id": None,
        "석재구분": st.column_config.SelectboxColumn("석재구분", options=STONE_TYPES),
        "예산수량": st.column_config.NumberColumn("예산수량", min_value=0.0, step=0.1),
    },
    key="stone_backup_items",
)

if st.button("예산 / 품목 저장", type="primary"):
    current_ids = set(base["id"].dropna().astype(int).tolist()) if len(base) else set()
    edited_ids = set()
    for _, r in edited.iterrows():
        item_name = str(r.get("품명", "") or "").strip()
        unit = str(r.get("단위", "") or "").strip()
        if not item_name or not unit:
            continue
        rid = r.get("id")
        if pd.notna(rid):
            rid = int(rid)
            edited_ids.add(rid)
            execute(
                """UPDATE budget_items SET vendor=?,tile_type=?,item_name=?,spec=?,unit=?,
                   budget_qty=?,default_destination=?,active=1 WHERE id=? AND category=?""",
                (
                    str(r.get("협력사", "") or "").strip(),
                    str(r.get("석재구분", "") or "").strip(),
                    item_name,
                    str(r.get("규격", "") or "").strip(),
                    unit,
                    float(r.get("예산수량", 0) or 0),
                    str(r.get("기본납품처", "") or "").strip(),
                    rid,
                    CATEGORY,
                ),
            )
        else:
            execute(
                """INSERT INTO budget_items(
                   category,vendor,item_name,spec,unit,budget_qty,tile_type,
                   application_type,default_destination,active
                   ) VALUES(?,?,?,?,?,?,?,?,?,1)""",
                (
                    CATEGORY,
                    str(r.get("협력사", "") or "").strip(),
                    item_name,
                    str(r.get("규격", "") or "").strip(),
                    unit,
                    float(r.get("예산수량", 0) or 0),
                    str(r.get("석재구분", "") or "").strip(),
                    "",
                    str(r.get("기본납품처", "") or "").strip(),
                ),
            )
    for rid in current_ids - edited_ids:
        execute("UPDATE budget_items SET active=0 WHERE id=? AND category=?", (rid, CATEGORY))
    st.success("석재 예산 / 품목을 저장했습니다.")
    st.rerun()

st.markdown("---")
st.markdown("### 입고 / 투입 내역 입력")

totals = stone_totals()
if len(totals):
    labels = {
        f"{r['stone_type']} | {r['item_name']} {r['spec']} | {r['vendor']}".strip(): int(r["id"])
        for _, r in totals.iterrows()
    }
    with st.form("stone_backup_tx_form", clear_on_submit=True):
        item_label = st.selectbox("품목", list(labels.keys()))
        tx_type = st.radio("구분", ["입고", "투입"], horizontal=True)
        qty = st.number_input("수량", min_value=0.0, step=0.1)
        tx_date = st.date_input("일자", value=date.today())
        note = st.text_input("비고")
        submitted = st.form_submit_button("내역 저장", type="primary")
    if submitted:
        if qty <= 0:
            st.warning("수량을 0보다 크게 입력해주세요.")
        else:
            execute(
                """INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user)
                   VALUES(?,?,?,?,?,?,?)""",
                (str(tx_date), labels[item_label], tx_type, float(qty), "현장", note.strip(), ""),
            )
            st.success(f"{tx_type} 내역을 저장했습니다.")
            st.rerun()
else:
    st.info("등록된 석재 품목이 없습니다.")

st.markdown("---")
st.markdown("### 석재 발주")

totals = stone_totals()
if len(totals):
    order_labels = {
        f"{r['stone_type']} | {r['item_name']} {r['spec']} | {r['vendor']}".strip(): int(r["id"])
        for _, r in totals.iterrows()
    }
    with st.form("stone_backup_order_form", clear_on_submit=True):
        order_date = st.date_input("발주일", value=date.today(), key="stone_backup_order_date")
        order_item = st.selectbox("발주 품목", list(order_labels.keys()))
        order_qty = st.number_input("발주수량", min_value=0.0, step=0.1)
        requested = st.date_input("납품요청일", value=date.today(), key="stone_backup_req_date")
        recipient = st.text_input("받는 사람")
        phone = st.text_input("연락처")
        address = st.text_input("현장 주소")
        note = st.text_input("발주 비고")
        save_order = st.form_submit_button("발주 저장", type="primary")

    if save_order:
        if order_qty <= 0:
            st.warning("발주수량을 0보다 크게 입력해주세요.")
        else:
            item_id = order_labels[order_item]
            row = totals[totals["id"] == item_id].iloc[0]
            order_no = next_order_no(order_date)
            with sqlite3.connect(DB) as c:
                cur = c.cursor()
                cur.execute(
                    """INSERT INTO orders(order_no,category,vendor,order_date,partner_confirm,
                       internal_approval,order_complete,note) VALUES(?,?,?,?,0,0,0,?)""",
                    (order_no, CATEGORY, str(row["vendor"] or ""), str(order_date), note.strip()),
                )
                order_id = cur.lastrowid
                cur.execute(
                    """INSERT INTO order_lines(order_id,item_id,qty,requested_delivery_date,destination,
                       delivery_recipient,delivery_phone,delivery_address)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (order_id, item_id, float(order_qty), str(requested), "현장",
                     recipient.strip(), phone.strip(), address.strip()),
                )
                cur.execute(
                    """INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user)
                       VALUES(?,?,?,?,?,?,?)""",
                    (str(order_date), item_id, "발주", float(order_qty), "현장", f"발주번호 {order_no}", ""),
                )
                c.commit()
            st.success(f"석재 발주 저장 완료: {order_no}")
            st.rerun()

st.markdown("---")
st.markdown("### 최근 석재 발주 현황")
orders = read(
    """SELECT o.order_no,o.vendor,o.order_date,b.item_name,b.spec,ol.qty,b.unit,
              ol.requested_delivery_date,ol.destination
       FROM orders o
       JOIN order_lines ol ON o.id=ol.order_id
       JOIN budget_items b ON ol.item_id=b.id
       WHERE o.category=?
       ORDER BY o.id DESC, ol.id DESC
       LIMIT 100""",
    (CATEGORY,),
)
if len(orders):
    orders.columns = ["발주번호","협력사","발주일","품명","규격","수량","단위","납품요청일","납품처"]
    st.dataframe(orders, use_container_width=True, hide_index=True)
else:
    st.info("석재 발주 내역이 없습니다.")
