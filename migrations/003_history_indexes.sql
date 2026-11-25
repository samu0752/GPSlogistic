CREATE INDEX IF NOT EXISTS entry_sku_id ON entries(sku, id DESC);
CREATE INDEX IF NOT EXISTS entry_location_id ON entries(location, id DESC);
CREATE INDEX IF NOT EXISTS operation_kind_date ON operations(kind, created_at, id);
