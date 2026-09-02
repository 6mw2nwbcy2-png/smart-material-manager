"""Smart Material Manager stable entrypoint.
Central DB is preferred so the original budget/order data is shown again.
If the central DB is temporarily unavailable, the app falls back to the repository
SQLite backup instead of crashing.
"""
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("app_snapshot.py")
source = SNAPSHOT.read_text(encoding="utf-8")

# 중앙 DB 우선 + 연결 실패 시에만 백업 DB 자동 전환.
source = source.replace(
    "DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)",
    '''DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)\nCENTRAL_DB_FALLBACK = False\n\nif USE_POSTGRES:\n    _probe = None\n    try:\n        _probe = psycopg2.connect(DATABASE_URL, connect_timeout=5)\n    except Exception:\n        USE_POSTGRES = False\n        CENTRAL_DB_FALLBACK = True\n    finally:\n        if _probe is not None:\n            try:\n                _probe.close()\n            except Exception:\n                pass''',
    1,
)

# 석재는 안정화 래퍼를 통해 실행.
source = source.replace(
    'runpy.run_path("pages/stone_impl.py", run_name="__main__")',
    'runpy.run_path("pages/4_Stone.py", run_name="__main__")',
)
source = source.replace(
    'runpy.run_path("pages/stone_impl_v2.py", run_name="__main__")',
    'runpy.run_path("pages/4_Stone.py", run_name="__main__")',
)

source = source.replace(
    'st.caption("☁ 중앙 DB 연결" if USE_POSTGRES else "💻 로컬 SQLite 모드")',
    '''st.caption("☁ 중앙 DB 연결" if USE_POSTGRES else "🛟 백업 DB 모드")\nif CENTRAL_DB_FALLBACK:\n    st.warning("중앙 DB 연결이 일시적으로 불가하여 백업 DB로 표시 중입니다. 중앙 DB가 정상화되면 기존 예산/발주 내역이 다시 표시됩니다.")''',
    1,
)

# 한눈에 보기 확장 화면 유지.
overview_anchor = '    st.info("일반 사용자는 자재 투입수량을 입력할 수 있고, 예산/품목/입고/발주상태 수정은 관리자만 가능합니다.")'
overview_extra = overview_anchor + '''\n\n    try:\n        _extra = Path("dashboard_extra.py")\n        exec(compile(_extra.read_text(encoding="utf-8"), str(_extra), "exec"), globals(), globals())\n    except Exception as _overview_error:\n        st.warning(f"담당자/업체별 현황을 표시하지 못했습니다: {_overview_error}")'''
source = source.replace(overview_anchor, overview_extra, 1)

# 관리자 설정: 예산/품목 일괄관리 + 저장된 발주서 상태/삭제.
admin_marker = 'elif menu == "관리자 설정":'
pos = source.find(admin_marker)
if pos >= 0:
    admin_block = '''elif menu == "관리자 설정":
    st.subheader("관리자 설정")
    if not is_admin():
        st.warning("관리자 로그인 후 사용할 수 있습니다.")
    else:
        st.markdown("### 예산 / 품목 관리")
        st.caption("철근·레미콘·타일·석재를 한 표에서 여러 행 추가/수정/삭제한 뒤 저장 버튼 한 번으로 반영합니다.")

        items = read("SELECT * FROM budget_items WHERE active=1 ORDER BY category,vendor,spec,item_name")
        edit_cols = ["id","category","vendor","item_name","spec","unit","budget_qty","tile_type","application_type","default_destination"]
        base = items[edit_cols].copy() if len(items) else pd.DataFrame(columns=edit_cols)

        edited = st.data_editor(
            base,
            use_container_width=True,
            hide_index=True,
            disabled=["id"],
            num_rows="dynamic",
            column_config={
                "id": None,
                "category": st.column_config.SelectboxColumn("공종", options=["철근","레미콘","타일","석재"], required=True),
                "vendor": st.column_config.TextColumn("협력사"),
                "item_name": st.column_config.TextColumn("품명", required=True),
                "spec": st.column_config.TextColumn("규격"),
                "unit": st.column_config.TextColumn("단위", required=True),
                "budget_qty": st.column_config.NumberColumn("예산수량", min_value=0.0, step=0.1),
                "tile_type": st.column_config.TextColumn("타일/석재구분"),
                "application_type": st.column_config.TextColumn("적용구분"),
                "default_destination": st.column_config.TextColumn("기본납품처"),
            },
            key="admin_bulk_budget_editor_v5",
        )

        if st.button("예산 / 품목 전체 저장", type="primary", key="admin_bulk_save_v5"):
            current_ids = set(items["id"].astype(int).tolist()) if len(items) else set()
            edited_ids = set()
            seen = set()
            errors = []

            for idx, r in edited.iterrows():
                category = str(r.get("category", "") or "").strip()
                item_name = str(r.get("item_name", "") or "").strip()
                spec = str(r.get("spec", "") or "").strip()
                unit = str(r.get("unit", "") or "").strip()
                vendor = str(r.get("vendor", "") or "").strip()
                tile_type = str(r.get("tile_type", "") or "").strip()
                application_type = str(r.get("application_type", "") or "").strip()
                default_destination = str(r.get("default_destination", "") or "").strip()
                budget_qty = float(r.get("budget_qty", 0) or 0)

                if not category and not item_name and not unit:
                    continue
                if not category or not item_name or not unit:
                    errors.append(f"{idx+1}행: 공종·품명·단위는 필수입니다.")
                    continue

                key = (category, item_name, spec)
                if key in seen:
                    errors.append(f"{idx+1}행: 같은 공종/품명/규격이 중복되었습니다.")
                    continue
                seen.add(key)

                if category == "타일" and not default_destination:
                    default_destination = calc_destination(tile_type, application_type)
                if category == "석재":
                    if not tile_type:
                        tile_type = "인조석"
                    if not default_destination:
                        default_destination = "현장"

                rid = r.get("id")
                if pd.notna(rid):
                    rid = int(rid)
                    edited_ids.add(rid)
                    execute(
                        """UPDATE budget_items
                           SET category=?,vendor=?,item_name=?,spec=?,unit=?,budget_qty=?,
                               tile_type=?,application_type=?,default_destination=?,active=1
                           WHERE id=?""",
                        (category,vendor,item_name,spec,unit,budget_qty,tile_type,
                         application_type,default_destination,rid),
                    )
                else:
                    dup = read(
                        "SELECT id FROM budget_items WHERE category=? AND item_name=? AND spec=? AND active=1",
                        (category,item_name,spec),
                    )
                    if len(dup):
                        errors.append(f"{idx+1}행: 이미 등록된 품목입니다.")
                        continue
                    execute(
                        """INSERT INTO budget_items(
                           category,vendor,item_name,spec,unit,budget_qty,
                           tile_type,application_type,default_destination,active)
                           VALUES(?,?,?,?,?,?,?,?,?,1)""",
                        (category,vendor,item_name,spec,unit,budget_qty,tile_type,
                         application_type,default_destination),
                    )

            if errors:
                st.error("저장하지 못한 행이 있습니다: " + " / ".join(errors))
            else:
                for rid in current_ids - edited_ids:
                    execute("UPDATE budget_items SET active=0 WHERE id=?", (rid,))
                st.success("예산 / 품목 전체 저장 완료")
                st.rerun()

        st.markdown("---")
        st.markdown("### 저장된 발주서 관리 / 삭제")
        st.caption("발주서 상태를 수정하거나 저장된 발주서를 삭제할 수 있습니다.")
        admin_orders = read("SELECT * FROM orders ORDER BY id DESC")

        if not len(admin_orders):
            st.info("저장된 발주서가 없습니다.")
        else:
            for _, o in admin_orders.iterrows():
                status = "발주완료" if int(o.order_complete or 0) else "결재완료" if int(o.internal_approval or 0) else "협력사 확인완료" if int(o.partner_confirm or 0) else "진행중"
                with st.expander(f"{o.order_no} | {o.category} | {o.vendor} | {status}"):
                    c1, c2, c3 = st.columns(3)
                    pc = c1.checkbox("협력사 확인", value=bool(o.partner_confirm), key=f"adm_pc_{o.id}")
                    ia = c2.checkbox("결재 완료", value=bool(o.internal_approval), key=f"adm_ia_{o.id}")
                    oc = c3.checkbox("발주 완료", value=bool(o.order_complete), key=f"adm_oc_{o.id}")

                    b1, b2 = st.columns(2)
                    if b1.button("상태 저장", key=f"adm_order_save_{o.id}", type="primary"):
                        execute(
                            "UPDATE orders SET partner_confirm=?,internal_approval=?,order_complete=? WHERE id=?",
                            (int(pc), int(ia), int(oc), int(o.id)),
                        )
                        st.success("발주서 상태 저장 완료")
                        st.rerun()

                    delete_ok = b2.checkbox("삭제 확인", key=f"adm_delete_confirm_{o.id}")
                    if b2.button("발주서 삭제", key=f"adm_order_delete_{o.id}", disabled=not delete_ok):
                        oid = int(o.id)
                        order_no = str(o.order_no)
                        try:
                            execute("DELETE FROM order_attachments WHERE order_id=?", (oid,))
                        except Exception:
                            pass
                        try:
                            execute("DELETE FROM transactions WHERE tx_type='발주' AND note LIKE ?", (f"%{order_no}%",))
                        except Exception:
                            pass
                        execute("DELETE FROM order_lines WHERE order_id=?", (oid,))
                        execute("DELETE FROM orders WHERE id=?", (oid,))
                        st.success(f"{order_no} 발주서 삭제 완료")
                        st.rerun()

        st.markdown("---")
        st.markdown("### 관리자 비밀번호 변경")
        p1 = st.text_input("새 비밀번호", type="password", key="admin_pw1_v5")
        p2 = st.text_input("새 비밀번호 확인", type="password", key="admin_pw2_v5")
        if st.button("비밀번호 변경", key="admin_pw_change_v5"):
            if len(p1) < 4:
                st.warning("4자리 이상 입력하세요.")
            elif p1 != p2:
                st.warning("비밀번호가 서로 다릅니다.")
            else:
                execute("UPDATE settings SET value=? WHERE key='admin_password'", (sha(p1),))
                st.success("비밀번호 변경 완료")
'''
    source = source[:pos] + admin_block

exec(compile(source, str(SNAPSHOT), "exec"), globals(), globals())
