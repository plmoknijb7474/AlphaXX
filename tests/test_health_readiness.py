from types import SimpleNamespace

from app import main


class _FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement):
        assert str(statement).strip().upper() == "SELECT 1"
        return SimpleNamespace(scalar=lambda: 1)


def test_readiness_returns_ready_when_database_query_succeeds(monkeypatch):
    monkeypatch.setattr(main.engine, "connect", lambda: _FakeConnection())
    result = main.health_ready()
    assert result == {"status": "ready", "service": "alpha-api", "version": "1.5.11"}


def test_readiness_returns_503_without_leaking_database_error(monkeypatch):
    def fail_connect():
        raise RuntimeError("private connection password must not leak")

    monkeypatch.setattr(main.engine, "connect", fail_connect)
    result = main.health_ready()
    assert result.status_code == 503
    assert b"private connection password" not in result.body
    assert b"not_ready" in result.body
