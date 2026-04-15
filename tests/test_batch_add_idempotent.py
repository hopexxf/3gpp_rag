"""
Tests for batch_add idempotency.
"""
import sys
from unittest.mock import MagicMock
import pytest


def _get_manage_spec(src_path):
    """Import manage_spec with src in path."""
    sp = str(src_path)
    if sp not in sys.path:
        sys.path.insert(0, sp)
    import manage_spec
    return manage_spec


class TestBatchAddIdempotent:

    def test_consecutive_batch_add(self, mock_protocol_dir, mock_db_manager, src_path):
        """Running batch_add twice should not error or duplicate."""
        ms = _get_manage_spec(src_path)
        orig = ms._scan_available_specs.__globals__["PROTOCOL_BASE"]
        ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = lambda: mock_protocol_dir

        spec_mgr = ms.SpecManager(mock_db_manager)
        spec_mgr.add = MagicMock(return_value=True)

        try:
            r1 = spec_mgr.batch_add("Rel-19")
            r2 = spec_mgr.batch_add("Rel-19")
        finally:
            ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = orig

        assert r1["total"] == 3
        assert r2["total"] == 3
        assert len(r1["success"]) == 3
        assert len(r2["success"]) == 3

    def test_add_nonexistent_spec(self, mock_db_manager, src_path):
        """Adding a spec that doesn't exist on disk returns failure."""
        ms = _get_manage_spec(src_path)

        spec_mgr = ms.SpecManager(mock_db_manager)
        spec_mgr.add = MagicMock(side_effect=FileNotFoundError("zip not found"))

        result = spec_mgr.batch_add("Rel-19", spec_list=["99.999"])

        assert result["total"] == 1
        assert len(result["failed"]) == 1
        assert "99.999" in result["failed"]
