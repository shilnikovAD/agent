"""Демо без Telegram: прогоняет сохранённый рабочий чат (data/demo_chat.jsonl) через агента.

Показывает, что ушло бы в чат само, что ушло бы Артуру на подтверждение (с точным текстом и флагами) и что агент
пропустил. Если запуск в терминале, черновик можно подтвердить или отклонить; иначе черновики пишутся
в runs/pending-demo.jsonl.
"""
import json
import sys

from workchat import config
from workchat.agent import AgentConfig, handle
from workchat.ledger import Ledger
from workchat.mcp_tools import KB


def main():
    chat = [json.loads(l) for l in (config.DATA / "demo_chat.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    kb, ledger = KB(), Ledger()
    if kb.mismatched:
        raise SystemExit(f"описания инструментов MCP не совпали с отпечатками: {kb.mismatched}")
    cfg = AgentConfig("demo", config.MODELS["cheap"])
    interactive = sys.stdin.isatty()
    history, pending = [], []
    try:
        for msg in chat:
            msg = {**msg, "history": list(history[-20:])}
            print(f"\n[{msg['chat']}] @{msg['author_username']}: {msg['text']}")
            d = handle(msg, cfg, kb, ledger)
            history.append({"author": msg["author_username"], "text": msg["text"]})
            if d.action == "auto":
                print(f"  → в чат: {d.reply}")
                history.append({"author": "ассистент Артура", "text": d.reply})
            elif d.action == "draft":
                print(f"  → Артуру на подтверждение: «{d.reply or '— пусто —'}»\n    почему: {d.reason}"
                      + (f"\n    флаги: {'; '.join(d.flags)}" if d.flags else ""))
                ok = interactive and input("    отправить? [y/N] ").strip().lower() == "y"
                pending.append({"message": msg["text"], "draft": d.reply, "flags": d.flags, "sent": ok})
            else:
                print(f"  → молчу ({d.reason})")
            print(f"    {d.meter.calls} вызова модели, {d.meter.cost * 100:.4f} цента, {d.seconds:.1f} с")
    finally:
        kb.close()
    (config.RUNS / "pending-demo.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pending), encoding="utf-8")
    print(f"\nпотрачено сегодня: ${ledger.spent_today():.4f}; журнал вызовов: {config.RUNS}")
