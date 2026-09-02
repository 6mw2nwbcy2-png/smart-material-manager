"""Administrator settings UI.

This module is executed inside app.py's global context. It intentionally contains no
hard-delete SQL. Saved orders are soft-deleted and recoverable.
"""

st.subheader("관리자 설정")

if not is_admin():
    st.warning("관리자 로그인 후 사용할 수 있습니다.")
else:
    st.success("☁ 중앙 DB 영구저장 모드: 앱 업데이트와 데이터 저장소를 분리했습니다.")
    st.caption("발주서 삭제는 실제 삭제가 아니라 보관 처리되며 언제든 복구할 수 있습니다.")

    def _text(value):
        if value is None or (hasattr(pd, "isna") and pd.isna(value)):
            return ""
        return str(value).strip()

    def _atomic(operations):
        """Run related DB writes as one transaction."""
        if USE_POSTGRES:
            with db_connect() as c:
                try:
                    with c.cursor() as cur:
                        for sql, params in operations:
                            cur.execute(_pg_sql(sql), params)
                    c.commit()
                except Exception:
                    c.rollback()
                    raise
        else:
            with sqlite3.connect(DB) as c:
                try:
                    for sql, params in operations:
                        c.execute(sql, params)
                    c.commit()
                except Exception:
                    c.rollback()
                    raise

    # ------------------------------------------------------------------
    # 예산 / 품목 관리
    # ------------------------------------------------------------------
    st.markdown("### 예산 / 품목 관리")
    st.caption("철근·레미콘·타일·석재를 한 표에서 여러 행 추가/수정/삭제한 뒤 저장 버튼 한 번으로 반영합니다.")

    items = read("SELECT * FROM budget_items WHERE active=1 ORDER BY category,vendor,spec,item_name")
    edit_cols = [
        "id", "category", "vendor", "item_name", "spec", "unit", "budget_qty",
        "tile_type", "application_type", "default_destination"
    ]
    base = items[edit_cols].copy() if len(items) else pd.DataFrame(columns=edit_cols)

    edited = st.data_editor(
        base,
        width="stretch",
        hide_index=True,
        disabled=["id"],
        num_rows="dynamic",
        column_config={
            "id": None,
            "category": st.column_config.SelectboxColumn("공종", options=["철근", "레미콘", "타일", "석재"], required=True),
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
        normalized = []
        errors = []

        # Validate everything first so a bad row cannot cause partial saving.
        for idx, row in edited.iterrows():
            category = _text(row.get("category"))
            vendor = _text(row.get("vendor"))
            item_name = _text(row.get("item_name"))
            spec = _text(row.get("spec"))
            unit = _text(row.get("unit"))
            tile_type = _text(row.get("tile_type"))
            application_type = _text(row.get("application_type"))
            default_destination = _text(row.get("default_destination"))
            try:
                budget_qty = float(row.get("budget_qty", 0) or 0)
            except Exception:
                budget_qty = -1

            if not category and not item_name and not unit:
                continue
            if not category or not item_name or not unit:
                errors.append(f"{idx + 1}행: 공종·품명·단위는 필수입니다.")
                continue
            if budget_qty < 0:
                errors.append(f"{idx + 1}행: 예산수량을 확인해주세요.")
                continue

            duplicate_key = (category, item_name, spec)
            if duplicate_key in seen:
                errors.append(f"{idx + 1}행: 같은 공종/품명/규격이 중복되었습니다.")
                continue
            seen.add(duplicate_key)

            if category == "타일" and not default_destination:
                default_destination = calc_destination(tile_type, application_type)
            if category == "석재":
                if not tile_type:
                    tile_type = "인조석"
                if not default_destination:
                    default_destination = "현장"

            rid = row.get("id")
            rid = int(rid) if pd.notna(rid) else None
            if rid is not None:
                edited_ids.add(rid)

            normalized.append({
                "id": rid,
                "category": category,
                "vendor": vendor,
                "item_name": item_name,
                "spec": spec,
                "unit": unit,
                "budget_qty": budget_qty,
                "tile_type": tile_type,
                "application_type": application_type,
                "default_destination": default_destination,
            })

        if errors:
            st.error("저장하지 못했습니다. 먼저 아래 항목을 수정해주세요: " + " / ".join(errors))
        else:
            operations = []
            duplicate_error = None
            for row in normalized:
                if row["id"] is not None:
                    operations.append((
                        """UPDATE budget_items
                           SET category=?,vendor=?,item_name=?,spec=?,unit=?,budget_qty=?,
                               tile_type=?,application_type=?,default_destination=?,active=1
                           WHERE id=?""",
                        (
                            row["category"], row["vendor"], row["item_name"], row["spec"], row["unit"],
                            row["budget_qty"], row["tile_type"], row["application_type"],
                            row["default_destination"], row["id"],
                        ),
                    ))
                else:
                    dup = read(
                        "SELECT id FROM budget_items WHERE category=? AND item_name=? AND spec=? AND active=1",
                        (row["category"], row["item_name"], row["spec"]),
                    )
                    if len(dup):
                        duplicate_error = f"이미 등록된 품목입니다: {row['category']} / {row['item_name']} / {row['spec']}"
                        break
                    operations.append((
                        """INSERT INTO budget_items(
                           category,vendor,item_name,spec,unit,budget_qty,
                           tile_type,application_type,default_destination,active)
                           VALUES(?,?,?,?,?,?,?,?,?,1)""",
                        (
                            row["category"], row["vendor"], row["item_name"], row["spec"], row["unit"],
                            row["budget_qty"], row["tile_type"], row["application_type"],
                            row["default_destination"],
                        ),
                    ))

            if duplicate_error:
                st.error(duplicate_error)
            else:
                for rid in current_ids - edited_ids:
                    operations.append(("UPDATE budget_items SET active=0 WHERE id=?", (rid,)))
                try:
                    _atomic(operations)
                    log_change("BULK_SAVE", "budget_items", "", f"rows={len(normalized)}; deactivated={len(current_ids - edited_ids)}")
                    st.success("예산 / 품목 전체 저장 완료")
                    st.rerun()
                except Exception as exc:
                    st.error(f"저장 중 오류가 발생하여 전체 작업을 취소했습니다: {exc}")

    # ------------------------------------------------------------------
    # 발주서 관리
    # ------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 발주서 관리")
    st.caption("저장된 모든 공종 발주서를 관리자가 상태 변경하거나 삭제(보관)할 수 있습니다.")

    admin_orders = read(
        """SELECT id,order_no,category,vendor,order_date,partner_confirm,internal_approval,order_complete,note
           FROM orders
           WHERE COALESCE(deleted_at,'')=''
           ORDER BY id DESC LIMIT 300"""
    )

    if not len(admin_orders):
        st.info("저장된 발주서가 없습니다.")
    else:
        order_labels = {
            f"{row.order_no} | {row.category} | {row.vendor} | {row.order_date}": int(row.id)
            for _, row in admin_orders.iterrows()
        }
        selected_label = st.selectbox("관리할 발주서", list(order_labels.keys()), key="admin_order_select_v5")
        selected_id = order_labels[selected_label]
        selected_order = admin_orders[admin_orders.id == selected_id].iloc[0]

        st.write(
            f"**발주번호:** {selected_order.order_no}  ·  **공종:** {selected_order.category}  ·  "
            f"**협력사:** {selected_order.vendor}  ·  **발주일:** {selected_order.order_date}"
        )

        s1, s2, s3 = st.columns(3)
        admin_partner = s1.checkbox("협력사 확인", value=bool(selected_order.partner_confirm), key=f"admin_partner_{selected_id}")
        admin_approval = s2.checkbox("결재 완료", value=bool(selected_order.internal_approval), key=f"admin_approval_{selected_id}")
        admin_complete = s3.checkbox("발주 완료", value=bool(selected_order.order_complete), key=f"admin_complete_{selected_id}")

        a1, a2 = st.columns(2)
        if a1.button("발주 상태 저장", type="primary", key=f"admin_order_status_{selected_id}"):
            execute(
                "UPDATE orders SET partner_confirm=?,internal_approval=?,order_complete=? WHERE id=?",
                (int(admin_partner), int(admin_approval), int(admin_complete), selected_id),
            )
            log_change("STATUS_UPDATE", "order", selected_id, f"order_no={selected_order.order_no}")
            st.success("발주 상태 저장 완료")
            st.rerun()

        delete_confirm = a2.checkbox("삭제 확인", key=f"admin_order_delete_confirm_{selected_id}")
        if a2.button("발주서 삭제(보관)", key=f"admin_order_delete_{selected_id}"):
            if not delete_confirm:
                st.warning("삭제 확인을 먼저 체크해주세요.")
            else:
                deleted_at = pd.Timestamp.now().isoformat()
                order_no = str(selected_order.order_no)
                try:
                    _atomic([
                        ("UPDATE orders SET deleted_at=?,deleted_by=? WHERE id=?", (deleted_at, "관리자", selected_id)),
                        (
                            "UPDATE transactions SET deleted_at=?,deleted_by=? WHERE (order_id=? OR (tx_type='발주' AND note LIKE ?))",
                            (deleted_at, "관리자", selected_id, f"%{order_no}%"),
                        ),
                    ])
                    log_change("SOFT_DELETE", "order", selected_id, f"order_no={order_no}")
                    st.success(f"{order_no} 발주서를 삭제 보관함으로 이동했습니다. 품목·첨부파일 원본은 그대로 보존됩니다.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"삭제 보관 처리 중 오류가 발생하여 취소했습니다: {exc}")

    with st.expander("🗃 삭제 발주서 복구"):
        deleted_orders = read(
            """SELECT id,order_no,category,vendor,order_date,deleted_at
               FROM orders
               WHERE COALESCE(deleted_at,'')<>''
               ORDER BY id DESC LIMIT 300"""
        )
        if not len(deleted_orders):
            st.caption("삭제 보관된 발주서가 없습니다.")
        else:
            restore_labels = {
                f"{row.order_no} | {row.category} | {row.vendor} | 삭제 {row.deleted_at}": int(row.id)
                for _, row in deleted_orders.iterrows()
            }
            restore_label = st.selectbox("복구할 발주서", list(restore_labels.keys()), key="admin_restore_order_select_v5")
            restore_id = restore_labels[restore_label]
            restore_row = deleted_orders[deleted_orders.id == restore_id].iloc[0]
            if st.button("발주서 복구", key=f"admin_restore_order_{restore_id}"):
                order_no = str(restore_row.order_no)
                try:
                    _atomic([
                        ("UPDATE orders SET deleted_at='',deleted_by='' WHERE id=?", (restore_id,)),
                        (
                            "UPDATE transactions SET deleted_at='',deleted_by='' WHERE (order_id=? OR (tx_type='발주' AND note LIKE ?))",
                            (restore_id, f"%{order_no}%"),
                        ),
                    ])
                    log_change("RESTORE", "order", restore_id, f"order_no={order_no}")
                    st.success(f"{order_no} 발주서를 복구했습니다.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"복구 중 오류가 발생하여 취소했습니다: {exc}")

    # ------------------------------------------------------------------
    # 비밀번호
    # ------------------------------------------------------------------
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
            log_change("PASSWORD_CHANGE", "settings", "admin_password", "관리자 비밀번호 변경")
            st.success("비밀번호 변경 완료")
