"""Строки заказа по-прежнему неизменяемы, но удалённый владельцем товар/складскую позицию можно «отвязать»:
product_id и inventory_item_id становятся NULL, а название, цена, количество и состав остаются как были."""
from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION forbid_order_item_update() RETURNS trigger AS $$
BEGIN
  IF (NEW.product_id IS NULL OR NEW.product_id IS NOT DISTINCT FROM OLD.product_id)
     AND (NEW.inventory_item_id IS NULL OR NEW.inventory_item_id IS NOT DISTINCT FROM OLD.inventory_item_id)
     AND (to_jsonb(NEW) - 'product_id' - 'inventory_item_id') = (to_jsonb(OLD) - 'product_id' - 'inventory_item_id')
  THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'order_items are immutable (order snapshot)';
END; $$ LANGUAGE plpgsql;
"""

REVERSE = """
CREATE OR REPLACE FUNCTION forbid_order_item_update() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'order_items are immutable (order snapshot)';
END; $$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [("orders", "0002_immutable_snapshot")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
