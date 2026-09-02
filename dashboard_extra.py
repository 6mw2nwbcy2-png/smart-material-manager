"""Extra overview widgets for Smart Material Manager.
Contacts are DB-backed so admins can add/edit/delete them and all users see the same data.
"""

st.markdown("---")
st.markdown("### 지급자재 업체 담당자")
st.caption("타일·석재 지급자재 업체의 본사 및 현장 담당자 연락처입니다.")

if USE_POSTGRES:
    execute("""CREATE TABLE IF NOT EXISTS supplier_contacts(
        id SERIAL PRIMARY KEY,
        category TEXT DEFAULT '', company TEXT NOT NULL DEFAULT '',
        hq_manager TEXT DEFAULT '', hq_phone TEXT DEFAULT '', hq_email TEXT DEFAULT '',
        position TEXT DEFAULT '', site_manager TEXT DEFAULT '', site_phone TEXT DEFAULT '', site_email TEXT DEFAULT ''
    )""")
else:
    execute("""CREATE TABLE IF NOT EXISTS supplier_contacts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT DEFAULT '', company TEXT NOT NULL DEFAULT '',
        hq_manager TEXT DEFAULT '', hq_phone TEXT DEFAULT '', hq_email TEXT DEFAULT '',
        position TEXT DEFAULT '', site_manager TEXT DEFAULT '', site_phone TEXT DEFAULT '', site_email TEXT DEFAULT ''
    )""")

_count = int(read("SELECT COUNT(*) AS n FROM supplier_contacts").iloc[0]["n"])
if _count == 0:
    _seed_contacts = [
        ("타일자재 1", "(주)대동세라믹", "이준혁", "010-8756-0517", "leejh0517@nate.com", "과장", "이준혁", "010-8756-0517", "leejh0517@nate.com"),
        ("타일자재 2", "(주)케이씨씨글라스 수도권영업소", "이재훈", "010-8958-7283", "e-jjang@homecc.com", "대리", "박성용", "010-9934-2710", "sypark5203@homecc.com"),
        ("타일자재 3", "(주)삼현요업공장", "양승진", "010-8906-2549", "y08s03i@hanmail.net", "과장", "양승진", "010-8906-2549", "y08s03i@hanmail.net"),
        ("인조대리석_납품", "LX하우시스", "정재균", "010-8498-5458", "jjkcap@lxhausys.com", "대리", "조범기", "010-5828-5170", "decopia@hanmail.net"),
        ("천연가공석 1_납품 및 설치", "LX하우시스", "정재균", "010-8498-5458", "jjkcap@lxhausys.com", "대리", "조범기", "010-5828-5170", "decopia@hanmail.net"),
        ("천연가공석 2 납품 및 설치", "KCC글라스", "김백용", "010-6899-8071", "", "과장", "김백용", "010-6899-8071", ""),
    ]
    for _r in _seed_contacts:
        execute("""INSERT INTO supplier_contacts(category,company,hq_manager,hq_phone,hq_email,position,site_manager,site_phone,site_email)
                   VALUES(?,?,?,?,?,?,?,?,?)""", _r)

_contact_df = read("SELECT * FROM supplier_contacts ORDER BY category,company,id")
_cols = ["id","category","company","hq_manager","hq_phone","hq_email","position","site_manager","site_phone","site_email"]
_contact_df = _contact_df[_cols].copy() if len(_contact_df) else pd.DataFrame(columns=_cols)

if is_admin():
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
        }, key="overview_supplier_contacts_editor_v2")

    if st.button("업체 담당자 수정 / 추가 / 삭제 저장", type="primary", key="save_overview_contacts_v2"):
        _old_ids = set(_contact_df["id"].astype(int).tolist()) if len(_contact_df) else set()
        _kept_ids, _errors = set(), []
        for _idx, _r in _edited.iterrows():
            _company = str(_r.get("업체명", "") or "").strip()
            _category = str(_r.get("공종", "") or "").strip()
            _hq_manager = str(_r.get("본사담당자", "") or "").strip()
            _hq_phone = str(_r.get("본사 휴대폰", "") or "").strip()
            _hq_email = str(_r.get("본사 E-Mail", "") or "").strip()
            _position = str(_r.get("직책", "") or "").strip()
            _site_manager = str(_r.get("현장담당자", "") or "").strip()
            _site_phone = str(_r.get("현장 휴대폰", "") or "").strip()
            _site_email = str(_r.get("현장 E-Mail", "") or "").strip()
            if not any([_company,_category,_hq_manager,_hq_phone,_hq_email,_position,_site_manager,_site_phone,_site_email]):
                continue
            if not _company:
                _errors.append(f"{_idx+1}행: 업체명은 필수입니다.")
                continue
            _rid = _r.get("id")
            if pd.notna(_rid):
                _rid = int(_rid); _kept_ids.add(_rid)
                execute("""UPDATE supplier_contacts SET category=?,company=?,hq_manager=?,hq_phone=?,hq_email=?,position=?,site_manager=?,site_phone=?,site_email=? WHERE id=?""",
                        (_category,_company,_hq_manager,_hq_phone,_hq_email,_position,_site_manager,_site_phone,_site_email,_rid))
            else:
                execute("""INSERT INTO supplier_contacts(category,company,hq_manager,hq_phone,hq_email,position,site_manager,site_phone,site_email) VALUES(?,?,?,?,?,?,?,?,?)""",
                        (_category,_company,_hq_manager,_hq_phone,_hq_email,_position,_site_manager,_site_phone,_site_email))
        if _errors:
            st.error(" / ".join(_errors))
        else:
            for _rid in _old_ids - _kept_ids:
                execute("DELETE FROM supplier_contacts WHERE id=?", (_rid,))
            st.success("업체 담당자 수정 / 추가 / 삭제가 저장되었습니다.")
            st.rerun()
else:
    _show = _contact_df.drop(columns=["id"]).rename(columns={
        "category":"공종", "company":"업체명", "hq_manager":"본사담당자", "hq_phone":"본사 휴대폰",
        "hq_email":"본사 E-Mail", "position":"직책", "site_manager":"현장담당자",
        "site_phone":"현장 휴대폰", "site_email":"현장 E-Mail"
    })
    st.dataframe(_show, use_container_width=True, hide_index=True)

st.markdown("---")
st.markdown("### 타일 · 석재 업체별 예산 / 투입 / 잔여")
st.caption("예산수량 대비 누적 투입량과 잔여수량을 업체별로 비교합니다. 단위가 다른 품목은 단위별로 분리해 표시합니다.")

_all = get_totals()
for _category in ["타일", "석재"]:
    _cat = _all[_all["category"] == _category].copy() if len(_all) else pd.DataFrame()
    st.markdown(f"#### {_category}")
    if not len(_cat):
        st.info(f"등록된 {_category} 품목이 없습니다.")
        continue
    _cat["업체"] = _cat["vendor"].fillna("").astype(str).str.strip().replace("", "미지정")
    _cat["예산"] = pd.to_numeric(_cat["budget_qty"], errors="coerce").fillna(0.0)
    _cat["투입"] = pd.to_numeric(_cat["used"], errors="coerce").fillna(0.0)
    _cat["잔여"] = (_cat["예산"] - _cat["투입"]).clip(lower=0)
    _cat["단위"] = _cat["unit"].fillna("").astype(str).replace("", "단위미지정")
    for _unit, _u in _cat.groupby("단위", dropna=False):
        _summary = _u.groupby("업체", as_index=False)[["예산", "투입", "잔여"]].sum().sort_values("예산", ascending=False)
        st.caption(f"단위: {_unit}")
        st.bar_chart(_summary.set_index("업체")[["예산", "투입", "잔여"]], use_container_width=True)
        _show_summary = _summary.copy()
        for _c in ["예산", "투입", "잔여"]:
            _show_summary[_c] = _show_summary[_c].round(2)
        st.dataframe(_show_summary, use_container_width=True, hide_index=True)
