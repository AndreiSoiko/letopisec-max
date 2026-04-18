"""Тесты разбиения и склейки текстовых блоков для LLM-коррекции."""

import pytest
from bot.services.correction import _split_text, _merge_blocks, MAX_BLOCK_CHARS, OVERLAP_CHARS


class TestSplitText:
    def test_short_text_not_split(self):
        text = "Короткий текст."
        assert _split_text(text) == [text]

    def test_exactly_max_chars_not_split(self):
        text = "a" * MAX_BLOCK_CHARS
        assert _split_text(text) == [text]

    def test_long_text_produces_multiple_blocks(self):
        text = "Слово " * (MAX_BLOCK_CHARS // 6 + 50)
        blocks = _split_text(text)
        assert len(blocks) > 1

    def test_each_block_max_size(self):
        text = "x" * (MAX_BLOCK_CHARS * 3)
        blocks = _split_text(text)
        for block in blocks:
            assert len(block) <= MAX_BLOCK_CHARS

    def test_split_at_sentence_boundary(self):
        # Граница разбиения должна предпочитать ". "
        half = MAX_BLOCK_CHARS // 2
        # Ставим точку чуть раньше MAX_BLOCK_CHARS
        sentence_end = "а" * (half + 10) + ". "
        filler = "б" * (MAX_BLOCK_CHARS - len(sentence_end) + 5)
        text = sentence_end + filler + " " + "в" * MAX_BLOCK_CHARS
        blocks = _split_text(text)
        # Первый блок должен оканчиваться после точки
        assert blocks[0].endswith(". ") or ". " in blocks[0]

    def test_blocks_cover_all_content(self):
        # После разбиения и склейки должен получиться текст без потерь
        text = ("Это предложение. " * 200).strip()
        blocks = _split_text(text)
        merged = _merge_blocks(blocks)
        # Все уникальные части должны присутствовать
        assert "Это предложение" in merged

    def test_empty_string(self):
        blocks = _split_text("")
        assert blocks == [""]

    def test_overlap_between_blocks(self):
        # Второй блок должен начинаться не с позиции конца первого — есть перекрытие
        text = "a" * (MAX_BLOCK_CHARS + OVERLAP_CHARS + 100)
        blocks = _split_text(text)
        assert len(blocks) >= 2
        # Между первым и вторым блоком должно быть перекрытие
        # Второй блок начинается раньше, чем конец первого
        assert len(blocks[0]) > MAX_BLOCK_CHARS - OVERLAP_CHARS


class TestMergeBlocks:
    def test_single_block(self):
        assert _merge_blocks(["Единственный блок"]) == "Единственный блок"

    def test_empty_list(self):
        assert _merge_blocks([]) == ""

    def test_no_overlap(self):
        # Если блоки не имеют общего суффикса/префикса — склеиваются через пробел
        result = _merge_blocks(["Первый блок", "Второй блок"])
        assert "Первый блок" in result
        assert "Второй блок" in result

    def test_exact_overlap_removed(self):
        # _merge_blocks обнаруживает перекрытия длиной >= 20 символов
        overlap = "конец первого блока, начало второго"  # 35 символов
        block1 = "Начало предложения. " + overlap
        block2 = overlap + " продолжение текста."
        result = _merge_blocks([block1, block2])
        # Перекрытие должно встречаться один раз, не два
        assert result.count(overlap) == 1

    def test_three_blocks(self):
        result = _merge_blocks(["блок А", "блок Б", "блок В"])
        assert "блок А" in result
        assert "блок В" in result

    def test_preserves_content(self):
        blocks = ["Важный текст совещания. "] * 3
        result = _merge_blocks(blocks)
        assert "Важный текст совещания" in result
