"""Тесты T-Bank: подпись токена и валидация уведомлений."""

import hashlib
import re
import pytest
from bot.services.tinkoff import _token, verify_notification, new_order_id


class TestToken:
    def test_returns_hex_string(self):
        result = _token({"TerminalKey": "TinkoffBankTest", "Amount": 100})
        assert re.fullmatch(r"[0-9a-f]{64}", result)

    def test_deterministic(self):
        params = {"TerminalKey": "TinkoffBankTest", "Amount": 100, "OrderId": "order_1"}
        assert _token(params) == _token(params)

    def test_different_params_different_token(self):
        p1 = {"TerminalKey": "TinkoffBankTest", "Amount": 100}
        p2 = {"TerminalKey": "TinkoffBankTest", "Amount": 200}
        assert _token(p1) != _token(p2)

    def test_token_key_excluded_from_calculation(self):
        # Поле Token в params не влияет на результат (исключается)
        params = {"TerminalKey": "TinkoffBankTest", "Amount": 100}
        params_with_token = {**params, "Token": "oldtoken"}
        assert _token(params) == _token(params_with_token)

    def test_nested_dicts_excluded(self):
        # Вложенные объекты не участвуют в подписи
        params = {"TerminalKey": "TinkoffBankTest", "Amount": 100}
        params_with_receipt = {**params, "Receipt": {"Items": []}}
        assert _token(params) == _token(params_with_receipt)

    def test_list_values_excluded(self):
        params = {"TerminalKey": "TinkoffBankTest", "Amount": 100}
        params_with_list = {**params, "Items": ["a", "b"]}
        assert _token(params) == _token(params_with_list)

    def test_uses_password_from_config(self):
        # Токен включает Password из конфига — вычисляем вручную
        from bot.config import TINKOFF_PASSWORD
        params = {"TerminalKey": "TinkoffBankTest", "Amount": 100}
        data = {**params, "Password": TINKOFF_PASSWORD}
        filtered = {k: v for k, v in data.items() if not isinstance(v, (dict, list))}
        expected = hashlib.sha256(
            "".join(str(v) for _, v in sorted(filtered.items())).encode()
        ).hexdigest()
        assert _token(params) == expected


class TestVerifyNotification:
    def test_valid_notification(self):
        params = {"TerminalKey": "TinkoffBankTest", "Amount": 10000, "OrderId": "42_topup_abc1"}
        token = _token(params)
        notification = {**params, "Token": token}
        assert verify_notification(notification) is True

    def test_invalid_token(self):
        notification = {
            "TerminalKey": "TinkoffBankTest",
            "Amount": 10000,
            "Token": "wrongtoken",
        }
        assert verify_notification(notification) is False

    def test_missing_token(self):
        notification = {"TerminalKey": "TinkoffBankTest", "Amount": 10000}
        assert verify_notification(notification) is False

    def test_tampered_amount(self):
        params = {"TerminalKey": "TinkoffBankTest", "Amount": 10000}
        token = _token(params)
        # Подменяем Amount после подписи
        notification = {"TerminalKey": "TinkoffBankTest", "Amount": 99999, "Token": token}
        assert verify_notification(notification) is False


class TestNewOrderId:
    def test_format(self):
        oid = new_order_id(12345, "topup")
        # Формат: {user_id}_{kind}_{8 hex символов}
        assert re.fullmatch(r"12345_topup_[0-9a-f]{8}", oid)

    def test_unique(self):
        ids = {new_order_id(1, "topup") for _ in range(100)}
        assert len(ids) == 100  # Все уникальны

    def test_different_kinds(self):
        sub_id = new_order_id(1, "subscription")
        topup_id = new_order_id(1, "topup")
        assert "subscription" in sub_id
        assert "topup" in topup_id
        assert sub_id != topup_id

    def test_different_users(self):
        id1 = new_order_id(111, "topup")
        id2 = new_order_id(222, "topup")
        assert id1.startswith("111_")
        assert id2.startswith("222_")
