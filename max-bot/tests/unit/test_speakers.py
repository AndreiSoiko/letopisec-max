"""Тесты идентификации спикеров: парсинг JSON и подстановка имён."""

import pytest
from bot.services.speakers import _extract_json, apply_speaker_names


class TestExtractJson:
    def test_valid_json(self):
        assert _extract_json('{"0": "Андрей"}') == {"0": "Андрей"}

    def test_two_speakers(self):
        assert _extract_json('{"0": "Андрей", "1": "Мария"}') == {
            "0": "Андрей", "1": "Мария"
        }

    def test_markdown_fence(self):
        raw = '```json\n{"0": "Иван"}\n```'
        assert _extract_json(raw) == {"0": "Иван"}

    def test_markdown_fence_no_lang(self):
        raw = '```\n{"0": "Иван"}\n```'
        assert _extract_json(raw) == {"0": "Иван"}

    def test_prose_before_json(self):
        raw = 'Вот маппинг спикеров:\n{"0": "Андрей Сойка"}'
        assert _extract_json(raw) == {"0": "Андрей Сойка"}

    def test_empty_object(self):
        assert _extract_json("{}") == {}

    def test_no_json(self):
        assert _extract_json("Никто не представился") == {}

    def test_non_digit_key_ignored(self):
        # Ключи должны быть цифровыми строками
        assert _extract_json('{"speaker_0": "Андрей"}') == {}

    def test_non_string_value_ignored(self):
        assert _extract_json('{"0": 42}') == {}

    def test_empty_string_value_ignored(self):
        assert _extract_json('{"0": ""}') == {}

    def test_whitespace_value_ignored(self):
        assert _extract_json('{"0": "   "}') == {}

    def test_valid_and_invalid_mixed(self):
        # Корректная запись сохраняется, некорректная игнорируется
        result = _extract_json('{"0": "Андрей", "abc": "Игнор", "1": ""}')
        assert result == {"0": "Андрей"}

    def test_invalid_json(self):
        assert _extract_json('{"0": "broken json"') == {}

    def test_value_trimmed(self):
        result = _extract_json('{"0": "  Андрей Сойка  "}')
        assert result == {"0": "Андрей Сойка"}

    def test_large_speaker_id(self):
        assert _extract_json('{"10": "Участник десять"}') == {"10": "Участник десять"}


class TestApplySpeakerNames:
    def test_single_substitution(self):
        text = "Участник 0: Привет всем.\n\nУчастник 1: Добрый день."
        result = apply_speaker_names(text, {"0": "Андрей"})
        assert result == "Андрей: Привет всем.\n\nУчастник 1: Добрый день."

    def test_both_speakers(self):
        text = "Участник 0: Привет.\n\nУчастник 1: Здравствуйте."
        result = apply_speaker_names(text, {"0": "Андрей", "1": "Мария"})
        assert result == "Андрей: Привет.\n\nМария: Здравствуйте."

    def test_empty_mapping(self):
        text = "Участник 0: Привет."
        assert apply_speaker_names(text, {}) == text

    def test_unknown_speaker_unchanged(self):
        # Спикер 2 не в маппинге — остаётся как есть
        text = "Участник 0: Привет.\n\nУчастник 2: Пока."
        result = apply_speaker_names(text, {"0": "Андрей"})
        assert "Андрей: Привет." in result
        assert "Участник 2: Пока." in result

    def test_no_mid_sentence_replacement(self):
        # «Участник 0:» в середине строки НЕ заменяется — только в начале
        text = "Цитирую: «Участник 0: сказал нечто важное»\n\nУчастник 0: Привет."
        result = apply_speaker_names(text, {"0": "Андрей"})
        assert "«Участник 0: сказал" in result  # не заменено
        assert "Андрей: Привет." in result       # заменено

    def test_multiple_occurrences_of_same_speaker(self):
        text = "Участник 0: Первая реплика.\n\nУчастник 0: Вторая реплика."
        result = apply_speaker_names(text, {"0": "Андрей"})
        assert result == "Андрей: Первая реплика.\n\nАндрей: Вторая реплика."

    def test_name_with_spaces(self):
        text = "Участник 0: Привет."
        result = apply_speaker_names(text, {"0": "Андрей Сойка"})
        assert result == "Андрей Сойка: Привет."

    def test_idempotent_empty_text(self):
        assert apply_speaker_names("", {"0": "Андрей"}) == ""
