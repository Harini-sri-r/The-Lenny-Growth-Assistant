import sys
from pathlib import Path

from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings


def test_database_url_escapes_at_sign_and_other_password_characters(monkeypatch):
    password = "smoke@pass:with/slash?query#fragment%"
    monkeypatch.setenv("DATABASE_HOST", "db")
    monkeypatch.setenv("DATABASE_PORT", "5432")
    monkeypatch.setenv("POSTGRES_USER", "lenny")
    monkeypatch.setenv("POSTGRES_PASSWORD", password)
    monkeypatch.setenv("POSTGRES_DB", "lenny")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://unused:unused@localhost/unused")

    rendered_url = Settings().effective_database_url
    parsed_url = make_url(rendered_url)

    assert "%40" in rendered_url
    assert parsed_url.drivername == "postgresql+psycopg"
    assert parsed_url.username == "lenny"
    assert parsed_url.password == password
    assert parsed_url.host == "db"
    assert parsed_url.port == 5432
    assert parsed_url.database == "lenny"
