"""Клиент MCP-сервера базы знаний: белые списки по ролям и отпечатки описаний инструментов.

- Белый список: роль видит и может вызвать только свои инструменты. kb_reload (админский) не выдаётся ни одной роли.
  Проверка в коде call(), а не просьба в промпте: если модель попросит чужой инструмент, вызов отклоняется.
- Отпечатки (как check_pins на семинаре 4): sha256 от имени, описания и схемы аргументов каждого инструмента лежат
  в mcp_pins.json. Если сервер подменил описание (атака через описание инструмента), инструмент отключается.
"""
import asyncio
import hashlib
import json
import sys
import threading
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from workchat import config

ROLE_TOOLS = {
    "router": set(),                                   # маршрутизация кодом, инструменты не нужны
    "responder": {"kb_search", "kb_list_documents"},   # отвечает коллегам: только чтение базы знаний
    "admin": {"kb_reload"},                            # не используется агентом в чатах
}


def fingerprint(tool) -> str:
    payload = json.dumps({"name": tool["name"], "description": tool["description"], "schema": tool["inputSchema"]},
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class KB:
    """Синхронная обёртка над одной MCP-сессией, живущей в отдельном потоке со своим event loop."""

    def __init__(self, url: str = config.MCP_URL):
        self.url = url
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.lock = threading.Lock()
        self._run(self._connect())
        self.tools = {t.name: {"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema}
                      for t in self._run(self.session.list_tools()).tools}
        self.mismatched = self.check_pins()

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=60)

    async def _connect(self):
        self.stack = AsyncExitStack()
        if self.url:
            read, write, _ = await self.stack.enter_async_context(streamablehttp_client(self.url))
        else:
            params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_kb.server"], cwd=str(config.ROOT),
                                           env={"KB_DIR": str(config.KB_DIR), "PYTHONIOENCODING": "utf-8"})
            read, write = await self.stack.enter_async_context(stdio_client(params))
        self.session = await self.stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

    def check_pins(self) -> list[str]:
        """Имена инструментов, чьи описания не совпали с закреплёнными. Такие инструменты не выдаются модели."""
        if not config.PINS_FILE.exists():
            return list(self.tools)
        pins = json.loads(config.PINS_FILE.read_text(encoding="utf-8"))
        return [name for name, tool in self.tools.items() if pins.get(name) != fingerprint(tool)]

    def write_pins(self):
        config.PINS_FILE.write_text(json.dumps({n: fingerprint(t) for n, t in sorted(self.tools.items())}, indent=1),
                                    encoding="utf-8")
        self.mismatched = []

    def allowed(self, role: str) -> list[str]:
        return [n for n in sorted(ROLE_TOOLS.get(role, set())) if n in self.tools and n not in self.mismatched]

    def schemas(self, role: str) -> list[dict]:
        return [{"type": "function", "function": {"name": n, "description": self.tools[n]["description"],
                                                  "parameters": self.tools[n]["inputSchema"]}} for n in self.allowed(role)]

    def call(self, name: str, args: dict, role: str) -> str:
        if name not in self.allowed(role):
            return f"отказ: инструмент {name} не разрешён роли {role}"
        with self.lock:
            result = self._run(self.session.call_tool(name, args))
        return "\n".join(getattr(c, "text", "") for c in result.content)[:3000]

    def close(self):
        try:
            self._run(self.stack.aclose())
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
