"""Поиск по базе знаний: строки markdown-документов, словарный поиск по основам слов.

Почему не вектор: на русском корпусе в ДЗ 4 словарный поиск по основам дал recall@5 0.97 против 0.88 у эмбеддингов
(hw4/README.md, раздел «Гибрид»). База знаний здесь маленькая, а в вопросах коллег есть точные имена, даты и названия.
Заодно серверу не нужны ни сеть, ни ключ к API эмбеддингов: контейнер работает без сети и без секретов.
"""
import math
import re
from dataclasses import dataclass
from pathlib import Path

ENDINGS = re.compile(r"(иями|ями|ами|ого|его|ому|ему|ыми|ими|ией|ия|ие|ий|ый|ой|ая|яя|ое|ее|ые|ие|ом|ем|ам|ям|ах|ях|ов|ев|ей|ую|юю|а|я|о|е|ы|и|у|ю|ь)$")
STOP = {"и", "в", "во", "на", "с", "со", "по", "к", "ко", "о", "об", "от", "до", "за", "из", "у", "не", "ли", "а", "но", "что", "как",
        "это", "то", "же", "бы", "мне", "меня", "ты", "вы", "он", "она", "мы", "есть", "где", "когда", "кто", "какой", "какая",
        "какие", "скажи", "подскажи", "подскажите", "артур", "артура", "артуру", "привет", "пожалуйста"}


def stem(word: str) -> str:
    base = ENDINGS.sub("", word)
    return base if len(base) >= 3 else word


def tokens(text: str) -> list[str]:
    words = re.findall(r"\w+", text.lower().replace("ё", "е"))
    return [stem(w) for w in words if w not in STOP]


@dataclass
class Chunk:
    doc: str
    section: str
    text: str

    def render(self) -> str:
        return f"[{self.doc} / {self.section}] {self.text}" if self.section else f"[{self.doc}] {self.text}"


def load_chunks(folder: Path) -> list[Chunk]:
    chunks = []
    for path in sorted(folder.glob("*.md")):
        title, section = path.stem, ""
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("#"):
                section = line.lstrip("#").strip()
            elif line:
                chunks.append(Chunk(title, section, line.lstrip("- ").strip()))
    return chunks


class Index:
    def __init__(self, folder: Path):
        self.folder = folder
        self.reload()

    def reload(self) -> int:
        self.chunks = load_chunks(self.folder)
        # заголовок документа и раздела входят в индекс: «деплой» находит строки раздела «Деплой»
        self.docs = [set(tokens(f"{c.doc} {c.section} {c.text}")) for c in self.chunks]
        df: dict[str, int] = {}
        for d in self.docs:
            for w in d:
                df[w] = df.get(w, 0) + 1
        n = len(self.docs)
        self.idf = {w: math.log(1 + n / k) for w, k in df.items()}
        return n

    def search(self, query: str, k: int = 5) -> list[Chunk]:
        q = set(tokens(query))
        scored = [(sum(self.idf.get(w, 0.0) for w in q & d), i) for i, d in enumerate(self.docs)]
        scored = [(s, i) for s, i in scored if s > 0]
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [self.chunks[i] for _, i in scored[:k]]
