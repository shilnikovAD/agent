"""Потолки денег и логика Telegram-бота на фальшивом API, без сети и без модели."""
import json

import pytest

from workchat import telegram_bot
from workchat.agent import Decision
from workchat.ledger import BudgetExceeded, Ledger, TaskMeter


def test_task_cap(tmp_path, monkeypatch):
    led = Ledger(day_cap=100)
    monkeypatch.setattr(led, "spend_file", tmp_path / "spend.json")
    m = TaskMeter("t", cap_usd=0.01)
    m.cost = 0.02
    with pytest.raises(BudgetExceeded):
        led.check(m)


def test_day_cap(tmp_path, monkeypatch):
    led = Ledger(day_cap=0.5)
    monkeypatch.setattr(led, "spend_file", tmp_path / "spend.json")
    (tmp_path / "spend.json").write_text(json.dumps({led._day(): 0.6}), encoding="utf-8")
    with pytest.raises(BudgetExceeded):
        led.check(TaskMeter("t"))


class FakeApi:
    def __init__(self):
        self.calls = []

    def __call__(self, method, **params):
        self.calls.append((method, params))
        return {"message_id": 999}


def make_bot(tmp_path, monkeypatch, decision):
    monkeypatch.setattr(telegram_bot, "PENDING_FILE", tmp_path / "pending.json")
    monkeypatch.setattr(telegram_bot, "handle", lambda *a, **k: decision)
    api = FakeApi()
    return telegram_bot.Bot(api, None, None, None, owner_id=42, owner_username="artur_sh"), api


def group_message(text):
    return {"update_id": 1, "message": {"message_id": 7, "chat": {"id": -100, "type": "supergroup", "title": "payments"},
                                        "from": {"id": 5, "username": "oleg_sedov", "first_name": "Олег"}, "text": text}}


def test_draft_goes_to_owner_not_to_chat(tmp_path, monkeypatch):
    bot, api = make_bot(tmp_path, monkeypatch, Decision("draft", "Сделаю к пятнице", "срок", ["обещание"], None))
    bot.on_update(group_message("Артур, успеешь?"))
    (method, params), = api.calls
    assert params["chat_id"] == 42 and "Сделаю к пятнице" in params["text"] and "обещание" in params["text"]


def test_only_owner_can_approve(tmp_path, monkeypatch):
    bot, api = make_bot(tmp_path, monkeypatch, Decision("draft", "Ок", "срок", [], None))
    bot.on_update(group_message("Артур, успеешь?"))
    draft_id = next(iter(bot.pending))
    bot.on_button({"id": "q1", "from": {"id": 666}, "data": f"ok:{draft_id}"})
    assert not any(m == "sendMessage" and p["chat_id"] == -100 for m, p in api.calls)
    bot.on_button({"id": "q2", "from": {"id": 42}, "data": f"ok:{draft_id}"})
    assert any(m == "sendMessage" and p["chat_id"] == -100 and "Ок" in p["text"] for m, p in api.calls)


def test_auto_reply_goes_to_chat(tmp_path, monkeypatch):
    bot, api = make_bot(tmp_path, monkeypatch, Decision("auto", "🤖 Ассистент Артура: деплой по вторникам", "факт", [], None))
    bot.on_update(group_message("Артур, когда деплой?"))
    (method, params), = api.calls
    assert params["chat_id"] == -100 and params["text"].startswith("🤖")
