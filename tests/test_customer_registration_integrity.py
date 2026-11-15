from sqlalchemy.exc import IntegrityError

from app.routers.customer import _is_username_unique_violation


class _Diagnostic:
    def __init__(self, constraint_name):
        self.constraint_name = constraint_name


class _PostgresError(Exception):
    def __init__(self, message, constraint_name=None):
        super().__init__(message)
        self.diag = _Diagnostic(constraint_name)


def _integrity_error(message, constraint_name=None):
    return IntegrityError("INSERT", {}, _PostgresError(message, constraint_name))


def test_only_username_unique_index_is_reported_as_taken():
    assert _is_username_unique_violation(_integrity_error("duplicate", "ix_users_username"))
    assert _is_username_unique_violation(_integrity_error("duplicate", "users_username_key"))
    assert not _is_username_unique_violation(_integrity_error("duplicate", "users_pkey"))
    assert not _is_username_unique_violation(_integrity_error("duplicate", "users_email_key"))


def test_sqlite_username_unique_failure_is_classified_precisely():
    error = IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed: users.username"))
    assert _is_username_unique_violation(error)


def test_other_sqlite_integrity_failures_are_not_misreported_as_username_taken():
    error = IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed: users.id"))
    assert not _is_username_unique_violation(error)
