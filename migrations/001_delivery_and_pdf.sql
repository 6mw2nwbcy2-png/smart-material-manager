-- Smart Material Manager v1.2
-- 1) 주문별 납품정보
-- 2) 협력사 담당자
-- 기존 orders/order_lines 데이터는 유지합니다.

CREATE TABLE IF NOT EXISTS partner_contacts (
    id SERIAL PRIMARY KEY,
    vendor TEXT NOT NULL,
    contact_name TEXT DEFAULT '',
    position TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    email TEXT DEFAULT '',
    note TEXT DEFAULT '',
    active INTEGER DEFAULT 1
);

ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_type TEXT DEFAULT '현장';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_recipient TEXT DEFAULT '';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_phone TEXT DEFAULT '';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_address TEXT DEFAULT '';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_address_original TEXT DEFAULT '';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_address_updated_by TEXT DEFAULT '';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_address_updated_at TEXT DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_orders_delivery_type ON orders(delivery_type);
CREATE INDEX IF NOT EXISTS idx_partner_contacts_vendor ON partner_contacts(vendor);
