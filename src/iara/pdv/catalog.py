"""Catálogo de produtos do PDV, lido de um cache local em DBF que o próprio PDV mantém.

Somente leitura: nada aqui escreve no PDV nem em lugar nenhum. O arquivo é lido inteiro e
recarregado quando muda no disco. O nome do arquivo e as colunas vêm da configuração (`pdv`).
"""

from __future__ import annotations

import logging
import re
import struct
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from iara.config import PdvConfig

log = logging.getLogger(__name__)

ENCODING = "cp1252"
STOPWORDS = frozenset({"a", "o", "as", "os", "de", "da", "do", "das", "dos", "um", "uma", "e", "com", "para",
                       "pra", "por", "reais", "real", "r"})  # fmt: skip
_TOKEN = re.compile(r"[a-z]+|\d+(?:[.,]\d+)?")
_TRAILING_PRICE = re.compile(r"\s*\d+(?:[.,]\d+)?\s*$")


@dataclass(frozen=True, slots=True)
class PdvProduct:
    codigo: str
    descricao: str
    preco: float


def base_name(descricao: str) -> str:
    """Descrição sem o preço do fim: 'CANECA 15,00' -> 'CANECA'."""
    return _TRAILING_PRICE.sub("", descricao).strip()


def read_dbf(data: bytes) -> Iterator[dict[str, str]]:
    """Registros não apagados de um DBF, com os campos como texto."""
    count, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields: list[tuple[str, int, int]] = []
    pos, off = 1, 32  # byte 0 de cada registro é a marca de apagado
    while off + 32 <= header_len and data[off] != 0x0D:
        name = data[off : off + 11].split(b"\0")[0].decode("ascii")
        length = data[off + 16]
        fields.append((name, pos, length))
        pos += length
        off += 32
    # Se o PDV estiver gravando, o cabeçalho pode prometer mais registros do que o arquivo tem.
    count = min(count, (len(data) - header_len) // record_len)
    for i in range(count):
        rec = data[header_len + i * record_len : header_len + (i + 1) * record_len]
        if rec[:1] == b"*":
            continue
        yield {name: rec[p : p + n].decode(ENCODING, "replace").strip() for name, p, n in fields}


def normalize(text: str) -> list[str]:
    """Tokens sem acento, minúsculos, sem palavras vazias; números ficam como '15' ou '15,90'."""
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii")
    return [t for t in _TOKEN.findall(plain) if t not in STOPWORDS]


def _price(token: str) -> float:
    return float(token.replace(",", "."))


def _word_matches(query: str, word: str) -> bool:
    # Tolera plural e palavra incompleta: "canecas" ~ "caneca", "termica" ~ "termic".
    if query == word:
        return True
    short, long_ = sorted((query.rstrip("s"), word.rstrip("s")), key=len)
    return len(short) >= 4 and long_.startswith(short)


def _token_matches(token: str, words: list[str], preco: float) -> bool:
    if token[0].isdigit():
        valor = _price(token)
        # "15" casa com 15,00 e 15,90; "15,90" só com 15,90.
        same_price = int(preco) == int(valor) if valor.is_integer() else abs(preco - valor) < 0.005
        return same_price or token in words
    return any(_word_matches(token, w) for w in words if not w[0].isdigit())


class PdvCatalog:
    def __init__(self, cfg: PdvConfig) -> None:
        """`cfg.exclude`: tipos de produto (ex.: 'SAZONAIS') que existem no cadastro mas não nesta loja."""
        self._path = Path(cfg.dados_dir) / cfg.products_file
        self._fields = cfg.fields
        self._active_status = cfg.active_status
        self._exclude = {" ".join(normalize(t)) for t in cfg.exclude}
        self._mtime: float | None = None
        self._items: list[tuple[PdvProduct, list[str]]] = []

    def products(self) -> list[PdvProduct]:
        self._refresh()
        return [p for p, _ in self._items]

    def types(self) -> list[str]:
        """Tipos de produto do cadastro (descrições sem o preço), sem repetição."""
        self._refresh()
        names = {base_name(p.descricao) for p, _ in self._items}
        return sorted(n for n in names if n)

    def search(self, query: str) -> list[PdvProduct]:
        """Produtos ativos que casam com todos os termos, do mais barato para o mais caro."""
        self._refresh()
        tokens = normalize(query)
        if not tokens:
            return []
        hits = [p for p, words in self._items if all(_token_matches(t, words, p.preco) for t in tokens)]
        hits.sort(key=lambda p: (p.preco, p.descricao))
        return hits

    def _refresh(self) -> None:
        mtime = self._path.stat().st_mtime
        if mtime == self._mtime:
            return
        items = []
        f = self._fields
        for rec in read_dbf(self._path.read_bytes()):
            if rec.get(f.status) != self._active_status:
                continue
            try:
                preco = float(rec.get(f.preco) or 0)
            except ValueError:
                continue
            if preco <= 0:
                continue
            product = PdvProduct(rec.get(f.codigo, "").lstrip("0"), rec.get(f.descricao, ""), preco)
            if " ".join(normalize(base_name(product.descricao))) in self._exclude:
                continue
            items.append((product, normalize(product.descricao)))
        self._items = items
        self._mtime = mtime
        log.info("Catálogo do PDV carregado: %d produtos ativos", len(items))
