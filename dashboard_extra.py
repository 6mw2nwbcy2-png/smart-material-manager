"""Extended '한눈에 보기' for Smart Material Manager.

Shows the exact operational items requested for 지급자재 management:
- material-by-material planned site delivery schedule
- storage location
- budget vs received quantity charts
- tile/stone supplier contacts

Schedule/storage editing is available to normal users when the CENTRAL DB is connected.
Fallback mode remains read-only so data never splits into a temporary local copy.
"""
from datetime import date
import pandas as pd

# -----------------------------------------------------------------------------
# 1. 자재별 현장 반입일정 / 보관위치
# -----------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 📅 자재별 현장 반입 일정")
st.caption("지급자재의 개략 현장반입 예정일, 발주·입고·투입 현황과 보관위치를 한 화면에서 확인합니다.")

_schedule = read("""
SELECT b.id,b.category,b.vendor,b.item_name,b.spec,b.unit,b.budget_qty,
       COALESCE(b.planned_delivery_date,'') AS planned_delivery_date,
       COALESCE(b.storage_location,'') AS storage_location,
       COALESCE(SUM(CASE WHEN t.tx_type='발주' THEN t.qty ELSE 0 END),0) AS ordered,
       COALESCE(SUM(CASE WHEN t.tx_type='입고' THEN t.qty ELSE 0 END),0) AS received,
       COALESCE(SUM(CASE WHEN t.tx_type='투입' THEN t.qty ELSE 0 END),0) AS used
FROM budget_items b
LEFT JOIN transactions t ON b.id=t.item_id
WHERE b.active=1
GROUP BY b.id
ORDER BY CASE WHEN COALESCE(b.planned_delivery_date,'')='' THEN 1 ELSE 0 END,
         b.planned_delivery_date,b.category,b.vendor,b.spec,b.item_name
""")

if len(_schedule):
    _schedule["재고"] = pd.to_numeric(_schedule["received"], errors="coerce").fillna(0) - pd.to_numeric(_schedule["used"], errors="coerce").fillna(0)
    _dates = pd.to_datetime(_schedule["planned_delivery_date"], errors="coerce")
    _today = date.today()

    def _dday(x):
        if pd.isna(x):
            return ""
        days = (x.date() - _today).days
        return f"D-{days}" if days >= 0 else f"D+{abs(days)}"

    _schedule["D-Day"] = [_dday(x) for x in _dates]
    _due7 = int(sum(pd.notna(x) and 0 <= (x.date() - _today).days <= 7 for x in _dates))
    _overdue = int(sum(
        pd.notna(x)
        and (x.date() - _today).days < 0
        and float(_schedule.iloc[i]["received"] or 0) < float(_schedule.iloc[i]["ordered"] or 0)
        for i, x in enumerate(_dates)
    ))
    _no_location = int((_schedule["storage_location"].fillna("").astype(str).str.strip() == "").sum())

    _m1,_m2,_m3,_m4 = st.columns(4)
    _m1.metric("등록 자재", f"{len(_schedule)}종")
    _m2.metric("7일 이내 반입", f"{_due7}건")
    _m3.metric("반입 지연 확인", f"{_overdue}건")
    _m4.metric("보관위치 미등록", f"{_no_location}건")

    _show = _schedule[[
        "category","vendor","item_name","spec","unit","budget_qty",
        "ordered","received","used","재고","planned_delivery_date","D-Day","storage_location"
    ]].copy()
    _show.columns = [
        "공종","협력사","품명","규격","단위","예산수량",
        "누적발주","누적입고","누적투입","현재재고","현장반입 예정일","D-Day","보관위치"
    ]
    st.dataframe(_show, use_container_width=True, hide_index=True)

    st.markdown("#### ✏️ 반입일정 / 보관위치 입력")
    if USE_POSTGRES:
        st.caption("일반 사용자도 수정 가능합니다. 입력 후 저장 버튼을 눌러야 중앙 DB에 반영됩니다.")
        _edit = _schedule[["id","category","vendor","item_name","spec","planned_delivery_date","storage_location"]].copy()
        _edit.columns = ["id","공종","협력사","품명","규격","현장반입 예정일","보관위치"]
        _edit["현장반입 예정일"] = pd.to_datetime(_edit["현장반입 예정일"], errors="coerce").dt.date
        with st.form("overview_supply_schedule_form_v3"):
            _edited = st.data_editor(
                _edit,
                use_container_width=True,
                hide_index=True,
                disabled=["id","공종","협력사","품명","규격"],
                column_config={
                    "id": None,
                    "현장반입 예정일": st.column_config.DateColumn("현장반입 예정일", format="YYYY-MM-DD"),
                    "보관위치": st.column_config.TextColumn("보관위치", help="예: 지하주차장 B2 A구역"),
                },
                key="overview_supply_schedule_editor_v3",
            )
            _save_schedule = st.form_submit_button("반입일정 / 보관위치 저장", type="primary")
        if _save_schedule:
            for _, _r in _edited.iterrows():
                _d = _r["현장반입 예정일"]
                _d = "" if pd.isna(_d) else str(_d)
                _loc = str(_r["보관위치"] or "").strip()
                execute(
                    "UPDATE budget_items SET planned_delivery_date=?,storage_location=? WHERE id=?",
                    (_d,_loc,int(_r["id"])),
                )
            st.success("반입일정과 보관위치를 중앙 DB에 저장했습니다.")
            st.rerun()
    else:
        st.info("현재는 중앙 DB 미연결로 조회만 가능합니다. 중앙 DB가 복구되면 이 표에서 바로 일정/보관위치를 수정할 수 있습니다.")
else:
    st.info("등록된 자재 품목이 없습니다.")

# -----------------------------------------------------------------------------
# 2. 예산 대비 실제 입고량 그래프
# -----------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 📊 예산 대비 입고 현황")
st.caption("예산수량 대비 실제 현장 입고량을 공종·단위별로 비교합니다. 서로 다른 단위는 합산하지 않습니다.")

_totals = get_totals()
if not len(_totals):
    st.info("표시할 예산/입고 데이터가 없습니다.")
else:
    for _category in ["철근","레미콘","타일","석재"]:
        _cat = _totals[_totals["category"] == _category].copy()
        if not len(_cat):
            continue
        st.markdown(f"#### {_category}")
        _cat["예산"] = pd.to_numeric(_cat["budget_qty"], errors="coerce").fillna(0.0)
        _cat["입고"] = pd.to_numeric(_cat["received"], errors="coerce").fillna(0.0)
        _cat["입고율(%)"] = _cat.apply(lambda r: (float(r["입고"]) / float(r["예산"]) * 100.0) if float(r["예산"]) > 0 else 0.0, axis=1)
        _cat["품목"] = _cat.apply(
            lambda r: f"{str(r.get('vendor','') or '').strip() + ' / ' if str(r.get('vendor','') or '').strip() else ''}{r['item_name']} {r['spec']}".strip(),
            axis=1,
        )
        _cat["단위"] = _cat["unit"].fillna("").astype(str).replace("", "단위미지정")
        for _unit, _u in _cat.groupby("단위", dropna=False):
            st.caption(f"단위: {_unit}")
            _chart = _u[["품목","예산","입고"]].copy().set_index("품목")
            st.bar_chart(_chart, use_container_width=True)
            _summary = _u[["품목","예산","입고","입고율(%)"]].copy()
            for _c in ["예산","입고","입고율(%)"]:
                _summary[_c] = pd.to_numeric(_summary[_c], errors="coerce").fillna(0).round(1)
            st.dataframe(_summary, use_container_width=True, hide_index=True)

# -----------------------------------------------------------------------------
# 3. 지급자재 업체 담당자
# -----------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 📞 지급자재 업체 담당자")
st.caption("타일·석재 지급자재 업체의 본사 및 현장 담당자 연락처입니다.")

_seed_contacts = [
    ("타일자재 1", "(주)대동세라믹", "이준혁", "010-8756-0517", "leejh0517@nate.com", "과장", "이준혁", "010-8756-0517", "leejh0517@nate.com"),
    ("타일자재 2", "(주)케이씨씨글라스 수도권영업소", "이재훈", "010-8958-7283", "e-jjang@homecc.com", "대리", "박성용", "010-9934-2710", "sypark5203@homecc.com"),
    ("타일자재 3", "(주)삼현요업공장", "양승진", "010-8906-2549", "y08s03i@hanmail.net", "과장", "양승진", "010-8906-2549", "y08s03i@hanmail.net"),
    ("인조대리석_납품", "LX하우시스", "정재균", "010-8498-5458", "jjkcap@lxhausys.com", "대리", "조범기", "010-5828-5170", "decopia@hanmail.net"),
    ("천연가공석 1_납품 및 설치", "LX하우시스", "정재균", "010-8498-5458", "jjkcap@lxhausys.com", "대리", "조범기", "010-5828-5170", "decopia@hanmail.net"),
    ("천연가공석 2 납품 및 설치", "KCC글라스", "김백용", "010-6899-8071", "", "과장", "김백용", "010-6899-8071", ""),
]
_contact_cols = ["id","category","company","hq_manager","hq_phone","hq_email","position","site_manager","site_phone","site_email"]
_contact_df = pd.DataFrame(columns=_contact_cols)

if USE_POSTGRES:
    execute("""CREATE TABLE IF NOT EXISTS supplier_contacts(
        id SERIAL PRIMARY KEY,
        category TEXT DEFAULT '', company TEXT NOT NULL DEFAULT '',
        hq_manager TEXT DEFAULT '', hq_phone TEXT DEFAULT '', hq_email TEXT DEFAULT '',
        position TEXT DEFAULT '', site_manager TEXT DEFAULT '', site_phone TEXT DEFAULT '', site_email TEXT DEFAULT ''
    )""")
    _count = int(read("SELECT COUNT(*) AS n FROM supplier_contacts").iloc[0]["n"])
    if _count == 0:
        for _r in _seed_contacts:
            execute("""INSERT INTO supplier_contacts(category,company,hq_manager,hq_phone,hq_email,position,site_manager,site_phone,site_email)
                       VALUES(?,?,?,?,?,?,?,?,?)""", _r)
    _contact_df = read("SELECT * FROM supplier_contacts ORDER BY category,company,id")
else:
    # Read-only fallback must never call execute(). If an old local table exists, read it;
    # otherwise show the last known contact list in memory so the section never disappears.
    try:
        _contact_df = read("SELECT * FROM supplier_contacts ORDER BY category,company,id")
    except Exception:
        _contact_df = pd.DataFrame([
            (i+1,) + row for i,row in enumerate(_seed_contacts)
        ], columns=_contact_cols)

_contact_df = _contact_df[_contact_cols].copy() if len(_contact_df) else pd.DataFrame(columns=_contact_cols)

if USE_POSTGRES and is_admin():
    st.caption("관리자는 표에서 직접 수정하고, + 버튼으로 추가하거나 행을 삭제한 뒤 저장할 수 있습니다.")
    _edit = _contact_df.rename(columns={
        "category":"공종", "company":"업체명", "hq_manager":"본사담당자", "hq_phone":"본사 휴대폰",
        "hq_email":"본사 E-Mail", "position":"직책", "site_manager":"현장담당자",
        "site_phone":"현장 휴대폰", "site_email":"현장 E-Mail"
    })
    _edited = st.data_editor(
        _edit, use_container_width=True, hide_index=True, num_rows="dynamic", disabled=["id"],
        column_config={
            "id": None,
            "공종": st.column_config.TextColumn("공종"),
            "업체명": st.column_config.TextColumn("업체명", required=True),
            "본사담당자": st.column_config.TextColumn("본사담당자"),
            "본사 휴대폰": st.column_config.TextColumn("본사 휴대폰"),
            "본사 E-Mail": st.column_config.TextColumn("본사 E-Mail"),
            "직책": st.column_config.TextColumn("직책"),
            "현장담당자": st.column_config.TextColumn("현장담당자"),
            "현장 휴대폰": st.column_config.TextColumn("현장 휴대폰"),
            "현장 E-Mail": st.column_config.TextColumn("현장 E-Mail"),
        }, key="overview_supplier_contacts_editor_v3")

    if st.button("업체 담당자 수정 / 추가 / 삭제 저장", type="primary", key="save_overview_contacts_v3"):
        _old_ids = set(_contact_df["id"].astype(int).tolist()) if len(_contact_df) else set()
        _kept_ids, _errors = set(), []
        for _idx, _r in _edited.iterrows():
            _company = str(_r.get("업체명", "") or "").strip()
            _category = str(_r.get("공종", "") or "").strip()
            _vals = [
                str(_r.get("본사담당자", "") or "").strip(),
                str(_r.get("본사 휴대폰", "") or "").strip(),
                str(_r.get("본사 E-Mail", "") or "").strip(),
                str(_r.get("직책", "") or "").strip(),
                str(_r.get("현장담당자", "") or "").strip(),
                str(_r.get("현장 휴대폰", "") or "").strip(),
                str(_r.get("현장 E-Mail", "") or "").strip(),
            ]
            if not _company and not _category and not any(_vals):
                continue
            if not _company:
                _errors.append(f"{_idx+1}행: 업체명은 필수입니다.")
                continue
            _rid = _r.get("id")
            if pd.notna(_rid):
                _rid = int(_rid); _kept_ids.add(_rid)
                execute("""UPDATE supplier_contacts SET category=?,company=?,hq_manager=?,hq_phone=?,hq_email=?,position=?,site_manager=?,site_phone=?,site_email=? WHERE id=?""",
                        (_category,_company,*_vals,_rid))
            else:
                execute("""INSERT INTO supplier_contacts(category,company,hq_manager,hq_phone,hq_email,position,site_manager,site_phone,site_email) VALUES(?,?,?,?,?,?,?,?,?)""",
                        (_category,_company,*_vals))
        if _errors:
            st.error(" / ".join(_errors))
        else:
            for _rid in _old_ids - _kept_ids:
                execute("DELETE FROM supplier_contacts WHERE id=?", (_rid,))
            st.success("업체 담당자 수정 / 추가 / 삭제가 저장되었습니다.")
            st.rerun()
else:
    _show_contacts = _contact_df.drop(columns=["id"]).rename(columns={
        "category":"공종", "company":"업체명", "hq_manager":"본사담당자", "hq_phone":"본사 휴대폰",
        "hq_email":"본사 E-Mail", "position":"직책", "site_manager":"현장담당자",
        "site_phone":"현장 휴대폰", "site_email":"현장 E-Mail"
    })
    st.dataframe(_show_contacts, use_container_width=True, hide_index=True)
    if not USE_POSTGRES:
        st.caption("※ 중앙 DB 미연결 시 연락처는 마지막 확인 가능한 값으로 표시됩니다. 수정은 중앙 DB 연결 후 가능합니다.")
