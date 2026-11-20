"""Неизменяемость снимка заказа на уровне PostgreSQL:
- строки order_items нельзя изменить после создания (UPDATE запрещён);
- поле orders.snapshot нельзя изменить после первого заполнения."""
from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION forbid_order_item_update() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'order_items are immutable (order snapshot)';
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS order_items_immutable ON order_items;
CREATE TRIGGER order_items_immutable BEFORE UPDATE ON order_items
  FOR EACH ROW EXECUTE FUNCTION forbid_order_item_update();

CREATE OR REPLACE FUNCTION forbid_order_snapshot_change() RETURNS trigger AS $$
BEGIN
  IF OLD.snapshot IS NOT NULL AND OLD.snapshot <> '{}'::jsonb AND NEW.snapshot IS DISTINCT FROM OLD.snapshot THEN
    RAISE EXCEPTION 'orders.snapshot is immutable once set';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS orders_snapshot_immutable ON orders;
CREATE TRIGGER orders_snapshot_immutable BEFORE UPDATE OF snapshot ON orders
  FOR EACH ROW EXECUTE FUNCTION forbid_order_snapshot_change();
"""

REVERSE = """
DROP TRIGGER IF EXISTS order_items_immutable ON order_items;
DROP TRIGGER IF EXISTS orders_snapshot_immutable ON orders;
DROP FUNCTION IF EXISTS forbid_order_item_update();
DROP FUNCTION IF EXISTS forbid_order_snapshot_change();
"""


class Migration(migrations.Migration):
    dependencies = [("orders", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
