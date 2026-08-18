#!/usr/bin/env python3
"""Test for validate_chatgpt_export's generic ``except Exception`` boundary
(distinct from its dedicated ImportError and jsonschema.ValidationError
branches), flagged as untested new code in PR #175.

Real (non-mocked) trigger: the schema's ``mapping`` field uses
``patternProperties`` keyed on ``^[a-zA-Z0-9-_]+$`` -- a mapping key that
does *not* match that pattern (e.g. contains a space) is never validated
by jsonschema at all (patternProperties only constrains matching keys), so
its value can be anything and jsonschema.validate() still passes. The
post-schema semantic-validation loop then calls ``node.get("message")`` on
that value assuming it's a dict, which raises a real AttributeError for a
non-dict value -- exactly the kind of gap this boundary exists to catch.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from universal_memory_mcp.schemas.chatgpt_schema import validate_chatgpt_export  # noqa: E402


def test_validate_chatgpt_export_reports_error_on_real_post_schema_failure():
    """A mapping key that bypasses patternProperties validation (doesn't
    match the pattern) can hold a non-dict value that passes schema
    validation but breaks the semantic-validation loop -- must return
    {"valid": False, "errors": [...]} rather than raise."""
    data = [
        {
            "title": "Conversation with a schema-bypassing mapping key",
            "create_time": 1700000000.0,
            "conversation_id": "c1",
            # "bad key!" contains characters outside ^[a-zA-Z0-9-_]+$, so
            # jsonschema's patternProperties never validates its value --
            # a plain string instead of the expected node object.
            "mapping": {"bad key!": "not a dict"},
        }
    ]

    result = validate_chatgpt_export(data)

    assert result["valid"] is False
    assert result["errors"]
    assert "attribute 'get'" in result["errors"][0]
    assert result["conversation_count"] == 0
