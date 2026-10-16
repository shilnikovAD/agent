"""MCP-сервер базы знаний Артура: поиск по рабочим документам.

Запуск: python -m mcp_kb.server            (stdio, для локального прогона)
        MCP_TRANSPORT=http python -m mcp_kb.server   (streamable HTTP на :8765/mcp, так он работает в docker compose)

В контейнере у сервера нет ни сети наружу, ни секретов: он только читает /kb (только чтение).
"""
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mcp_kb.search import Index

KB_DIR = Path(os.getenv("KB_DIR", Path(__file__).resolve().parent.parent / "data" / "kb"))
index = Index(KB_DIR)
server = FastMCP("workchat-kb", log_level="WARNING", host=os.getenv("MCP_HOST", "127.0.0.1"), port=int(os.getenv("MCP_PORT", "8765")))


@server.tool()
def kb_search(query: str, k: int = 5) -> str:
    """Search Arthur's work knowledge base (team, projects, processes, calendar, vacation) and return up to k matching lines
    with their document and section. Use short queries with key words, in Russian."""
    hits = index.search(query, max(1, min(int(k), 8)))
    return "\n".join(h.render() for h in hits) if hits else "nothing found"


@server.tool()
def kb_list_documents() -> str:
    """List the documents in the knowledge base with their sections."""
    seen: dict[str, list[str]] = {}
    for c in index.chunks:
        sections = seen.setdefault(c.doc, [])
        if c.section and c.section not in sections:
            sections.append(c.section)
    return "\n".join(f"{doc}: {', '.join(s) or '—'}" for doc, s in seen.items())


@server.tool()
def kb_reload() -> str:
    """Admin: re-read the knowledge base files from disk. Not for chat roles."""
    return f"reloaded {index.reload()} chunks"


if __name__ == "__main__":
    server.run(transport="streamable-http" if os.getenv("MCP_TRANSPORT") == "http" else "stdio")
