import sqlite3
import tempfile
import unittest
from pathlib import Path

from gps import db


class MigrationsTests(unittest.TestCase):
    def test_migrates_populated_legacy_database_without_losing_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.db"
            connection = sqlite3.connect(path)
            try:
                for name in ("001_initial_schema.sql", "002_user_credentials.sql"):
                    connection.executescript((db.MIGRATIONS / name).read_text(encoding="utf-8"))
                with connection:
                    connection.execute("INSERT INTO metadata VALUES ('schema_version','1')")
                    connection.execute("""
                        INSERT INTO users(username,name,password_hash,role,must_change_password)
                        VALUES ('samuel','Samuel','hash-inexistente-para-teste','admin',1)
                    """)
            finally:
                connection.close()
            db.initialize(path)
            db.initialize(path)
            versions = db.query(path, "SELECT version FROM schema_version ORDER BY version")
            self.assertEqual([row[0] for row in versions][:2], [1, 2])
            user = db.query(path, "SELECT * FROM users", one=True)
            self.assertEqual(user["username"], "samuel")
            self.assertEqual(user["must_change_password"], 1)
            self.assertEqual(user["auth_version"], 0)
