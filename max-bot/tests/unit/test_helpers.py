"""Тесты утилит: форматирование, расширения, rate limiter."""

import pytest
from bot.utils.helpers import format_duration, format_file_size, get_file_extension


class TestFormatDuration:
    def test_zero(self):
        assert format_duration(0) == "00:00"

    def test_seconds_only(self):
        assert format_duration(45) == "00:45"

    def test_one_minute(self):
        assert format_duration(60) == "01:00"

    def test_minutes_and_seconds(self):
        assert format_duration(65) == "01:05"

    def test_59_minutes_59_seconds(self):
        assert format_duration(3599) == "59:59"

    def test_exactly_one_hour(self):
        assert format_duration(3600) == "01:00:00"

    def test_hours_minutes_seconds(self):
        assert format_duration(3661) == "01:01:01"

    def test_large_value(self):
        assert format_duration(7322) == "02:02:02"

    def test_float_truncated(self):
        # Дробные секунды обрезаются
        assert format_duration(61.9) == "01:01"

    def test_hours_with_zero_seconds(self):
        assert format_duration(7200) == "02:00:00"


class TestFormatFileSize:
    def test_bytes(self):
        assert format_file_size(0) == "0 Б"

    def test_bytes_small(self):
        assert format_file_size(512) == "512 Б"

    def test_bytes_boundary(self):
        assert format_file_size(1023) == "1023 Б"

    def test_kilobytes(self):
        assert format_file_size(1024) == "1.0 КБ"

    def test_kilobytes_fractional(self):
        assert format_file_size(1536) == "1.5 КБ"

    def test_kilobytes_boundary(self):
        assert format_file_size(1024 * 1024 - 1) == "1024.0 КБ"

    def test_megabytes(self):
        assert format_file_size(1024 * 1024) == "1.0 МБ"

    def test_megabytes_fractional(self):
        result = format_file_size(int(1.5 * 1024 * 1024))
        assert result == "1.5 МБ"

    def test_50mb(self):
        assert format_file_size(50 * 1024 * 1024) == "50.0 МБ"


class TestGetFileExtension:
    def test_simple(self):
        assert get_file_extension("audio.mp3") == "mp3"

    def test_uppercase(self):
        assert get_file_extension("AUDIO.MP3") == "mp3"

    def test_mixed_case(self):
        assert get_file_extension("File.OGG") == "ogg"

    def test_no_extension(self):
        assert get_file_extension("filename") == ""

    def test_hidden_file(self):
        # .env → расширение пустое, имя — ".env"
        assert get_file_extension(".env") == ""

    def test_double_extension(self):
        # Берётся последнее расширение
        assert get_file_extension("archive.tar.gz") == "gz"

    def test_path_with_dirs(self):
        assert get_file_extension("/tmp/audio/file.wav") == "wav"

    def test_m4a(self):
        assert get_file_extension("recording.m4a") == "m4a"

    def test_dot_in_name(self):
        assert get_file_extension("meeting.2024.mp4") == "mp4"
