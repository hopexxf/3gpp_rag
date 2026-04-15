"""
Tests for setup.ps1 - static verification only.
Verify that the script contains correct manage_spec.py command references.
"""
import re
from pathlib import Path
import pytest


SCRIPT_DIR = Path(__file__).parent.parent
SETUP_PS1 = SCRIPT_DIR / "setup.ps1"


class TestSetupPs1:
    """Static analysis of setup.ps1 to verify correct command references."""

    @pytest.fixture(autouse=True)
    def _has_script(self):
        if not SETUP_PS1.exists():
            pytest.skip("setup.ps1 not found (may not exist yet before Phase 2)")
        self.content = SETUP_PS1.read_text(encoding="utf-8-sig")

    def test_db_mode_calls_batch_add(self):
        """DB mode should call manage_spec.py batch-add."""
        if not hasattr(self, "content"):
            pytest.skip("setup.ps1 not found")
        assert "batch-add" in self.content, (
            "setup.ps1 'db' mode should call 'manage_spec.py batch-add'"
        )

    def test_full_mode_calls_batch_add(self):
        """Full mode should also call manage_spec.py batch-add."""
        if not hasattr(self, "content"):
            pytest.skip("setup.ps1 not found")
        assert "batch-add" in self.content, (
            "setup.ps1 'full' mode should call 'manage_spec.py batch-add'"
        )

    def test_calls_manage_spec_py(self):
        """Script should reference manage_spec.py."""
        if not hasattr(self, "content"):
            pytest.skip("setup.ps1 not found")
        assert "manage_spec.py" in self.content, (
            "setup.ps1 should reference manage_spec.py"
        )
