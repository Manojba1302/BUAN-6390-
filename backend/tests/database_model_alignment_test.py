"""Offline ORM checks. These do not replace tests on initialized PostgreSQL."""
import unittest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from app.db.models import (
    Base, ApplicationField, Employment, Asset, File,
    AuthAccount, AuthSession, PasswordReset, ChatConversation, ChatTurn,
)


class DatabaseModelAlignmentTests(unittest.TestCase):
    def test_tables_compile_for_postgresql(self):
        for table in Base.metadata.sorted_tables:
            with self.subTest(table=table.name):
                self.assertIn('CREATE TABLE', str(CreateTable(table).compile(dialect=postgresql.dialect())))

    def test_detail_ownership_and_partial_deletion(self):
        for model, source in ((ApplicationField, 'file_id'), (Employment, 'source_file_id'), (Asset, 'source_file_id')):
            with self.subTest(table=model.__tablename__):
                table = model.__table__
                self.assertFalse(table.c.customer_id.nullable)
                self.assertIsNotNone(table.c.customer_id.server_default)
                ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
                self.assertIn('FOREIGN KEY(application_id, customer_id)', ddl)
                self.assertIn(f'ON DELETE SET NULL ({source})', ddl)

    def test_file_metadata_and_vault_rules(self):
        names = {c.name for c in File.__table__.constraints}
        self.assertTrue({'file_size_bytes_nonnegative', 'file_page_count_nonnegative', 'file_attempts_nonnegative'} <= names)
        ddl = str(CreateTable(File.__table__).compile(dialect=postgresql.dialect()))
        self.assertIn('ON DELETE SET NULL (application_id)', ddl)

    def test_login_defaults_and_deletion(self):
        for model in (AuthAccount, AuthSession, PasswordReset):
            self.assertEqual(next(iter(model.__table__.c.customer_id.foreign_keys)).ondelete, 'CASCADE')
        self.assertEqual(str(AuthAccount.__table__.c.failed_attempts.server_default.arg), '0')
        self.assertEqual(str(PasswordReset.__table__.c.used.server_default.arg), 'false')
        self.assertIn('auth_account_failed_attempts_check', {c.name for c in AuthAccount.__table__.constraints})

    def test_chat_models_preserved(self):
        self.assertIn('reply', ChatTurn.__table__.c)
        self.assertIn('source_versions', ChatTurn.__table__.c)
        self.assertIn('application_id', ChatConversation.__table__.c)
        self.assertEqual(next(iter(ChatTurn.__table__.c.conversation_id.foreign_keys)).ondelete, 'CASCADE')


if __name__ == '__main__':
    unittest.main()
