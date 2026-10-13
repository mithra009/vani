"""Tests for editor_service.providers.validate_translation."""

import pytest

from editor_service.providers import validate_translation
from editor_service.errors import OutputInvalid


ITEMS = [{"id": 1, "text": "Hello"}, {"id": 2, "text": "World"}]


class TestValidateTranslation:
    def test_valid_input(self):
        raw = [{"id": 1, "text": "Hola"}, {"id": 2, "text": "Mundo"}]
        result = validate_translation(ITEMS, raw)
        assert result == {1: "Hola", 2: "Mundo"}

    def test_rejects_non_list(self):
        with pytest.raises(OutputInvalid, match="no list"):
            validate_translation(ITEMS, "not a list")

    def test_rejects_missing_ids(self):
        raw = [{"id": 1, "text": "Hola"}]  # missing id 2
        with pytest.raises(OutputInvalid, match="ids don't match"):
            validate_translation(ITEMS, raw)

    def test_rejects_empty_text(self):
        raw = [{"id": 1, "text": "Hola"}, {"id": 2, "text": "   "}]
        with pytest.raises(OutputInvalid, match="Empty translation"):
            validate_translation(ITEMS, raw)

