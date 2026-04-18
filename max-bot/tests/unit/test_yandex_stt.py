"""Тесты парсинга ответов Yandex SpeechKit getRecognition."""

import pytest
from bot.services.yandex_stt import _parse_recognition_simple, _parse_recognition_diarized


def _make_item(text: str, speaker_tag: str = None, channel_tag: str = "0") -> dict:
    """Вспомогательная функция для создания объекта getRecognition."""
    alternative = {"text": text, "words": []}
    if speaker_tag is not None:
        alternative["speakerTag"] = speaker_tag
    return {
        "result": {
            "final": {
                "alternatives": [alternative],
                "channelTag": channel_tag,
            },
            "channelTag": channel_tag,
        }
    }


def _make_partial_item(text: str) -> dict:
    """Объект без поля final (промежуточный результат — должен игнорироваться)."""
    return {
        "result": {
            "partial": {"alternatives": [{"text": text}]},
            "channelTag": "0",
        }
    }


class TestParseRecognitionSimple:
    def test_empty_list(self):
        assert _parse_recognition_simple([]) == ""

    def test_single_item(self):
        items = [_make_item("Привет всем")]
        assert _parse_recognition_simple(items) == "Привет всем"

    def test_multiple_items_joined_with_space(self):
        items = [_make_item("Привет"), _make_item("как дела")]
        assert _parse_recognition_simple(items) == "Привет как дела"

    def test_empty_text_skipped(self):
        items = [_make_item("Привет"), _make_item(""), _make_item("пока")]
        assert _parse_recognition_simple(items) == "Привет пока"

    def test_whitespace_text_skipped(self):
        items = [_make_item("Привет"), _make_item("   "), _make_item("пока")]
        assert _parse_recognition_simple(items) == "Привет пока"

    def test_partial_items_ignored(self):
        items = [_make_partial_item("не должно попасть"), _make_item("финальный текст")]
        assert _parse_recognition_simple(items) == "финальный текст"

    def test_items_without_alternatives_ignored(self):
        items = [
            {"result": {"final": {"alternatives": []}, "channelTag": "0"}},
            _make_item("настоящий текст"),
        ]
        assert _parse_recognition_simple(items) == "настоящий текст"

    def test_item_without_result_wrapper(self):
        # Некоторые форматы приходят без обёртки "result"
        items = [{"final": {"alternatives": [{"text": "голый финал"}]}}]
        assert _parse_recognition_simple(items) == "голый финал"

    def test_text_stripped(self):
        items = [_make_item("  пробелы  ")]
        assert _parse_recognition_simple(items) == "пробелы"


class TestParseRecognitionDiarized:
    def test_empty_list_returns_empty(self):
        assert _parse_recognition_diarized([]) == ""

    def test_single_speaker(self):
        items = [_make_item("Привет", speaker_tag="0")]
        result = _parse_recognition_diarized(items)
        assert result == "Участник 0: Привет"

    def test_two_different_speakers(self):
        items = [
            _make_item("Добрый день", speaker_tag="0"),
            _make_item("Здравствуйте", speaker_tag="1"),
        ]
        result = _parse_recognition_diarized(items)
        assert "Участник 0: Добрый день" in result
        assert "Участник 1: Здравствуйте" in result

    def test_consecutive_same_speaker_merged(self):
        items = [
            _make_item("Первая реплика", speaker_tag="0"),
            _make_item("вторая реплика", speaker_tag="0"),
        ]
        result = _parse_recognition_diarized(items)
        # Обе реплики объединены в одну строку
        assert result == "Участник 0: Первая реплика вторая реплика"

    def test_alternating_speakers(self):
        items = [
            _make_item("Реплика А1", speaker_tag="0"),
            _make_item("Реплика Б1", speaker_tag="1"),
            _make_item("Реплика А2", speaker_tag="0"),
        ]
        result = _parse_recognition_diarized(items)
        lines = result.split("\n\n")
        assert lines[0] == "Участник 0: Реплика А1"
        assert lines[1] == "Участник 1: Реплика Б1"
        assert lines[2] == "Участник 0: Реплика А2"

    def test_blocks_separated_by_double_newline(self):
        items = [
            _make_item("Реплика 0", speaker_tag="0"),
            _make_item("Реплика 1", speaker_tag="1"),
        ]
        result = _parse_recognition_diarized(items)
        assert "\n\n" in result

    def test_speaker_tag_from_channel_tag_fallback(self):
        # Нет speakerTag — берётся channelTag
        items = [_make_item("Текст без speakerTag", channel_tag="2")]
        result = _parse_recognition_diarized(items)
        assert result == "Участник 2: Текст без speakerTag"

    def test_no_segments_falls_back_to_simple(self):
        # Нет ни одного final.alternatives → fallback на _parse_recognition_simple
        items = [
            {"result": {"final": {"alternatives": []}, "channelTag": "0"}},
        ]
        result = _parse_recognition_diarized(items)
        assert result == ""

    def test_empty_text_items_skipped(self):
        items = [
            _make_item("Первая реплика", speaker_tag="0"),
            _make_item("", speaker_tag="0"),
            _make_item("Третья реплика", speaker_tag="1"),
        ]
        result = _parse_recognition_diarized(items)
        assert "Участник 0: Первая реплика" in result
        assert "Участник 1: Третья реплика" in result
        # Пустая строка не попала в результат
        assert "Участник 0:  " not in result
