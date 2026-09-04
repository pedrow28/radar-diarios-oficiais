"""Recorte e limpeza do PDF do IOF-MG.

O intervalo de páginas de cada órgão vem do índice que a própria API entrega em
`cadernos[].secoes[]`, o que dispensa parsear o sumário impresso.
"""

from __future__ import annotations

import re

import fitz

from radar.core.erros import SemEdicao

# Linha feita APENAS de mobiliario de pagina, uma ou mais pecas. A ancora de
# linha e obrigatoria: "MINAS GERAIS" aparece 27 vezes DENTRO do corpo dos
# atos ("FUNDACAO HOSPITALAR DO ESTADO DE MINAS GERAIS - FHEMIG"), e remove-la
# sem ancora mutila o nome das entidades que publicam.
_CABECALHO = re.compile(
    r"^[ \t]*(?:(?:MINAS GERAIS|Diário do Executivo|Diário do Legislativo)[ \t]*)+$",
    re.IGNORECASE | re.MULTILINE,
)
_LINHA_DE_PAGINA = re.compile(
    r"^\s*\d{1,4}\s*[–-]\s*(?:segunda|terça|quarta|quinta|sexta|sábado|domingo)"
    r"[^\n]*\d{4}\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_DATA_E_PAGINA = re.compile(
    r"^\s*(?:segunda|terça|quarta|quinta|sexta|sábado|domingo)[^\n]*\d{4}\s*[–-]\s*\d{1,4}\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# Hífen no fim da linha que quebra uma palavra; o legítimo (CIB-SUS) não é seguido de \n.
_HIFENIZACAO = re.compile(r"(\w)-\s*\n\s*(\w)")
_LINHAS_VAZIAS = re.compile(r"\n{3,}")


def intervalo_da_secao(caderno: dict, secao: str, total_paginas: int) -> tuple[int, int]:
    """Páginas inicial e final do órgão, pelo índice da API.

    O fim é a página inicial da próxima seção — que compartilha essa página —
    ou o total do caderno, se for a última.
    """
    secoes = sorted(caderno.get("secoes", []), key=lambda s: s.get("paginaInicial", 0))
    for posicao, atual in enumerate(secoes):
        if atual.get("descricao") == secao:
            inicio = int(atual["paginaInicial"])
            if posicao + 1 < len(secoes):
                fim = int(secoes[posicao + 1]["paginaInicial"])
            else:
                fim = int(total_paginas)
            return inicio, max(inicio, fim)
    disponiveis = [s.get("descricao") for s in secoes]
    raise SemEdicao(f"Seção {secao!r} não encontrada no caderno. Disponíveis: {disponiveis}")


def proxima_secao(caderno: dict, secao: str) -> str | None:
    """Descrição da seção que começa depois da alvo, ou `None` se for a última."""
    secoes = sorted(caderno.get("secoes", []), key=lambda s: s.get("paginaInicial", 0))
    for posicao, atual in enumerate(secoes):
        if atual.get("descricao") == secao and posicao + 1 < len(secoes):
            return secoes[posicao + 1].get("descricao")
    return None


def truncar_na_proxima_secao(
    paginas: list[tuple[int, str]], proxima: str | None
) -> list[tuple[int, str]]:
    """Corta a última página no cabeçalho da seção seguinte.

    A página de fronteira é compartilhada entre dois órgãos; sem o corte, atos do
    órgão seguinte entram na coleta como se fossem do alvo.
    """
    if not proxima or not paginas:
        return paginas
    numero, texto = paginas[-1]
    posicao = texto.find(proxima)
    if posicao == -1:
        return paginas
    return paginas[:-1] + [(numero, texto[:posicao].rstrip())]


def texto_das_paginas(pdf: bytes, inicio: int, fim: int) -> list[tuple[int, str]]:
    """Texto de cada página do intervalo, 1-indexado e inclusivo."""
    paginas: list[tuple[int, str]] = []
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        ultimo = min(fim, doc.page_count)
        for numero in range(max(1, inicio), ultimo + 1):
            paginas.append((numero, doc[numero - 1].get_text()))
    return paginas


def limpar(texto: str) -> str:
    """Remove cabeçalhos de página e refaz palavras quebradas por hifenização."""
    limpo = _CABECALHO.sub("", texto)
    limpo = _LINHA_DE_PAGINA.sub("", limpo)
    limpo = _DATA_E_PAGINA.sub("", limpo)
    limpo = _HIFENIZACAO.sub(r"\1\2", limpo)
    limpo = _LINHAS_VAZIAS.sub("\n\n", limpo)
    return limpo.strip()
