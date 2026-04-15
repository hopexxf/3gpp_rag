"""
3GPP RAG Tests - Shared Fixtures
"""
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def mock_protocol_dir(tmp_path):
    """Create a mock protocol directory with fake zip files.

    Uses real 3GPP zip naming convention: S38300.zip, s38133.zip, etc.
    """
    rel_dir = tmp_path / "Rel-19" / "38_series"
    rel_dir.mkdir(parents=True)
    # Real naming convention: spec number as 5 digits, no dot in filename
    for name in ["S38300.zip", "s38133.zip", "S38523.zip"]:
        (rel_dir / name).write_bytes(b"")
    # Non-standard files (should be ignored)
    (rel_dir / "readme.txt").write_text("hello")
    (rel_dir / "notes.md").write_text("# notes")
    return tmp_path


@pytest.fixture
def mock_db_manager():
    """Mock DatabaseManager with configurable get_loaded_specs."""
    mgr = MagicMock()
    mgr.get_loaded_specs.return_value = {}
    mgr.get_client.return_value = MagicMock()
    mgr.list_releases.return_value = ["Rel-19"]
    return mgr


@pytest.fixture
def mock_collection():
    """Mock ChromaDB Collection."""
    col = MagicMock()
    col.get.return_value = {"ids": [], "metadatas": [], "documents": []}
    col.count.return_value = 0
    return col


@pytest.fixture
def src_path():
    """Path to src/ directory."""
    return Path(__file__).parent.parent / "src"
