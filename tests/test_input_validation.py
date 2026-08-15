"""Test input validation for security and data integrity"""

from pathlib import Path

import pytest

from exceptions import (
    ContentValidationError,
    DateValidationError,
    MetadataValidationError,
    QueryValidationError,
    TitleValidationError,
    ValidationError,
)
from validators import (
    validate_content,
    validate_date,
    validate_import_file_path,
    validate_limit,
    validate_search_query,
    validate_title,
)


class TestTitleValidation:
    """Test title validation for security and correctness"""

    def test_valid_titles(self):
        """Test normal valid titles pass validation"""
        assert validate_title("My Conversation") == "My Conversation"
        assert validate_title("Test-123") == "Test-123"
        assert validate_title("AI & Machine Learning") == "AI & Machine Learning"

    def test_empty_title_returns_default(self):
        """Test empty/None titles return default"""
        assert validate_title(None) == "Untitled Conversation"
        assert validate_title("") == "Untitled Conversation"
        assert validate_title("   ") == "Untitled Conversation"

    def test_title_length_limit(self):
        """Test title length validation"""
        # Max length title should pass
        long_title = "A" * 200
        assert validate_title(long_title) == long_title

        # Over max length should fail
        too_long = "A" * 201
        with pytest.raises(TitleValidationError, match="Title too long"):
            validate_title(too_long)

    def test_path_traversal_prevention(self):
        """Test path traversal attempts are blocked"""
        with pytest.raises(TitleValidationError, match="invalid path characters"):
            validate_title("../../etc/passwd")
        with pytest.raises(TitleValidationError, match="invalid path characters"):
            validate_title("..\\windows\\system32")

    def test_null_byte_prevention(self):
        """Test null bytes are blocked"""
        with pytest.raises(TitleValidationError, match="null bytes"):
            validate_title("test\x00malicious")

    def test_dangerous_characters_removed(self):
        """Test dangerous file characters are sanitized"""
        assert validate_title('test<script>alert("xss")</script>') == "testscriptalert(xss)/script"
        assert validate_title("file:name|test") == "filenametest"
        assert validate_title("test*file?name") == "testfilename"

    def test_control_characters_removed(self):
        """Test control characters are removed except safe ones"""
        # Tab and newline should be preserved
        assert validate_title("test\ttab") == "test\ttab"
        assert validate_title("test\nnewline") == "test\nnewline"

        # Other control chars should be removed
        assert validate_title("test\x01\x02\x03") == "test"
        assert validate_title("test\x7f") == "test"


class TestContentValidation:
    """Test content validation"""

    def test_valid_content(self):
        """Test normal content passes validation"""
        content = "This is a normal conversation about AI and programming."
        assert validate_content(content) == content

    def test_empty_content_fails(self):
        """Test empty content is rejected"""
        with pytest.raises(ContentValidationError, match="Content cannot be empty"):
            validate_content("")
        with pytest.raises(ContentValidationError, match="Content cannot be empty"):
            validate_content(None)

    def test_content_length_limits(self):
        """Test content length validation"""
        # Empty content
        with pytest.raises(ContentValidationError, match="Content cannot be empty"):
            validate_content("")

        # Maximum length
        huge_content = "A" * 1_000_001
        with pytest.raises(ContentValidationError, match="Content too long"):
            validate_content(huge_content)

        # Just under max should pass
        ok_content = "A" * 1_000_000
        assert validate_content(ok_content) == ok_content

    def test_null_bytes_removed_from_content(self):
        """Test null bytes are removed from content"""
        content = "Normal text\x00with null byte"
        assert validate_content(content) == "Normal textwith null byte"

    def test_formatting_preserved(self):
        """Test that formatting characters are preserved"""
        content = "Line 1\nLine 2\tTabbed\rCarriage return"
        assert validate_content(content) == content


class TestDateValidation:
    """Test date validation"""

    def test_valid_iso_dates(self):
        """Test valid ISO format dates"""
        # With Z suffix
        date = validate_date("2025-06-09T12:00:00Z")
        assert date.year == 2025
        assert date.month == 6
        assert date.day == 9

        # With timezone offset
        date = validate_date("2025-06-09T12:00:00+00:00")
        assert date.year == 2025

        # Without timezone
        date = validate_date("2025-06-09T12:00:00")
        assert date.year == 2025

    def test_none_date_returns_none(self):
        """Test None/empty date returns None"""
        assert validate_date(None) is None
        assert validate_date("") is None

    def test_invalid_date_format_fails(self):
        """Test invalid date formats fail"""
        with pytest.raises(DateValidationError, match="Invalid date format"):
            validate_date("not-a-date")
        with pytest.raises(DateValidationError, match="Invalid date format"):
            validate_date("2025-13-01")  # Invalid month
        with pytest.raises(DateValidationError, match="Invalid date format"):
            validate_date("2025-06-32")  # Invalid day

    def test_unrealistic_dates_fail(self):
        """Test dates too far in past/future fail"""
        # 200 years in future
        with pytest.raises(DateValidationError, match="Date is unrealistic"):
            validate_date("2225-01-01T00:00:00Z")

        # 200 years in past
        with pytest.raises(DateValidationError, match="Date is unrealistic"):
            validate_date("1825-01-01T00:00:00Z")


class TestQueryValidation:
    """Test search query validation"""

    def test_valid_queries(self):
        """Test normal queries pass validation"""
        assert validate_search_query("python programming") == "python programming"
        assert validate_search_query("AI") == "AI"
        assert validate_search_query("test 123") == "test 123"

    def test_empty_query_fails(self):
        """Test empty queries fail"""
        with pytest.raises(QueryValidationError, match="Query cannot be empty"):
            validate_search_query("")
        with pytest.raises(QueryValidationError, match="Query cannot be empty"):
            validate_search_query("   ")

    def test_query_length_limit(self):
        """Test query length validation"""
        # Max length should pass
        long_query = "A" * 500
        assert validate_search_query(long_query) == long_query

        # Over max should fail
        too_long = "A" * 501
        with pytest.raises(QueryValidationError, match="Query too long"):
            validate_search_query(too_long)

    def test_dangerous_characters_removed(self):
        """Test dangerous regex characters are sanitized"""
        assert validate_search_query("test<script>") == "testscript"
        assert validate_search_query("path\\test") == "pathtest"
        assert validate_search_query("test>output") == "testoutput"

    def test_null_bytes_blocked(self):
        """Test null bytes in queries"""
        with pytest.raises(QueryValidationError, match="null bytes"):
            validate_search_query("test\x00query")


class TestLimitValidation:
    """Test search limit validation"""

    def test_valid_limits(self):
        """Test normal limits pass"""
        assert validate_limit(10) == 10
        assert validate_limit(50) == 50
        assert validate_limit(100) == 100

    def test_limit_bounds(self):
        """Test limit bounds enforcement"""
        # Below minimum
        assert validate_limit(0) == 1
        assert validate_limit(-10) == 1

        # Above maximum
        assert validate_limit(101) == 100
        assert validate_limit(1000) == 100

    def test_non_integer_limit_fails(self):
        """Test non-integer limits fail"""
        with pytest.raises(ValidationError, match="Limit must be an integer"):
            validate_limit("10")
        with pytest.raises(ValidationError, match="Limit must be an integer"):
            validate_limit(10.5)
        with pytest.raises(ValidationError, match="Limit must be an integer"):
            validate_limit(None)


class TestValidatorEdgeCases:
    """Test edge cases in validators.py for complete coverage"""

    def test_content_validation_logic(self):
        """Test content validation logic and document unreachable code"""
        # Test that line 104 is unreachable due to MIN_CONTENT_LENGTH = 1
        # Any content with len < 1 is empty and caught by line 99 first

        # Empty content should trigger line 99, not line 104
        with pytest.raises(ContentValidationError, match="Content cannot be empty"):
            validate_content("")

        # This confirms line 104 is unreachable for MIN_CONTENT_LENGTH = 1

    def test_content_at_minimum_length(self):
        """Test content at exactly minimum length"""
        # Test content at minimum length (should pass)
        min_content = "a"  # 1 character, minimum length

        # This should not raise an exception
        result = validate_content(min_content)
        assert result == min_content

    def test_whitespace_only_content(self):
        """Test content that's only whitespace"""
        # Test content that's only whitespace
        whitespace_content = "   "  # Whitespace only - truthy but effectively empty

        # Should be valid since it's not empty (length > 0) and passes all checks
        result = validate_content(whitespace_content)
        assert result == whitespace_content  # Should return as-is


class TestImportFilePathValidation:
    """Test validate_import_file_path -- the choke point importers and
    FormatDetector route through before opening a file (SonarCloud
    pythonsecurity:S8707)."""

    def test_valid_existing_file(self, tmp_path):
        target = tmp_path / "export.json"
        target.write_text("{}", encoding="utf-8")

        result = validate_import_file_path(target)

        assert result == target.resolve()
        assert isinstance(result, Path)

    def test_valid_existing_file_as_string(self, tmp_path):
        target = tmp_path / "export.json"
        target.write_text("{}", encoding="utf-8")

        result = validate_import_file_path(str(target))

        assert result == target.resolve()

    def test_none_rejected(self):
        with pytest.raises(MetadataValidationError, match="cannot be None"):
            validate_import_file_path(None)

    def test_wrong_type_rejected(self):
        with pytest.raises(MetadataValidationError, match="must be a string or Path"):
            validate_import_file_path(12345)

    def test_empty_string_rejected(self):
        with pytest.raises(MetadataValidationError, match="empty or whitespace-only"):
            validate_import_file_path("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(MetadataValidationError, match="empty or whitespace-only"):
            validate_import_file_path("   ")

    def test_null_byte_rejected(self):
        with pytest.raises(MetadataValidationError, match="null bytes"):
            validate_import_file_path("evil\x00path.json")

    def test_nonexistent_path_rejected(self, tmp_path):
        missing = tmp_path / "does-not-exist.json"
        with pytest.raises(MetadataValidationError, match="does not exist"):
            validate_import_file_path(missing)

    def test_directory_rejected(self, tmp_path):
        with pytest.raises(MetadataValidationError, match="not a regular file"):
            validate_import_file_path(tmp_path)

    def test_relative_and_traversal_paths_not_blocked(self, tmp_path, monkeypatch):
        # Deliberate design choice (see validate_import_file_path docstring):
        # these importers are only reachable from a local CLI script run by
        # a human against their own files, so relative/`..` paths are not a
        # privilege-escalation vector here and are intentionally allowed.
        target = tmp_path / "sub" / "export.json"
        target.parent.mkdir()
        target.write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = validate_import_file_path("sub/../sub/export.json")

        assert result == target.resolve()
