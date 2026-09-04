from datetime import date, datetime, timezone

from radar.fontes.dou.normaliza import normalizar
from radar.fontes.dou.texto import TextoDOU

QUANDO = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
DIA = date(2026, 9, 4)

ITEM = {
    "pubName": "DO1",
    "artType": "Portaria",
    "hierarchyStr": "Ministério da Saúde/Gabinete do Ministro",
    "urlTitle": "portaria-gm/ms-n-12.141-de-3-de-setembro-de-2026-730143120",
    "title": "Portaria GM/MS Nº 12.141, DE 3 DE setembro DE 2026",
    "content": "Portaria GM/MS Nº 12.141 ... truncado ...",
    "editionNumber": "168",
    "numberPage": "184",
    "pubDate": "04/09/2026",
    "classPK": "730143120",
}


def test_secao_vem_de_pubname():
    assert normalizar(ITEM, None, DIA, QUANDO).secao == "1"
    assert normalizar({**ITEM, "pubName": "DO3"}, None, DIA, QUANDO).secao == "3"


def test_pubname_desconhecido_vira_none_em_vez_de_chute():
    assert normalizar({**ITEM, "pubName": "XX"}, None, DIA, QUANDO).secao is None


def test_tipo_vem_de_arttype():
    assert normalizar(ITEM, None, DIA, QUANDO).tipo == "Portaria"


def test_orgao_e_unidade_saem_da_hierarquia():
    pub = normalizar(ITEM, None, DIA, QUANDO)
    assert pub.orgao == "Ministério da Saúde"
    assert pub.unidade == "Gabinete do Ministro"


def test_hierarquia_sem_barra_deixa_unidade_none():
    pub = normalizar({**ITEM, "hierarchyStr": "Ministério da Saúde"}, None, DIA, QUANDO)
    assert pub.orgao == "Ministério da Saúde"
    assert pub.unidade is None


def test_numero_e_extraido_do_titulo():
    assert normalizar(ITEM, None, DIA, QUANDO).numero == "12.141"


def test_numero_ausente_vira_none_nao_placeholder():
    pub = normalizar({**ITEM, "title": "Aviso de licitação"}, None, DIA, QUANDO)
    assert pub.numero is None


def test_usa_texto_integral_quando_disponivel():
    texto = TextoDOU(identifica="Portaria GM/MS Nº 12.141", ementa="Renova.", texto="Art. 1º Fica renovada.")
    pub = normalizar(ITEM, texto, DIA, QUANDO)
    assert pub.texto == "Art. 1º Fica renovada."
    assert pub.ementa == "Renova."


def test_sem_texto_integral_cai_para_o_content_da_listagem():
    pub = normalizar(ITEM, None, DIA, QUANDO)
    assert pub.texto == ITEM["content"]


def test_url_e_canonica():
    assert normalizar(ITEM, None, DIA, QUANDO).url.startswith("https://www.in.gov.br/web/dou/-/")


def test_pagina_e_inteiro_e_edicao_e_texto():
    pub = normalizar(ITEM, None, DIA, QUANDO)
    assert pub.pagina == 184
    assert pub.edicao == "168"


def test_origem_registra_a_procedencia():
    origem = normalizar(ITEM, None, DIA, QUANDO).origem
    assert origem["classPK"] == "730143120"
    assert origem["metodo"] == "in.gov.br/consulta"


def test_nao_ha_campo_de_juizo():
    pub = normalizar(ITEM, None, DIA, QUANDO)
    for proibido in ("score", "is_sus", "impacto", "relevancia"):
        assert not hasattr(pub, proibido)
