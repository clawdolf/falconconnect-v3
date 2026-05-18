"""Path-traversal defence for the admin route.

The admin route lets callers pick a sub-directory name for the report
output, but must NEVER let them escape the server-controlled reports base.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from routers.lead_hygiene import AuditRequest, _resolve_out_dir, DEFAULT_REPORTS_BASE


class TestOutputSubdirValidator:
    def test_default_is_optional(self):
        req = AuditRequest(fixture_mode=True)
        assert req.output_subdir is None

    def test_simple_slug_is_accepted(self):
        req = AuditRequest(fixture_mode=True, output_subdir="2026-05-18-voicemail")
        assert req.output_subdir == "2026-05-18-voicemail"

    def test_slash_is_rejected(self):
        with pytest.raises(ValidationError):
            AuditRequest(fixture_mode=True, output_subdir="foo/bar")

    def test_traversal_is_rejected(self):
        with pytest.raises(ValidationError):
            AuditRequest(fixture_mode=True, output_subdir="..")
        with pytest.raises(ValidationError):
            AuditRequest(fixture_mode=True, output_subdir="../etc")

    def test_absolute_path_is_rejected(self):
        with pytest.raises(ValidationError):
            AuditRequest(fixture_mode=True, output_subdir="/etc/passwd")

    def test_leading_dot_is_rejected(self):
        # The first char must be alnum to prevent hidden / dot directories.
        with pytest.raises(ValidationError):
            AuditRequest(fixture_mode=True, output_subdir=".hidden")

    def test_overlong_is_rejected(self):
        with pytest.raises(ValidationError):
            AuditRequest(fixture_mode=True, output_subdir="a" * 200)

    def test_null_byte_is_rejected(self):
        with pytest.raises(ValidationError):
            AuditRequest(fixture_mode=True, output_subdir="ok\x00bad")


class TestResolveOutDir:
    def test_subdir_resolves_under_base(self):
        out = _resolve_out_dir("safe-run")
        assert str(out).startswith(str(DEFAULT_REPORTS_BASE))

    def test_omitted_subdir_yields_timestamped_run(self):
        out = _resolve_out_dir(None)
        assert out.name.startswith("run-")
        assert str(out).startswith(str(DEFAULT_REPORTS_BASE))
