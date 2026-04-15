"""
Tests for check-pending CLI command.
"""
import sys
import json
from unittest.mock import patch, MagicMock
import pytest


def _get_manage_spec(src_path):
    """Import manage_spec with src in path."""
    sp = str(src_path)
    if sp not in sys.path:
        sys.path.insert(0, sp)
    import manage_spec
    return manage_spec


class TestCheckPending:

    def _set_base(self, ms, protocol_dir):
        orig = ms._scan_available_specs.__globals__["PROTOCOL_BASE"]
        ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = lambda: protocol_dir
        return orig

    def test_all_pending(self, mock_protocol_dir, mock_db_manager, src_path):
        """DB is empty, all disk specs are pending."""
        ms = _get_manage_spec(src_path)
        mock_db_manager.get_loaded_specs.return_value = {}

        orig = self._set_base(ms, mock_protocol_dir)
        try:
            available = ms._scan_available_specs("Rel-19")
            loaded = mock_db_manager.get_loaded_specs("Rel-19")
            pending = [s for s in available if s not in loaded]
        finally:
            ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = orig

        assert len(pending) == 3
        assert set(pending) == {"38.133", "38.300", "38.523"}

    def test_all_loaded(self, mock_protocol_dir, mock_db_manager, src_path):
        """All specs already in DB, pending is empty."""
        ms = _get_manage_spec(src_path)
        mock_db_manager.get_loaded_specs.return_value = {
            "38.133": {"clauses": 100}, "38.300": {"clauses": 200}, "38.523": {"clauses": 300}
        }

        orig = self._set_base(ms, mock_protocol_dir)
        try:
            available = ms._scan_available_specs("Rel-19")
            loaded = mock_db_manager.get_loaded_specs("Rel-19")
            pending = [s for s in available if s not in loaded]
        finally:
            ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = orig

        assert pending == []

    def test_partial_pending(self, mock_protocol_dir, mock_db_manager, src_path):
        """Some specs in DB, some pending."""
        ms = _get_manage_spec(src_path)
        mock_db_manager.get_loaded_specs.return_value = {
            "38.300": {"clauses": 200}
        }

        orig = self._set_base(ms, mock_protocol_dir)
        try:
            available = ms._scan_available_specs("Rel-19")
            loaded = mock_db_manager.get_loaded_specs("Rel-19")
            pending = [s for s in available if s not in loaded]
        finally:
            ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = orig

        assert set(pending) == {"38.133", "38.523"}
        assert len(pending) == 2

    def test_no_zip_files(self, tmp_path, mock_db_manager, src_path):
        """Directory exists but has no zip files."""
        ms = _get_manage_spec(src_path)
        mock_db_manager.get_loaded_specs.return_value = {}

        orig = self._set_base(ms, tmp_path)
        try:
            available = ms._scan_available_specs("Rel-19")
            loaded = mock_db_manager.get_loaded_specs("Rel-19")
            pending = [s for s in available if s not in loaded]
        finally:
            ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = orig

        assert available == []
        assert pending == []
