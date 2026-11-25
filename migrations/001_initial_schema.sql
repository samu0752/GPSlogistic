CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 name TEXT NOT NULL, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('operador','supervisor','admin')),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)));
CREATE TABLE IF NOT EXISTS areas(code TEXT PRIMARY KEY, category TEXT NOT NULL, type TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS brands(code TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS products(
 sku TEXT PRIMARY KEY, brand TEXT NOT NULL REFERENCES brands(name), manufacturer_code TEXT NOT NULL,
 description TEXT NOT NULL, category TEXT NOT NULL, type TEXT NOT NULL, capacity TEXT NOT NULL,
 unit TEXT NOT NULL, modules INTEGER NOT NULL CHECK(modules>=1), source TEXT NOT NULL DEFAULT '',
 verification TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 minimum INTEGER NOT NULL DEFAULT 5 CHECK(minimum>=0), UNIQUE(brand,manufacturer_code));
CREATE TABLE IF NOT EXISTS locations(
 code TEXT PRIMARY KEY, area TEXT NOT NULL REFERENCES areas(code),
 brand TEXT NOT NULL REFERENCES brands(name), active INTEGER NOT NULL DEFAULT 1
 CHECK(active IN (0,1)));
CREATE TABLE IF NOT EXISTS operations(
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN
 ('initial','in','out','transfer','count','reversal')),
 user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, reason TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE, payload_hash TEXT NOT NULL,
 reversal_of INTEGER UNIQUE REFERENCES operations(id));
CREATE TABLE IF NOT EXISTS balances(
 sku TEXT NOT NULL REFERENCES products(sku), location TEXT NOT NULL REFERENCES locations(code),
 quantity INTEGER NOT NULL CHECK(quantity>=0 AND quantity<=1000000000),
 PRIMARY KEY(sku,location));
CREATE TABLE IF NOT EXISTS entries(
 id INTEGER PRIMARY KEY, operation_id INTEGER NOT NULL REFERENCES operations(id),
 sku TEXT NOT NULL REFERENCES products(sku), location TEXT NOT NULL REFERENCES locations(code),
 before_qty INTEGER NOT NULL CHECK(before_qty>=0), delta INTEGER NOT NULL,
 after_qty INTEGER NOT NULL CHECK(after_qty>=0 AND after_qty<=1000000000),
 CHECK(after_qty=before_qty+delta), UNIQUE(operation_id,sku,location));
CREATE INDEX IF NOT EXISTS entry_lookup ON entries(sku,location,id);
CREATE INDEX IF NOT EXISTS operation_date ON operations(created_at);
CREATE TABLE IF NOT EXISTS events(
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL,
 action TEXT NOT NULL, details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_limits(
 username TEXT PRIMARY KEY, failures INTEGER NOT NULL, locked_until REAL NOT NULL);
CREATE TRIGGER IF NOT EXISTS entry_check BEFORE INSERT ON entries
 WHEN NEW.before_qty != COALESCE((SELECT quantity FROM balances WHERE sku=NEW.sku AND
 location=NEW.location),0)
 BEGIN SELECT RAISE(ABORT,'Saldo anterior divergente'); END;
CREATE TRIGGER IF NOT EXISTS entry_balance AFTER INSERT ON entries BEGIN
 INSERT INTO balances(sku,location,quantity) VALUES(NEW.sku,NEW.location,NEW.after_qty)
 ON CONFLICT(sku,location) DO UPDATE SET quantity=excluded.quantity; END;
CREATE TRIGGER IF NOT EXISTS entries_no_update BEFORE UPDATE ON entries
 BEGIN SELECT RAISE(ABORT,'Historico imutavel'); END;
CREATE TRIGGER IF NOT EXISTS entries_no_delete BEFORE DELETE ON entries
 BEGIN SELECT RAISE(ABORT,'Historico imutavel'); END;
CREATE TRIGGER IF NOT EXISTS operations_no_update BEFORE UPDATE ON operations
 BEGIN SELECT RAISE(ABORT,'Historico imutavel'); END;
CREATE TRIGGER IF NOT EXISTS operations_no_delete BEFORE DELETE ON operations
 BEGIN SELECT RAISE(ABORT,'Historico imutavel'); END;
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
 BEGIN SELECT RAISE(ABORT,'Auditoria imutavel'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
 BEGIN SELECT RAISE(ABORT,'Auditoria imutavel'); END;
