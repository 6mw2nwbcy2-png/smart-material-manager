"""Extra overview widgets for Smart Material Manager.
This module is intentionally read-only: it only displays contact information and
aggregated budget/usage/remaining charts, so a rendering problem here cannot alter DB data.
"""

st.markdown("---")
st.markdown("### 지급자재 업체 담당자")
st.caption("타일·석재 지급자재 업체의 본사 및 현장 담당자 연락처입니다.")

contacts = pd.DataFrame([
    {
        "공종": "타일자재 1",
        "업체명": "(주)대동세라믹",
        "본사담당자": "이준혁",
        "본사 휴대폰": "010-8756-0517",
        "본사 E-Mail": "leejh0517@nate.com",
        "직책": "과장",
        "현장담당자": "이준혁",
        "현장 휴대폰": "010-8756-0517",
        "현장 E-Mail": "leejh0517@nate.com",
    },
    {
        "공종": "타일자재 2",
        "업체명": "(주)케이씨씨글라스 수도권영업소",
        "본사담당자": "이재훈",
        "본사 휴대폰": "010-8958-7283",
        "본사 E-Mail": "e-jjang@homecc.com",
        "직책": "대리",
        "현장담당자": "박성용",
        "현장 휴대폰": "010-9934-2710",
        "현장 E-Mail": "sypark5203@homecc.com",
    },
    {
        "공종": "타일자재 3",
        "업체명": "(주)삼현요업공장",
        "본사담당자": "양승진",
        "본사 휴대폰": "010-8906-2549",
        "본사 E-Mail": "y08s03i@hanmail.net",
        "직책": "과장",
        "현장담당자": "양승진",
        "현장 휴대폰": "010-8906-2549",
        "현장 E-Mail": "y08s03i@hanmail.net",
    },
    {
        "공종": "인조대리석_납품",
        "업체명": "LX하우시스",
        "본사담당자": "정재균",
        "본사 휴대폰": "010-8498-5458",
        "본사 E-Mail": "jjkcap@lxhausys.com",
        "직책": "대리",
        "현장담당자": "조범기",
        "현장 휴대폰": "010-5828-5170",
        "현장 E-Mail": "decopia@hanmail.net",
    },
    {
        "공종": "천연가공석 1_납품 및 설치",
        "업체명": "LX하우시스",
        "본사담당자": "정재균",
        "본사 휴대폰": "010-8498-5458",
        "본사 E-Mail": "jjkcap@lxhausys.com",
        "직책": "대리",
        "현장담당자": "조범기",
        "현장 휴대폰": "010-5828-5170",
        "현장 E-Mail": "decopia@hanmail.net",
    },
    {
        "공종": "천연가공석 2 납품 및 설치",
        "업체명": "KCC글라스",
        "본사담당자": "김백용",
        "본사 휴대폰": "010-6899-8071",
        "본사 E-Mail": "",
        "직책": "과장",
        "현장담당자": "김백용",
        "현장 휴대폰": "010-6899-8071",
        "현장 E-Mail": "",
    },
])

st.dataframe(
    contacts,
    use_container_width=True,
    hide_index=True,
    column_config={
        "본사 E-Mail": st.column_config.LinkColumn("본사 E-Mail", display_text=r".*"),
        "현장 E-Mail": st.column_config.LinkColumn("현장 E-Mail", display_text=r".*"),
    },
)

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
        _summary = (
            _u.groupby("업체", as_index=False)[["예산", "투입", "잔여"]]
            .sum()
            .sort_values("예산", ascending=False)
        )
        st.caption(f"단위: {_unit}")
        st.bar_chart(
            _summary.set_index("업체")[["예산", "투입", "잔여"]],
            use_container_width=True,
        )
        _show = _summary.copy()
        for _c in ["예산", "투입", "잔여"]:
            _show[_c] = _show[_c].round(2)
        st.dataframe(_show, use_container_width=True, hide_index=True)
