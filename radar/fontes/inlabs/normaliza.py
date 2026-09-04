"""Converte um `Artigo` do INLABS em `Publicacao`.

Mesma saída da fonte `dou`, e por isso reusa dela o mapa de seções, a extração
de número e a leitura do articulado: são o mesmo diário, servido por outra
porta. O que a fonte não informa vira `None` — nunca é inferido.
"""

from __future__ import annotations

import html as _html
import re
from datetime import date, datetime

from radar.core.modelos import Publicacao, gerar_id
from radar.fontes.dou.normaliza import _SECAO_POR_PUBNAME, _inteiro, _numero
from radar.fontes.dou.texto import extrair_texto

# Sem `pdfPage` não há link do ato; o portal do serviço é o mais específico
# que se pode apontar sem inventar uma URL que talvez não exista.
URL_PADRAO = "https://inlabs.in.gov.br/"

_TAG = re.compile(r"<[^>]+>")
_ESPACOS = re.compile(r"\s+")


def _sem_tags(html: str) -> str:
    """Último recurso quando o articulado não usa as classes do portal."""
    return _ESPACOS.sub(" ", _html.unescape(_TAG.sub(" ", html))).strip()


def _secao(pub_name: str) -> tuple[str | None, bool]:
    """Devolve a seção e se a edição é extra.

    `DO1E` é a edição extra da Seção 1: a seção é a mesma, o que muda é a
    procedência. Marcá-la separadamente evita tanto perder o ato (seção
    desconhecida) quanto apagar a diferença (extra virando edição comum).
    """
    if pub_name in _SECAO_POR_PUBNAME:
        return _SECAO_POR_PUBNAME[pub_name], False
    if pub_name.endswith("E") and pub_name[:-1] in _SECAO_POR_PUBNAME:
        return _SECAO_POR_PUBNAME[pub_name[:-1]], True
    return None, False


def normalizar(a, data: date, coletado_em: datetime) -> Publicacao:
    niveis = [n.strip() for n in a.art_category.split("/")]
    orgao = niveis[0] if niveis and niveis[0] else ""
    unidade = niveis[1] if len(niveis) > 1 and niveis[1] else None

    secao, extra = _secao(a.pub_name)
    titulo = a.identifica or a.nome

    extraido = extrair_texto(f'<div class="texto-dou">{a.texto_html}</div>')
    texto = extraido.texto or _sem_tags(a.texto_html)
    # A `Ementa` do XML é declarada pela fonte; a extraída é leitura nossa do
    # parágrafo `ementa`. Entre as duas, vale a que a fonte assinou.
    ementa = a.ementa or extraido.ementa or None

    url = a.pdf_page or URL_PADRAO
    origem = {
        "metodo": "inlabs",
        "id_materia": a.id_materia,
        # `orgao`/`unidade` guardam só dois níveis, e a ANVISA aparece no
        # terceiro. A hierarquia inteira fica aqui.
        "art_category": a.art_category,
        "pub_name": a.pub_name,
        "texto_integral": True,
    }
    if extra:
        origem["extra"] = True
    if not a.pdf_page:
        origem["url_fallback"] = True

    return Publicacao(
        id=gerar_id("inlabs", data, url, titulo),
        fonte="inlabs",
        data_publicacao=data,
        coletado_em=coletado_em,
        orgao=orgao,
        unidade=unidade,
        secao=secao,
        pagina=_inteiro(a.number_page),
        edicao=a.edition_number or None,
        tipo=a.art_type or None,
        # A designação do ato está em `Identifica`/`Titulo`. `name` é o rótulo
        # do arquivo no serviço e pode trazer número de outro ato citado.
        numero=_numero(a.identifica or a.titulo),
        titulo=titulo,
        ementa=ementa,
        texto=texto,
        url=url,
        origem=origem,
    )
