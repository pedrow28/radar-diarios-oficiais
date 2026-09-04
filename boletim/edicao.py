"""Modelos da edição do boletim e a montagem da edição do dia.

A edição é o produto final: título, "em 30 segundos", intro e os itens já
separados por seção. O texto de abertura é a única parte escrita pelo LLM, e
por isso é a única que passa por `validar_voz` antes de virar edição - o resto
são fatos que vieram do diário.

Quando o modelo erra a voz duas vezes, ou está fora do ar, a edição sai com
título e destaques determinísticos. Boletim atrasado não serve para quem
precisa do prazo de um edital.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Sequence

from boletim.esquemas import EDITORIAL_SCHEMA, validar
from boletim.llm import LLM, LLMIndisponivel
from boletim.prompts import SISTEMA_EDITORIAL, montar_editorial

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


# ── montagem da edição ──────────────────────────────────────────────────
_TRAVESSAO = re.compile(r"[—–]")
_EMOJI = re.compile(r"[🌀-🫿☀-➿]")
_PROIBIDAS = re.compile(r"\b(dica|truque)\b", re.IGNORECASE)
_PONTUACAO = ".,;:!?()[]\"'"
_MAX_TITULO_CASE = 3
_MAX_BULLETS_FALLBACK = 3

SEM_RELEVANTES = "Sem publicações relevantes nesta data"
INTRO_SEM_RELEVANTES = (
    "Nenhuma publicação de captação de recursos, mudança de regra ou edital nesta "
    "data. O radar segue lendo o Diário Oficial da União e o Diário Oficial de "
    "Minas Gerais no próximo dia útil."
)


def ordenar(itens: Sequence[Item]) -> dict[str, tuple[Item, ...]]:
    """Agrupa por seção na ordem em que o gestor lê. X fica de fora da edição.

    Em A o desempate é o valor: entre duas habilitações igualmente relevantes,
    quem lê quer ver primeiro a que move mais dinheiro.
    """
    por_categoria = {
        cat: [i for i in itens if i.categoria == cat] for cat in ROTULOS
    }
    return {
        "A": tuple(
            sorted(
                por_categoria["A"],
                key=lambda i: (-i.relevancia, -(i.valor_brl or 0.0)),
            )
        ),
        "B": tuple(sorted(por_categoria["B"], key=lambda i: -i.relevancia)),
        "C": tuple(sorted(por_categoria["C"], key=lambda i: -i.relevancia)),
        "D": tuple(sorted(por_categoria["D"], key=lambda i: i.titulo)),
    }


def validar_voz(texto: str) -> list[str]:
    """Erros de voz Thauma no texto. Lista vazia significa aprovado.

    Devolve todos de uma vez porque a lista vira a instrução de correção na
    segunda tentativa do modelo.
    """
    erros: list[str] = []
    if _TRAVESSAO.search(texto):
        erros.append("travessão encontrado; use hífen (-)")
    if _EMOJI.search(texto):
        erros.append("emoji encontrado; o boletim não usa emoji")
    if "?" in texto:
        erros.append("pergunta retórica; escreva em afirmativa")
    for achado in set(m.group(0).lower() for m in _PROIBIDAS.finditer(texto)):
        erros.append(f'palavra proibida: "{achado}"')
    if _tem_title_case(texto):
        erros.append(
            f"Title Case: mais de {_MAX_TITULO_CASE} palavras seguidas em maiúscula"
        )
    return erros


def _tem_title_case(texto: str) -> bool:
    """Siglas não contam: "teto MAC ampliado" é sentença, não Title Case."""
    seguidas = 0
    for bruto in texto.split():
        palavra = bruto.strip(_PONTUACAO)
        if not palavra:
            continue
        if palavra.isupper():
            continue
        if palavra[0].isalpha() and palavra[0].isupper():
            seguidas += 1
            if seguidas > _MAX_TITULO_CASE:
                return True
        else:
            seguidas = 0
    return False


def titulo_fallback(data: date, n: int) -> str:
    """Título sem LLM: factual, com número, e sempre aprovado na voz."""
    return f"Boletim de {data:%d/%m/%Y}: {n} publicações relevantes"


def montar_edicao(
    itens: Sequence[Item],
    fontes: Sequence[FonteResumo],
    parcial: bool,
    llm: LLM,
    data: date,
    agora: datetime,
) -> Edicao:
    """Monta a edição do dia, com ou sem o texto de abertura do LLM."""
    secoes = ordenar(itens)
    relevantes = [*secoes["A"], *secoes["B"], *secoes["C"]]
    if relevantes:
        titulo, em_30_segundos, intro = _abertura(relevantes, secoes, llm, data)
    else:
        titulo, em_30_segundos, intro = _abertura_sem_relevantes(secoes["D"], data)

    return Edicao(
        data=data,
        titulo=titulo,
        em_30_segundos=em_30_segundos,
        intro=intro,
        secoes=secoes,
        fontes=tuple(fontes),
        # Item em fallback também torna o dia parcial: a edição saiu, mas com
        # uma parte do julgamento faltando.
        parcial=parcial or any(i.fallback for i in itens),
        gerado_em=agora,
    )


def _abertura_sem_relevantes(
    outros: tuple[Item, ...], data: date
) -> tuple[str, tuple[str, ...], str]:
    """Abertura de um dia sem A, B nem C, escrita sem chamar o LLM.

    Não há o que resumir, e gastar uma chamada para escrever "não houve nada"
    é dinheiro fora.
    """
    destaques = tuple(i.titulo for i in outros[:_MAX_BULLETS_FALLBACK])
    return (
        titulo_fallback(data, 0),
        destaques or (SEM_RELEVANTES,),
        INTRO_SEM_RELEVANTES,
    )


def _abertura(
    relevantes: list[Item],
    secoes: dict[str, tuple[Item, ...]],
    llm: LLM,
    data: date,
) -> tuple[str, tuple[str, ...], str]:
    """Pede a abertura ao LLM, com uma segunda chance quando a voz reprova.

    A segunda chamada leva as correções junto: sem dizer o que estava errado,
    repetir o mesmo prompt tende a produzir o mesmo travessão.
    """
    contagens = {cat: len(secoes[cat]) for cat in ROTULOS}
    base = montar_editorial(relevantes, contagens, data)
    prompt = base

    for _ in range(2):
        try:
            resposta = llm.completar_json(
                SISTEMA_EDITORIAL, prompt, EDITORIAL_SCHEMA, rotulo="editorial"
            )
        except LLMIndisponivel:
            break
        erros = validar(resposta, EDITORIAL_SCHEMA) or _erros_de_voz(resposta)
        if not erros:
            return (
                resposta["titulo"],
                tuple(resposta["em_30_segundos"]),
                resposta["intro"],
            )
        prompt = f"{base}\n\nCorreções obrigatórias: {'; '.join(erros)}"

    return (
        titulo_fallback(data, len(relevantes)),
        tuple(i.resumo for i in relevantes[:_MAX_BULLETS_FALLBACK]),
        f"O radar encontrou {len(relevantes)} publicações relevantes nesta data. "
        "O texto de abertura não pôde ser gerado, e os destaques abaixo saem "
        "direto da classificação.",
    )


def _erros_de_voz(editorial: dict[str, Any]) -> list[str]:
    partes = [editorial["titulo"], editorial["intro"], *editorial["em_30_segundos"]]
    erros: list[str] = []
    for parte in partes:
        for erro in validar_voz(parte):
            if erro not in erros:
                erros.append(erro)
    return erros
