"""Quebra o texto de um órgão em publicações discretas.

Herda a ideia do `parse_publications_ses` do scraper antigo, com âncora mais
forte: só é cabeçalho a linha que começa com um tipo configurado E traz número
ou data. Sem isso, `DELIBERA:` e `Resoluções que menciona.` viram publicações.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from radar.fontes.iofmg.pdf import limpar

_NUMERO = re.compile(r"N[º°o]?\s*([\d][\d.]*)", re.IGNORECASE)
_TEM_DATA = re.compile(r"\bDE\s+\d{1,2}\s+DE\s+[A-ZÇÃÊÉÓÍÚÂÔ]+\s+DE\s+\d{4}", re.IGNORECASE)


@dataclass(frozen=True)
class Bruto:
    tipo: str
    numero: str | None
    titulo: str
    texto: str
    pagina: int


def _compilar(tipos: list[str]) -> re.Pattern:
    alternativas = "|".join(
        re.escape(t.upper()) for t in sorted(tipos, key=len, reverse=True)
    )
    # Cabeçalho começa a linha, é CAIXA ALTA e não é seguido imediatamente de
    # ':' (DELIBERA:). Sem `IGNORECASE` de propósito: a extração do PDF quebra a
    # linha no meio da frase, e uma citação em caixa mista no começo de uma linha
    # ("Resolução SES nº 8.994/2023, ...") virava cabeçalho — inventando uma
    # publicação inexistente e cortando o inteiro teor do ato de verdade.
    return re.compile(rf"^\s*({alternativas})(?![:A-ZÇ])(.*)$", re.MULTILINE)


def _e_cabecalho(tipo: str, resto: str) -> bool:
    """Só aceita como cabeçalho o que traz número ou data — o que um ato sempre traz."""
    linha = f"{tipo} {resto}"
    return bool(_NUMERO.search(linha) or _TEM_DATA.search(linha))


def segmentar(paginas: list[tuple[int, str]], tipos: list[str]) -> list[Bruto]:
    """Devolve as publicações encontradas, em ordem de aparição."""
    if not tipos:
        return []
    padrao = _compilar(tipos)
    achados: list[Bruto] = []

    for numero_pagina, bruto in paginas:
        texto = limpar(bruto)
        marcas = [
            (m.start(), m.end(), m.group(1).upper(), m.group(0).strip())
            for m in padrao.finditer(texto)
            if _e_cabecalho(m.group(1), m.group(2))
        ]
        for posicao, (inicio, fim, tipo, titulo) in enumerate(marcas):
            limite = marcas[posicao + 1][0] if posicao + 1 < len(marcas) else len(texto)
            corpo = texto[fim:limite].strip()
            if not corpo:
                continue
            achado_numero = _NUMERO.search(titulo)
            achados.append(
                Bruto(
                    tipo=tipo,
                    numero=achado_numero.group(1).rstrip(".") if achado_numero else None,
                    titulo=titulo,
                    texto=corpo,
                    pagina=numero_pagina,
                )
            )
    return achados
