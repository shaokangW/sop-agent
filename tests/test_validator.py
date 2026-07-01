"""Tests for JSON extraction + schema validation in validate_output."""
import pytest

from sopagent.harness.validator import ValidationFailed, validate_output

SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}


def test_plain_json():
    data = validate_output('{"summary": "x"}', SCHEMA)
    assert data == {"summary": "x"}


def test_json_inside_codeblock():
    content = 'Here you go:\n```json\n{"summary": "x"}\n```\nDone.'
    data = validate_output(content, SCHEMA)
    assert data == {"summary": "x"}


def test_json_bare_codeblock():
    data = validate_output('```\n{"summary": "x"}\n```', SCHEMA)
    assert data == {"summary": "x"}


def test_json_with_surrounding_prose():
    data = validate_output('Sure! {"summary": "x"} that is all', SCHEMA)
    assert data["summary"] == "x"


def test_not_json_raises():
    with pytest.raises(ValidationFailed):
        validate_output("totally not json", SCHEMA)


def test_schema_mismatch_raises():
    with pytest.raises(ValidationFailed):
        validate_output('{"summary": 123}', SCHEMA)
