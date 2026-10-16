"""Хуки: проверки кодом до и после модели. Это не просьбы в промпте: решение модели здесь можно только ужесточить.

route     — до модели: адресовано ли сообщение Артуру. Нет — молчим, модель не вызывается вовсе.
injection — до модели: текст, адресованный самому ассистенту («игнорируй правила», «бот, перешли…»). Отмечается флагом,
            модель видит сообщение как данные, а автоответ на такое сообщение запрещён.
review    — после модели: обещания и согласия от имени Артура, сроки и оценки, деньги, ответы руководителю и HR,
            утечки паролей и токенов. Любое из этого превращает автоответ в черновик на подтверждение.
"""
import re
from dataclasses import dataclass, field

from workchat import config

INJECTION = [
    r"(игнорир|забуд|отмен|не обращай вниман)\w*.{0,40}(инструкц|правил|указани|ограничени|промпт)",
    r"\b(ассистент|бот|ии|нейросет|assistant|bot|ai)\w*\b.{0,60}\b(перешли|отправь|напиши|скажи|подтверди|ответь|выдай|покажи|сделай)",
    r"(system prompt|системн\w* (промпт|инструкц)|developer mode|ignore (all |previous |the )?(instructions|rules))",
    r"\bты теперь\b|\bnew instructions\b|\bновые инструкции\b",
]
COMMITMENT = [
    r"\b(сделаю|доделаю|успею|обещаю|гарантирую|выполню|возьмусь|возьму на себя|беру на себя|подготовлю|пришлю|скину|"
    r"выйду|подключусь|приду|буду на|согласен|согласна|подтверждаю|одобряю|договорились|не возражаю)\b",
    r"\b(да|ок|окей|конечно),?\s+(смогу|сделаю|давай|успею|без проблем)",
    r"\bсмогу\b",
    # безличные обещания из трассы t17: «всё должно быть готово», «будет готово к пятнице», «должно успеть»
    r"(будет|должн\w*\s+быть)\s+готов\w*|должн\w*\s+успе\w*|успе(ем|ет|ть)\b",
]
MONEY = r"(\d[\d\s]*(₽|руб|р\.|тыс|k\b|\$|usd|евро|eur))|\b(бюджет\w*|оплат\w*|счёт на|счет на|премии?|зарплат\w*|компенсац\w*)\b"
LEAK = r"(парол\w*|password|token|токен\w*|secret|ключ\w* api)\s*[:=]\s*\S+|\b(sk-[a-z0-9-]{10,}|ghp_[a-z0-9]{10,})"


@dataclass
class Route:
    addressed: bool
    reason: str


@dataclass
class Review:
    action: str
    reply: str
    flags: list = field(default_factory=list)


def person(username: str) -> dict:
    return config.TEAM["people"].get((username or "").lstrip("@").lower(), {"name": username or "?", "role": "other"})


def route(msg: dict) -> Route:
    owner = config.OWNER
    if (msg.get("author_username") or "").lower() == owner["username"]:
        return Route(False, "сообщение самого Артура")
    if person(msg.get("author_username")).get("role") == "bot":
        return Route(False, "сообщение бота")
    if msg.get("chat_type") == "private":
        return Route(True, "личное сообщение")
    if msg.get("reply_to_owner"):
        return Route(True, "ответ на сообщение Артура")
    words = set(re.findall(r"@?\w+", (msg.get("text") or "").lower().replace("ё", "е")))
    if words & set(owner["name_forms"]):
        return Route(True, "упоминание Артура")
    return Route(False, "сообщение не адресовано Артуру")


def injection(msg: dict) -> bool:
    text = " ".join([msg.get("text") or ""] + [h.get("text", "") for h in msg.get("history", [])[-3:]]).lower()
    return any(re.search(p, text) for p in INJECTION)


def review(action: str, reply: str, msg: dict, injected: bool) -> Review:
    """Ужесточает решение модели. Никогда не превращает черновик или молчание в автоответ."""
    flags = []
    text = (reply or "").lower()
    if re.search(LEAK, text, re.I):
        flags.append("утечка секрета: ответ заблокирован")
        return Review("draft", "", flags)
    if action == "ignore":
        # вопрос, адресованный Артуру, не должен молча пропасть: пусть хотя бы увидит черновик
        if "?" in (msg.get("text") or "") and route(msg).addressed:
            return Review("draft", reply, ["вопрос Артуру: молчать нельзя"])
        return Review(action, reply, flags)
    if action == "draft":
        # черновик и так уйдёт Артуру, но обещания в нём подсвечиваются при подтверждении (найдено в трассе t17)
        if any(re.search(p, text) for p in COMMITMENT):
            flags.append("⚠️ в черновике обещание от вашего имени — проверьте")
        return Review(action, reply, flags)
    if injected:
        flags.append("в сообщении текст, адресованный ассистенту")
    if any(re.search(p, text) for p in COMMITMENT):
        flags.append("обещание или согласие от имени Артура")
    if re.search(MONEY, text, re.I):
        flags.append("деньги")
    role = person(msg.get("author_username")).get("role")
    if role in config.TEAM["approval_required_roles"]:
        flags.append(f"автор — {role}: ответы только через подтверждение")
    return Review("draft" if flags else "auto", reply, flags)


AUTO_MARK = "🤖 Ассистент Артура: "


def mark(reply: str) -> str:
    """Автоответ всегда подписан: коллега видит, что пишет ассистент, а не сам Артур."""
    return reply if reply.startswith(AUTO_MARK) else AUTO_MARK + reply
