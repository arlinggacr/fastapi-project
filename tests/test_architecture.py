"""Guards the layering rules.

Controllers must not touch the database, and SQLAlchemy queries may only be
built inside repositories (entities may declare columns/relationships).
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "modules"

DB_TOKENS = ("execute(", "select(", "session.add(", "session.delete(", "session.get(")


def _module_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


def test_controllers_do_not_import_sqlalchemy_queries():
    offenders: list[str] = []
    for path in _module_files():
        if "controllers" not in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("sqlalchemy")
                and not node.module.endswith("ext.asyncio")
            ):
                offenders.append(f"{path.relative_to(SRC)}: {node.module}")
    assert not offenders, offenders


def test_database_access_is_confined_to_repositories():
    offenders: list[str] = []
    for path in _module_files():
        if "repositories" in path.parts or "entities" in path.parts:
            continue
        source = path.read_text()
        for token in DB_TOKENS:
            if token in source:
                offenders.append(f"{path.relative_to(SRC)}: {token}")
    assert not offenders, offenders


def test_no_raw_sql_strings():
    """No module should build SQL by hand (f-strings / concatenation)."""
    suspicious = (
        "from sqlalchemy import text",
        "sqlalchemy.text(",
        'execute("',
        "execute('",
        "executemany(",
    )
    offenders: list[str] = []
    for path in _module_files():
        if "entities" in path.parts:
            continue
        source = path.read_text()
        for token in suspicious:
            if token in source:
                offenders.append(f"{path.relative_to(SRC)}: {token}")
    assert not offenders, offenders


def test_services_do_not_import_controllers():
    offenders: list[str] = []
    for path in _module_files():
        if "services" not in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "controllers" in node.module:
                offenders.append(f"{path.relative_to(SRC)}: {node.module}")
    assert not offenders, offenders
