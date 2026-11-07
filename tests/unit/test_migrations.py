import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect


def test_migrations_build_the_schema_including_dependencies_json(tmp_path):
    """`alembic upgrade head` on an empty database, then back down one step and up again."""
    url = f"sqlite:///{tmp_path / 'm.db'}"
    env = {**os.environ, "DATABASE_URL": url}

    def alembic(*args):
        subprocess.run([sys.executable, "-m", "alembic", *args], check=True, env=env)

    alembic("upgrade", "head")
    columns = {c["name"] for c in inspect(create_engine(url)).get_columns("metrics")}
    assert "dependencies_json" in columns

    alembic("downgrade", "-1")
    columns = {c["name"] for c in inspect(create_engine(url)).get_columns("metrics")}
    assert "dependencies_json" not in columns
    alembic("upgrade", "head")
