"""Telegram-бот: агент работает по событию (новое сообщение в рабочем чате), Артур подтверждает черновики.

Настройка (см. README): создать бота у @BotFather, выключить ему Group Privacy (/setprivacy → Disable), добавить
в рабочие группы. В .env: TELEGRAM_BOT_TOKEN, OWNER_TELEGRAM_ID (числовой id Артура), OWNER_USERNAME.

- auto  → бот отвечает в чат сам, с пометкой «🤖 Ассистент Артура».
- draft → карточка Артуру в личку: чат, автор, исходное сообщение, точный текст ответа и флаги проверки.
          Кнопки «Отправить» / «Не отправлять»; ответ на карточку своим текстом — отправить исправленный вариант.
          Нажать кнопки может только OWNER_TELEGRAM_ID, остальные нажатия отклоняются кодом.
- Ничего необратимого без подтверждения: отправка черновика возможна только из обработчика нажатия Артура.
"""
import json
import os
import time
import uuid
from collections import defaultdict, deque

import requests

from workchat import config
from workchat.agent import AgentConfig, handle
from workchat.ledger import Ledger
from workchat.mcp_tools import KB

PENDING_FILE = config.RUNS / "pending.json"


class Api:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"

    def __call__(self, method: str, **params):
        r = requests.post(self.base + method, json=params, timeout=60)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: {data.get('description')}")
        return data["result"]


class Bot:
    def __init__(self, api, kb, ledger, cfg: AgentConfig, owner_id: int, owner_username: str):
        self.api, self.kb, self.ledger, self.cfg = api, kb, ledger, cfg
        self.owner_id, self.owner_username = owner_id, owner_username.lstrip("@").lower()
        self.history = defaultdict(lambda: deque(maxlen=20))
        self.pending = json.loads(PENDING_FILE.read_text(encoding="utf-8")) if PENDING_FILE.exists() else {}

    def save(self):
        PENDING_FILE.write_text(json.dumps(self.pending, ensure_ascii=False, indent=1), encoding="utf-8")

    # --- входящие ---
    def on_update(self, upd: dict):
        if "callback_query" in upd:
            return self.on_button(upd["callback_query"])
        msg = upd.get("message")
        if not msg or "text" not in msg:
            return
        sender = msg.get("from", {})
        if msg["chat"]["type"] == "private" and sender.get("id") == self.owner_id:
            return self.on_owner(msg)
        incoming = {
            "id": msg["message_id"], "chat": msg["chat"].get("title") or "личные сообщения",
            "chat_type": "private" if msg["chat"]["type"] == "private" else "group",
            "author_username": (sender.get("username") or str(sender.get("id"))).lower(),
            "author_name": " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")])),
            "text": msg["text"],
            "reply_to_owner": ((msg.get("reply_to_message") or {}).get("from") or {}).get("username", "").lower() == self.owner_username,
            "history": list(self.history[msg["chat"]["id"]]),
        }
        self.history[msg["chat"]["id"]].append({"author": incoming["author_name"] or incoming["author_username"], "text": msg["text"]})
        d = handle(incoming, self.cfg, self.kb, self.ledger, task_id=f"tg:{msg['chat']['id']}:{msg['message_id']}")
        if d.action == "auto":
            self.api("sendMessage", chat_id=msg["chat"]["id"], text=d.reply, reply_to_message_id=msg["message_id"])
        elif d.action == "draft":
            self.ask_owner(msg, incoming, d)

    def ask_owner(self, msg, incoming, d):
        draft_id = uuid.uuid4().hex[:10]
        card = (f"✉️ Черновик ответа\nЧат: {incoming['chat']}\nОт: {incoming['author_name']} (@{incoming['author_username']})\n"
                f"Сообщение: {incoming['text']}\n\nБуду отправлять ровно это:\n«{d.reply or '— пусто, напишите ответ сами —'}»\n\n"
                f"Почему черновик: {d.reason}" + (f"\nФлаги проверки: {'; '.join(d.flags)}" if d.flags else "")
                + "\n\nОтветьте на эту карточку своим текстом, чтобы отправить исправленный вариант.")
        sent = self.api("sendMessage", chat_id=self.owner_id, text=card, reply_markup={"inline_keyboard": [[
            {"text": "✅ Отправить", "callback_data": f"ok:{draft_id}"},
            {"text": "❌ Не отправлять", "callback_data": f"no:{draft_id}"}]]})
        self.pending[draft_id] = {"chat_id": msg["chat"]["id"], "reply_to": msg["message_id"], "text": d.reply,
                                  "card_id": sent["message_id"], "created": time.time()}
        self.save()

    def on_button(self, q: dict):
        if q.get("from", {}).get("id") != self.owner_id:
            self.api("answerCallbackQuery", callback_query_id=q["id"], text="Подтверждать может только Артур")
            return
        verdict, draft_id = q.get("data", ":").split(":", 1)
        item = self.pending.pop(draft_id, None)
        self.save()
        if not item:
            self.api("answerCallbackQuery", callback_query_id=q["id"], text="Черновик уже обработан")
        elif verdict == "ok" and item["text"]:
            self.send_approved(item, item["text"])
            self.api("answerCallbackQuery", callback_query_id=q["id"], text="Отправлено")
        else:
            self.api("answerCallbackQuery", callback_query_id=q["id"], text="Не отправлено")

    def on_owner(self, msg: dict):
        card_id = (msg.get("reply_to_message") or {}).get("message_id")
        for draft_id, item in list(self.pending.items()):
            if item["card_id"] == card_id:
                self.pending.pop(draft_id)
                self.save()
                self.send_approved(item, msg["text"])
                self.api("sendMessage", chat_id=self.owner_id, text="Отправил ваш вариант.")
                return
        self.api("sendMessage", chat_id=self.owner_id, text=f"Черновиков ждёт подтверждения: {len(self.pending)}")

    def send_approved(self, item: dict, text: str):
        self.api("sendMessage", chat_id=item["chat_id"], text=f"Артур (через ассистента): {text}", reply_to_message_id=item["reply_to"])

    def poll(self):
        offset = None
        while True:
            try:
                updates = self.api("getUpdates", timeout=30, offset=offset, allowed_updates=["message", "callback_query"])
            except Exception as e:
                print("getUpdates:", e, flush=True)
                time.sleep(5)
                continue
            for upd in updates:
                offset = upd["update_id"] + 1
                try:
                    self.on_update(upd)
                except Exception as e:  # одно плохое сообщение не роняет бота
                    print("ошибка обработки:", type(e).__name__, e, flush=True)


def main():
    token, owner = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("OWNER_TELEGRAM_ID")
    if not owner:
        raise SystemExit("нет OWNER_TELEGRAM_ID в .env: без него некому подтверждать черновики")
    kb = KB()
    if kb.mismatched:
        raise SystemExit(f"описания инструментов MCP не совпали с отпечатками: {kb.mismatched}")
    cfg = AgentConfig("telegram", config.MODELS["cheap"])
    bot = Bot(Api(token), kb, Ledger(), cfg, int(owner), os.getenv("OWNER_USERNAME", config.OWNER["username"]))
    print("бот запущен, жду сообщений", flush=True)
    bot.poll()
