"""Smart Material Manager stable entrypoint.
Uses a repository-pinned application snapshot so deployment does not depend on runtime
GitHub fetches or the central DB being available during startup.
"""
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("app_snapshot.py")
source = SNAPSHOT.read_text(encoding="utf-8")

# 안정화 1단계: 중앙 DB 장애가 사이트 전체를 막지 않도록 백업 DB로 고정 실행.
source = source.replace(
    "DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)",
    "DATABASE_URL = ''\nUSE_POSTGRES = False",
    1,
)

# 석재는 원래 기능이 들어있는 v2 화면을 안정화 래퍼를 통해 실행.
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
    'st.caption("🛡 안정화 모드 · 백업 DB")\nst.info("현재 사이트 안정화를 위해 백업 DB 모드로 운영 중입니다. 기존 기능은 유지하고 중앙 DB만 별도 복구합니다.")',
    1,
)

# 관리자 설정은 여러 행을 한 번에 추가/수정/삭제 후 한 번에 저장하는 방식으로 복구.
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
            key="admin_bulk_budget_editor_v3",
        )

        if st.button("예산 / 품목 전체 저장", type="primary", key="admin_bulk_save_v3"):
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
        st.caption("철근·레미콘·타일·석재 발주서를 한곳에서 확인하고 여러 건을 선택해 삭제할 수 있습니다. 삭제하면 해당 발주 품목·첨부파일·발주 누계도 함께 제거됩니다.")

        admin_orders = read(
            """SELECT o.id,o.order_no,o.category,o.vendor,o.order_date,
                      o.partner_confirm,o.internal_approval,o.order_complete,
                      (SELECT COUNT(*) FROM order_lines ol WHERE ol.order_id=o.id) AS item_count
               FROM orders o
               ORDER BY o.id DESC"""
        )

        if not len(admin_orders):
            st.info("저장된 발주서가 없습니다.")
        else:
            order_manage = admin_orders.copy()
            order_manage["상태"] = order_manage.apply(
                lambda r: "발주완료" if int(r["order_complete"] or 0)
                else "결재완료" if int(r["internal_approval"] or 0)
                else "협력사 확인완료" if int(r["partner_confirm"] or 0)
                else "결재/확인중",
                axis=1,
            )
            order_manage = order_manage[["id","order_no","category","vendor","order_date","item_count","상태"]]
            order_manage.columns = ["id","발주번호","공종","협력사","발주일","품목수","상태"]
            order_manage["삭제"] = False

            delete_edit = st.data_editor(
                order_manage,
                use_container_width=True,
                hide_index=True,
                disabled=["id","발주번호","공종","협력사","발주일","품목수","상태"],
                column_config={
                    "id": None,
                    "삭제": st.column_config.CheckboxColumn("삭제 선택", default=False),
                },
                key="admin_saved_order_delete_editor_v1",
            )

            selected_orders = delete_edit[delete_edit["삭제"] == True].copy()
            if len(selected_orders):
                st.caption(f"삭제 선택: {len(selected_orders)}건")

            confirm_order_delete = st.checkbox(
                "선택한 발주서를 실제로 삭제합니다.",
                key="admin_saved_order_delete_confirm_v1",
            )

            if st.button("선택 발주서 삭제", key="admin_saved_order_delete_button_v1"):
                if not len(selected_orders):
                    st.warning("삭제할 발주서를 먼저 선택해주세요.")
                elif not confirm_order_delete:
                    st.warning("삭제 확인을 체크해주세요.")
                else:
                    deleted_count = 0
                    with sqlite3.connect(DB) as c:
                        existing_tables = {
                            row[0]
                            for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                        }
                        for _, order_row in selected_orders.iterrows():
                            oid = int(order_row["id"])
                            order_no = str(order_row["발주번호"])
                            if "order_attachments" in existing_tables:
                                c.execute("DELETE FROM order_attachments WHERE order_id=?", (oid,))
                            c.execute("DELETE FROM order_lines WHERE order_id=?", (oid,))
                            c.execute(
                                "DELETE FROM transactions WHERE tx_type='발주' AND note LIKE ?",
                                (f"%{order_no}%",),
                            )
                            c.execute("DELETE FROM orders WHERE id=?", (oid,))
                            deleted_count += 1
                        c.commit()

                    st.success(f"선택한 발주서 {deleted_count}건을 삭제했습니다.")
                    st.rerun()

        st.markdown("---")
        st.markdown("### 관리자 비밀번호 변경")
        p1 = st.text_input("새 비밀번호", type="password", key="admin_pw1_v3")
        p2 = st.text_input("새 비밀번호 확인", type="password", key="admin_pw2_v3")
        if st.button("비밀번호 변경", key="admin_pw_change_v3"):
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
