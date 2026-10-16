import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS = {"cheap": "openai/gpt-4o-mini", "mid": "anthropic/claude-haiku-4.5", "strong": "anthropic/claude-sonnet-4.6"}

DATA = ROOT / "data"
KB_DIR = Path(os.getenv("KB_DIR", DATA / "kb"))
RUNS = Path(os.getenv("RUNS_DIR", ROOT / "runs"))
RUNS.mkdir(exist_ok=True)
PINS_FILE = ROOT / "mcp_pins.json"

# потолки денег: на одно входящее сообщение и на день (счётчик трат в runs/spend.json)
MAX_USD_PER_TASK = float(os.getenv("MAX_USD_PER_TASK", "0.03"))
MAX_USD_PER_DAY = float(os.getenv("MAX_USD_PER_DAY", "2.0"))

# MCP-сервер базы знаний: в docker compose — http://kb:8765/mcp, локально — stdio-процесс python -m mcp_kb.server
MCP_URL = os.getenv("MCP_URL", "")

TEAM = json.loads((DATA / "team.json").read_text(encoding="utf-8"))
OWNER = TEAM["owner"]


def api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise SystemExit("нет OPENROUTER_API_KEY: скопируйте .env.example в .env и впишите ключ")
    return key
