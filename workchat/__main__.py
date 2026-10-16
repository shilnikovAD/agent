"""python -m workchat <команда>

  run       Telegram-бот, если в .env есть TELEGRAM_BOT_TOKEN; иначе демо на сохранённом чате (data/demo_chat.jsonl)
  demo      демо на сохранённом чате: что агент ответил бы и что ушло бы Артуру на подтверждение
  eval      прогон набора задач и таблица конфигураций: eval [best strong nohooks ...] [--limit N]
  pins      записать отпечатки описаний инструментов MCP-сервера (после осознанного изменения сервера)
  tax       налог MCP в токенах: сколько входных токенов добавляют описания инструментов к каждому вызову
"""
import os
import sys

from workchat import config


def main(argv):
    cmd = argv[0] if argv else "run"
    args = argv[1:]
    if cmd == "eval":
        limit = None
        if "--limit" in args:
            i = args.index("--limit")
            limit = int(args[i + 1])
            args = args[:i] + args[i + 2:]
        from workchat.evaluate import main as evaluate
        evaluate(args or ["strong", "best", "nohooks"], limit)
    elif cmd == "pins":
        from workchat.mcp_tools import KB
        kb = KB()
        kb.write_pins()
        print("отпечатки записаны:", config.PINS_FILE)
        kb.close()
    elif cmd == "tax":
        from workchat.tax import main as tax
        tax()
    elif cmd == "demo" or (cmd == "run" and not os.getenv("TELEGRAM_BOT_TOKEN")):
        from workchat.simulate import main as demo
        demo()
    elif cmd == "run":
        from workchat.telegram_bot import main as bot
        bot()
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
