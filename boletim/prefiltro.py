"""Triagem determinística antes do LLM: barata, auditável e reversível.

Mandar o diário inteiro para o modelo custa caro e, pior, dilui o julgamento em
centenas de nomeações e extratos de contrato. Aqui só entram regras que um
humano consegue conferir lendo o regex — nada de "achismo" antes da hora. O que
o prefiltro descarta fica registrado com a regra que o descartou, para que uma
regra ruim possa ser encontrada e corrigida.

A retenção forte vence o descarte de propósito: uma portaria que nomeia o
gestor E habilita leitos é, para quem capta recurso, uma habilitação.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from boletim.config import ConfigBoletim
from radar.core.modelos import Publicacao

# Ruído de diário oficial: ato de pessoal, contrato e aviso de licitação.
_DESCARTE = re.compile(
    r"nomea|exonera|designa|dispensa (de )?(servidor|função)|férias|diária"
    r"|boletim de serviço|ata de registro de preços|aviso de licitação"
    r"|extrato de (contrato|termo aditivo|inexigibilidade|dispensa)"
    r"|aviso de (homologação|suspensão)|resultado de julgamento|resolução-re\b"
    r"|autorização de funcionamento|cancelamento de registro|torna sem efeito"
    r"|concede férias",
    re.IGNORECASE,
)

# Vocabulário de dinheiro e de regra: o que o gestor que capta recurso procura.
_FORTE = re.compile(
    r"habilita|credencia|desabilita|teto (mac|financeiro)|limite financeiro"
    r"|incremento|custeio|investimento|emenda parlamentar|fundo a fundo"
    r"|fundo nacional de saúde|repasse|transfer(e|ência) de recursos|r\$\s?\d"
    r"|cib[- ]sus|deliberação|programação (orçamentária|assistencial)"
    r"|crédito (suplementar|especial|extraordinário)|\bloa\b|\bldo\b"
    r"|lei orçamentária|altera .{0,40}(critério|piso|prazo)|\brdc\b"
    r"|chamamento público|edital",
    re.IGNORECASE,
)

_VALOR = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})")

_MAIUSCULA = "A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ"
_PALAVRA = rf"[{_MAIUSCULA}][^\W\d_]*"
_LIGACAO = r"(?:de|do|da|dos|das)"
_MARCADOR = r"Munic[íi]pios? de|Hospital|Santa Casa|Funda[çc][ãa]o|Instituto"
# O marcador entra no nome: "César Leite" sozinho é nome de pessoa, "Hospital
# César Leite" é a entidade que o gestor reconhece. O nome corre por palavras
# capitalizadas e conectivos ("Santa Casa de Misericórdia de Belo Horizonte") e
# para na primeira pontuação ou palavra comum.
_ENTE = re.compile(rf"(?:{_MARCADOR})(?:\s+(?:{_PALAVRA}|{_LIGACAO}))+")
_TERMINA_EM_LIGACAO = re.compile(rf"\s+{_LIGACAO}$", re.IGNORECASE)

MAX_ENTES = 10
_CHARS_EMENTA = 400
_CHARS_TEXTO_FORTE = 2000


@dataclass(frozen=True)
class Descarte:
    id: str
    regra: str


@dataclass(frozen=True)
class Triagem:
    mantidas: tuple[Publicacao, ...]
    descartadas: tuple[Descarte, ...]
    avisos: tuple[str, ...] = ()


def valores_brl(texto: str) -> tuple[float, ...]:
    """Valores em reais citados no texto, na ordem em que aparecem.

    Só com a cifra: um "1.234,00" solto tanto pode ser dinheiro quanto
    quantidade de leitos, e inventar valor é o pior erro possível aqui.
    """
    return tuple(
        float(f"{inteiro.replace('.', '')}.{centavos}")
        for inteiro, centavos in _VALOR.findall(texto)
    )


def entes_candidatos(texto: str) -> tuple[str, ...]:
    """Municípios, hospitais e fundações nominais citados no texto.

    Candidatos, não verdades: servem de pista para o LLM e para o prefiltro,
    e são deduplicados preservando a ordem de aparição.
    """
    encontrados: list[str] = []
    for bruto in _ENTE.findall(texto):
        nome = _TERMINA_EM_LIGACAO.sub("", bruto).strip()
        if nome not in encontrados:
            encontrados.append(nome)
        if len(encontrados) == MAX_ENTES:
            break
    return tuple(encontrados)


def triar(pubs: Sequence[Publicacao], cfg: ConfigBoletim) -> Triagem:
    """Separa o que vale a pena classificar do ruído previsível do diário."""
    mantidas: list[Publicacao] = []
    descartadas: list[Descarte] = []

    for pub in pubs:
        if pub.fonte in ("dou", "inlabs") and pub.secao == "2":
            descartadas.append(Descarte(pub.id, "secao_2"))
            continue
        alvo = _alvo(pub)
        # A retenção forte olha também o corpo do ato: o dinheiro costuma
        # aparecer no artigo, não na ementa.
        if _FORTE.search(f"{alvo} {pub.texto[:_CHARS_TEXTO_FORTE]}"):
            mantidas.append(pub)
            continue
        if _DESCARTE.search(alvo):
            descartadas.append(Descarte(pub.id, "descarte"))
            continue
        mantidas.append(pub)

    avisos: list[str] = []
    if len(mantidas) > cfg.max_itens_dia:
        # `sorted` é estável: entre itens de força igual vale a ordem do diário.
        por_forca = sorted(mantidas, key=_forca, reverse=True)
        cortadas = por_forca[cfg.max_itens_dia:]
        mantidas = por_forca[: cfg.max_itens_dia]
        descartadas.extend(Descarte(p.id, "teto") for p in cortadas)
        avisos.append(
            f"{len(cortadas)} itens além do teto de {cfg.max_itens_dia} "
            "não foram classificados"
        )

    return Triagem(tuple(mantidas), tuple(descartadas), tuple(avisos))


def _alvo(pub: Publicacao) -> str:
    return " ".join([pub.tipo or "", pub.titulo, (pub.ementa or "")[:_CHARS_EMENTA]])


def _forca(pub: Publicacao) -> int:
    """Quantos termos fortes distintos a publicação traz.

    Distintos, e não ocorrências: uma portaria que repete "custeio" seis vezes
    não é mais relevante que uma que fala de teto MAC, repasse e habilitação.
    """
    alvo = f"{_alvo(pub)} {pub.texto[:_CHARS_TEXTO_FORTE]}"
    return len({achado.group(0).lower() for achado in _FORTE.finditer(alvo)})
