"""Inteiro teor de uma publicação do DOU.

O corpo vive em `div.texto-dou`, com parágrafos já classificados pelo portal:
`identifica` (título), `ementa`, `dou-paragraph` (articulado), `assina`, `anexo`.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass

_CORPO = re.compile(r'<div[^>]*class="[^"]*\btexto-dou\b[^"]*"[^>]*>(.*)', re.DOTALL)
# O ato acaba no rodape. Sem esse corte, paragrafos de mobiliario da pagina
# (classe `h6`, avisos de "nao substitui o publicado") entram no inteiro teor.
_FIM_DO_ATO = re.compile(
    r'<div[^>]*class="[^"]*(?:informacao-conteudo-dou|rodape-dou)', re.DOTALL
)
_PARAGRAFO = re.compile(r'<p class="([^"]+)"[^>]*>(.*?)</p>', re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_ESPACOS = re.compile(r"\s+")

# `d-none` e `audience-title` são elementos de interface, não conteúdo do ato.
_CLASSES_IGNORADAS = {"d-none", "audience-title"}


@dataclass(frozen=True)
class TextoDOU:
    identifica: str | None
    ementa: str | None
    texto: str


def _limpar(trecho: str) -> str:
    return _ESPACOS.sub(" ", _html.unescape(_TAG.sub(" ", trecho))).strip()


def extrair_texto(html: str) -> TextoDOU:
    """Extrai título, ementa e inteiro teor da página de uma publicação."""
    corpo = _CORPO.search(html)
    if not corpo:
        return TextoDOU(identifica=None, ementa=None, texto="")

    # Corta no rodape quando ele existe; senao vai ate o fim do documento.
    regiao = corpo.group(1)
    rodape = _FIM_DO_ATO.search(regiao)
    if rodape:
        regiao = regiao[: rodape.start()]

    identifica: str | None = None
    ementa: str | None = None
    linhas: list[str] = []

    for match in _PARAGRAFO.finditer(regiao):
        classes, conteudo = match.groups()
        nomes = set(classes.split())
        if nomes & _CLASSES_IGNORADAS:
            continue
        limpo = _limpar(conteudo)
        if not limpo:
            continue
        if "identifica" in nomes and identifica is None:
            identifica = limpo
        elif "ementa" in nomes and ementa is None:
            ementa = limpo
        linhas.append(limpo)

    return TextoDOU(identifica=identifica, ementa=ementa, texto="\n".join(linhas))
