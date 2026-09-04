"""Converte um item da busca do DOU em `Publicacao`."""

from __future__ import annotations

import re
from datetime import date, datetime

from radar.core.modelos import Publicacao, gerar_id
from radar.fontes.dou.busca import url_publicacao
from radar.fontes.dou.texto import TextoDOU

# `pubName` é a seção real do diário, informada pela fonte.
_SECAO_POR_PUBNAME = {"DO1": "1", "DO2": "2", "DO3": "3"}
# Exige o simbolo ordinal de verdade. Incluir "o" na classe faria a palavra
# "no" casar sob IGNORECASE, e "Plano 2026" viraria numero de ato 2026 —
# invencao de dado, que e exatamente o que este pacote nao pode fazer.
# Medido sobre os 118 titulos reais das fixtures: a forma estrita extrai os
# mesmos 62 numeros que a frouxa, sem perder nada.
_PADRAO_NUMERO = re.compile(r"\bN[º°]\s*([\d][\d.\-/]*)", re.IGNORECASE)


def _numero(titulo: str) -> str | None:
    achado = _PADRAO_NUMERO.search(titulo)
    return achado.group(1).rstrip(".,") if achado else None


def _inteiro(valor) -> int | None:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def normalizar(
    item: dict,
    texto: TextoDOU | None,
    data_publicacao: date,
    coletado_em: datetime,
) -> Publicacao:
    """Normaliza sem inferir: o que a fonte não informa vira `None`."""
    titulo = (item.get("title") or "").strip()
    url = url_publicacao(item.get("urlTitle", ""))

    hierarquia = (item.get("hierarchyStr") or "").split("/")
    orgao = hierarquia[0].strip() if hierarquia and hierarquia[0].strip() else ""
    unidade = hierarquia[1].strip() if len(hierarquia) > 1 and hierarquia[1].strip() else None

    if texto is not None and texto.texto:
        corpo = texto.texto
        ementa = texto.ementa
    else:
        corpo = item.get("content", "") or ""
        ementa = None

    return Publicacao(
        id=gerar_id("dou", data_publicacao, url, titulo),
        fonte="dou",
        data_publicacao=data_publicacao,
        coletado_em=coletado_em,
        orgao=orgao,
        unidade=unidade,
        secao=_SECAO_POR_PUBNAME.get(item.get("pubName", "")),
        pagina=_inteiro(item.get("numberPage")),
        edicao=str(item["editionNumber"]) if item.get("editionNumber") else None,
        tipo=item.get("artType") or None,
        numero=_numero(titulo),
        titulo=titulo,
        ementa=ementa,
        texto=corpo,
        url=url,
        origem={"metodo": "in.gov.br/consulta", "classPK": item.get("classPK")},
    )
