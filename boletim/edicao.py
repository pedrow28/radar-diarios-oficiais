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
from radar.core.log import configurar_log

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
_MAX_BULLETS_FALLBACK = 3

# Conectivos ficam fora da conta de proporção: "de" e "do" de um nome de
# instituição diluiriam qualquer título até ele passar.
_CONECTIVOS = frozenset(
    "de da do dos das e em para por com no na a o os as que ao à".split()
)
_MIN_CAPITALIZADAS_TITULO_CASE = 4
_FRACAO_TITULO_CASE = 0.6

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
            "Title Case: a frase inteira está capitalizada; escreva em formato de sentença"
        )
    return erros


def sem_travessao(texto: str) -> str:
    """Troca travessão e meia-risca por hífen, conforme a diretriz de marca.

    Vale para o texto do LLM e para o do diário: o em-dash entra por copiar e
    colar de PDF, e um único deles numa peça já quebra a voz.
    """
    return _TRAVESSAO.sub("-", texto)


def _tem_title_case(texto: str) -> bool:
    """Title Case da frase, não nome próprio dentro dela.

    A regra antiga reprovava 4 iniciais maiúsculas seguidas, e com isso
    "Programa Agora Tem Especialistas" - o nome de um programa federal que
    aparece em quase todo dia da semana - derrubava o título editorial. Na
    primeira semana real isso custou 3 dos 5 títulos.

    O que separa "Habilitações Do Programa Somam Cento E Oitenta Milhões" de
    "3 habilitações do Programa Agora Tem Especialistas somam R$ 180 milhões"
    é a proporção: no primeiro a frase inteira está capitalizada, no segundo o
    nome próprio é uma ilha de 4 palavras num texto de 7. Siglas, números e
    conectivos ficam fora da conta - "de" e "do" de um nome de instituição
    diluiriam qualquer título.
    """
    palavras: list[str] = []
    for bruto in texto.split():
        palavra = bruto.strip(_PONTUACAO)
        if not palavra or not palavra[0].isalpha():
            continue  # número, cifra, marcador
        if palavra.isupper():
            continue  # sigla: "MAC", "SES-MG", "CIB-SUS/MG"
        if palavra.lower() in _CONECTIVOS:
            continue
        palavras.append(palavra)

    capitalizadas = sum(1 for p in palavras if p[0].isupper())
    if capitalizadas < _MIN_CAPITALIZADAS_TITULO_CASE:
        return False
    return capitalizadas / len(palavras) >= _FRACAO_TITULO_CASE


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
    logger = configurar_log()
    contagens = {cat: len(secoes[cat]) for cat in ROTULOS}
    base = montar_editorial(relevantes, contagens, data)
    prompt = base
    erros: list[str] = []

    for _ in range(2):
        try:
            resposta = llm.completar_json(
                SISTEMA_EDITORIAL, prompt, EDITORIAL_SCHEMA, rotulo="editorial"
            )
        except LLMIndisponivel as exc:
            logger.warning("editorial: LLM indisponível (%s), título determinístico", exc)
            break
        erros = validar(resposta, EDITORIAL_SCHEMA)
        if not erros:
            # Travessão é erro de digitação, não de julgamento: normalizar antes
            # de validar poupa uma chamada e não deixa o dia sem título quando o
            # modelo insiste no em-dash.
            resposta = _normalizado(resposta)
            erros = _erros_de_voz(resposta)
        if not erros:
            return (
                resposta["titulo"],
                tuple(resposta["em_30_segundos"]),
                resposta["intro"],
            )
        prompt = f"{base}\n\nCorreções obrigatórias: {'; '.join(erros)}"
    else:
        # O `for` terminou sem `break`: as duas tentativas caíram na
        # validação (schema ou voz), não no LLM fora do ar.
        logger.warning("editorial: voz reprovada 2x: %s", "; ".join(erros))

    return (
        titulo_fallback(data, len(relevantes)),
        tuple(i.resumo for i in relevantes[:_MAX_BULLETS_FALLBACK]),
        f"O radar encontrou {len(relevantes)} publicações relevantes nesta data. "
        "O texto de abertura não pôde ser gerado, e os destaques abaixo saem "
        "direto da classificação.",
    )


def _normalizado(editorial: dict[str, Any]) -> dict[str, Any]:
    """Aplica a normalização determinística de traço nos três campos."""
    return {
        "titulo": sem_travessao(editorial["titulo"]),
        "em_30_segundos": [sem_travessao(b) for b in editorial["em_30_segundos"]],
        "intro": sem_travessao(editorial["intro"]),
    }


def _erros_de_voz(editorial: dict[str, Any]) -> list[str]:
    partes = [editorial["titulo"], editorial["intro"], *editorial["em_30_segundos"]]
    erros: list[str] = []
    for parte in partes:
        for erro in validar_voz(parte):
            if erro not in erros:
                erros.append(erro)
    return erros
