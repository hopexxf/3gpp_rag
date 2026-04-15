"""
Tests for _scan_available_specs() public function.
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import patch


def _get_manage_spec(src_path):
    """Import manage_spec with src in path."""
    sp = str(src_path)
    if sp not in sys.path:
        sys.path.insert(0, sp)
    import manage_spec
    return manage_spec


class TestScanAvailableSpecs:

    def test_normal_scan(self, mock_protocol_dir, src_path):
        """Normal directory: finds all spec zips."""
        ms = _get_manage_spec(src_path)
        orig = ms._scan_available_specs.__globals__["PROTOCOL_BASE"]
        ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = lambda: mock_protocol_dir
        try:
            result = ms._scan_available_specs("Rel-19")
        finally:
            ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = orig

        assert sorted(result) == ["38.133", "38.300", "38.523"]

    def test_empty_directory(self, tmp_path, src_path):
        """Empty release directory returns empty list."""
        ms = _get_manage_spec(src_path)
        orig = ms._scan_available_specs.__globals__["PROTOCOL_BASE"]
        ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = lambda: tmp_path
        try:
            result = ms._scan_available_specs("Rel-19")
        finally:
            ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = orig

        assert result == []

    def test_non_standard_filenames(self, mock_protocol_dir, src_path):
        """Non-standard files are ignored, only valid spec zips returned."""
        ms = _get_manage_spec(src_path)
        rel = mock_protocol_dir / "Rel-19" / "38_series"
        (rel / "abc123.zip").write_bytes(b"")
        (rel / "1234.zip").write_bytes(b"")
        (rel / "38.zip").write_bytes(b"")

        orig = ms._scan_available_specs.__globals__["PROTOCOL_BASE"]
        ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = lambda: mock_protocol_dir
        try:
            result = ms._scan_available_specs("Rel-19")
        finally:
            ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = orig

        assert result == ["38.133", "38.300", "38.523"]

    def test_duplicate_specs(self, mock_protocol_dir, src_path):
        """Duplicate spec numbers are deduplicated."""
        ms = _get_manage_spec(src_path)
        rel = mock_protocol_dir / "Rel-19" / "38_series"
        (rel / "S38300_v2.zip").write_bytes(b"")

        orig = ms._scan_available_specs.__globals__["PROTOCOL_BASE"]
        ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = lambda: mock_protocol_dir
        try:
            result = ms._scan_available_specs("Rel-19")
        finally:
            ms._scan_available_specs.__globals__["PROTOCOL_BASE"] = orig

        assert result.count("38.300") == 1
        assert len(result) == 3
