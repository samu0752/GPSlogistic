ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0
    CHECK(must_change_password IN (0,1));
ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0;
