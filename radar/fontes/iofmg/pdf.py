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
# A extração do PDF insere um espaço depois do ponto de milhar: "5. 953",
# "R$ 168. 895. 626,43", "MASP 1. 130. 647-9". Isso produz número de ato
# ERRADO ("5" em vez de "5.953" — quatro deliberações viram todas "5") e
# mutila os valores em reais, que são o principal sinal de captação.
# Medido nas duas edições reais: 166 normalizações, zero falsos positivos.
_MILHAR_QUEBRADO = re.compile(r"(?<=\d)\.[ ]+(?=\d{3}(?!\d))")
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


def posicao_do_cabecalho(texto: str, secao: str) -> int | None:
    """Offset do cabeçalho do órgão no texto da página, ou `None` se não houver.

    Duas exigências, e as duas foram medidas nas edições reais:

    - **Âncora de linha.** "Secretaria de Estado de Saúde" aparece no corpo dos
      atos ("no âmbito da Secretaria de Estado de Saúde;"). Um `find` cru acha a
      menção antes do cabeçalho e o corte destruiria o órgão inteiro.
    - **Tolerância à quebra de linha.** A coluna estreita do PDF parte o
      cabeçalho em duas linhas ("Secretaria de \\nEstado de Saúde"), então o
      espaço entre as palavras precisa casar `\\s+`.
    """
    if not secao:
        return None
    partes = [re.escape(p) for p in secao.split()]
    if not partes:
        return None
    padrao = re.compile(r"^[ \t]*" + r"\s+".join(partes) + r"[ \t]*$", re.MULTILINE)
    achado = padrao.search(texto)
    return achado.start() if achado else None


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
    posicao = posicao_do_cabecalho(texto, proxima)
    if posicao is None:
        return paginas
    return paginas[:-1] + [(numero, texto[:posicao].rstrip())]


def truncar_antes_da_secao(
    paginas: list[tuple[int, str]], secao: str | None
) -> list[tuple[int, str]]:
    """Corta a primeira página no cabeçalho do órgão alvo.

    Simétrica de `truncar_na_proxima_secao`: a primeira página do intervalo é
    tão compartilhada quanto a última, só que com o órgão *anterior*. Sem este
    corte, atos alheios entram na coleta com procedência falsa — medido em
    02/09, onde `PORTARIA Nº 35` é do IPSEMG e vinha rotulada como da Secretaria
    de Estado de Saúde.

    Se o cabeçalho não aparecer, nada é cortado: perder conteúdo em silêncio
    seria pior que carregar a sobra da fronteira.
    """
    if not secao or not paginas:
        return paginas
    numero, texto = paginas[0]
    posicao = posicao_do_cabecalho(texto, secao)
    if posicao is None:
        return paginas
    return [(numero, texto[posicao:].lstrip())] + paginas[1:]


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
    limpo = _MILHAR_QUEBRADO.sub(".", limpo)
    limpo = _HIFENIZACAO.sub(r"\1\2", limpo)
    limpo = _LINHAS_VAZIAS.sub("\n\n", limpo)
    return limpo.strip()
