import json

import pytest

from manifestfix.lenient_json import LenientJSONError, parse_lenient

CLEAN = {"a": 1, "b": ["x", "y"], "c": True, "d": None}

MESSY = """Sure, here is the result:
```json
{'a': 1, 'b': ['x', 'y',], 'c': True, // a comment
 'd': None,}
```
Hope this helps.
"""


def test_fenced_trailing_commas_and_single_quotes_match_clean_json():
    result = parse_lenient(MESSY)
    assert result.data == CLEAN
    assert {"markdown_fence", "prose", "single_quote", "trailing_comma", "python_literal"} <= set(
        result.kinds
    )
    assert "comment" in result.kinds


def test_string_values_with_commas_and_quotes_are_untouched():
    text = '{"description": "bolts, nuts, \'washers\'"}'
    result = parse_lenient(text)
    assert result.data == {"description": "bolts, nuts, 'washers'"}
    assert result.repairs == []


def test_comment_markers_and_literals_inside_strings_survive():
    text = '{"url": "http://x.example/a//b", "note": "True, None, [1,]", "tail": "a,}"}'
    result = parse_lenient(text)
    assert result.data["url"] == "http://x.example/a//b"
    assert result.data["note"] == "True, None, [1,]"
    assert result.data["tail"] == "a,}"
    assert result.repairs == []


def test_single_quoted_string_keeps_embedded_double_quote_and_apostrophe():
    result = parse_lenient("{'k': 'say \"hi\", it\\'s fine'}")
    assert result.data == {"k": 'say "hi", it\'s fine'}


def test_prose_around_object_is_dropped_and_logged():
    result = parse_lenient('Result: {"a": 1} Thanks!')
    assert result.data == {"a": 1}
    assert "prose" in result.kinds


def test_plain_json_needs_no_repairs():
    text = json.dumps(CLEAN)
    result = parse_lenient(text)
    assert result.data == CLEAN
    assert result.repairs == []


def test_bare_array_is_supported():
    assert parse_lenient("[1, 2, 3,]").data == [1, 2, 3]


def test_unrecoverable_text_raises():
    with pytest.raises(LenientJSONError):
        parse_lenient("no json here")
    with pytest.raises(LenientJSONError):
        parse_lenient('{"a": }')
