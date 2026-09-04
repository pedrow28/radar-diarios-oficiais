"""Modelos da edição do boletim: item classificado pelo LLM e edição pronta.

As funções que produzem estes modelos (classificação, montagem da edição)
vêm em tarefas seguintes; aqui só os dados.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Literal

Categoria = Literal["A", "B", "C", "D", "X"]

ROTULOS = {
    "A": "Captação de recursos",
    "B": "Mudança de regra",
    "C": "Editais e chamamentos",
    "D": "Outros atos",
}


@dataclass(frozen=True)
class Item:
    id: str
    fonte: str
    orgao: str
    unidade: str | None
    tipo: str | None
    numero: str | None
    data_publicacao: date
    secao: str | None
    pagina: int | None
    edicao: str | None
    titulo: str
    url: str
    categoria: Categoria
    relevancia: int
    resumo: str
    por_que_importa: str | None = None
    valor_brl: float | None = None
    entes: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    fallback: bool = False


@dataclass(frozen=True)
class FonteResumo:
    nome: str
    status: str
    edicao: str | None
    paginas: str | None
    avisos: tuple[str, ...] = ()


@dataclass(frozen=True)
class Edicao:
    data: date
    titulo: str
    em_30_segundos: tuple[str, ...]
    intro: str
    secoes: dict[str, tuple[Item, ...]]  # chaves "A","B","C","D"
    fontes: tuple[FonteResumo, ...]
    parcial: bool
    gerado_em: datetime

    def total_relevante(self) -> int:
        return sum(len(self.secoes.get(cat, ())) for cat in ("A", "B", "C"))


def item_para_dict(item: Item) -> dict[str, Any]:
    """Serializa um `Item` para `itens.json`: datas em ISO, tuplas em listas."""
    d = asdict(item)
    d["data_publicacao"] = item.data_publicacao.isoformat()
    d["entes"] = list(item.entes)
    d["tags"] = list(item.tags)
    return d


def item_de_dict(d: dict[str, Any]) -> Item:
    """Reconstrói um `Item` a partir do dict lido de `itens.json`."""
    campos = dict(d)
    campos["data_publicacao"] = date.fromisoformat(campos["data_publicacao"])
    campos["entes"] = tuple(campos.get("entes", ()))
    campos["tags"] = tuple(campos.get("tags", ()))
    return Item(**campos)
