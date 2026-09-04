"""Converte um segmento do IOF-MG em `Publicacao`."""

from __future__ import annotations

import json
from datetime import date, datetime
from urllib.parse import quote

from radar.core.modelos import Publicacao, gerar_id
from radar.fontes.iofmg.segmenta import Bruto

_BASE_EDICAO = "https://www.jornalminasgerais.mg.gov.br/edicao-do-dia?dados="


def url_pagina(data: date, id_caderno: int | None, pagina: int) -> str | None:
    """Link para a página no visualizador do Jornal MG.

    Sem o id do caderno da própria edição não há link correto — devolvemos
    `None` em vez de um link que aponta para a edição errada.
    """
    if id_caderno is None:
        return None
    payload = {
        "dataPublicacaoSelecionada": f"{data.isoformat()}T03:00:00.000Z",
        "idCadernoEdicaoSelecionado": id_caderno,
        "paginaSelecionada": pagina,
    }
    return _BASE_EDICAO + quote(json.dumps(payload, separators=(",", ":")))


def normalizar(
    bruto: Bruto,
    data_publicacao: date,
    coletado_em: datetime,
    id_caderno: int | None,
    orgao: str,
) -> Publicacao:
    url = url_pagina(data_publicacao, id_caderno, bruto.pagina) or ""
    ementa = bruto.texto.split(".")[0][:300] if bruto.texto else None
    return Publicacao(
        id=gerar_id("iofmg", data_publicacao, url or bruto.titulo, bruto.titulo),
        fonte="iofmg",
        data_publicacao=data_publicacao,
        coletado_em=coletado_em,
        orgao=orgao,
        unidade=None,
        secao=None,  # IOF-MG não tem Seção 1/2/3.
        pagina=bruto.pagina,
        edicao=str(id_caderno) if id_caderno is not None else None,
        tipo=bruto.tipo,
        numero=bruto.numero,
        titulo=bruto.titulo,
        ementa=ementa,
        texto=bruto.texto,
        url=url,
        origem={"metodo": "api jornalminasgerais", "id_caderno": id_caderno},
    )
