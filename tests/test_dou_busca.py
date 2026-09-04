import json
from datetime import date
from pathlib import Path

import pytest

from radar.fontes.dou.busca import (
    ID_BLOCO_JSON,
    decodificar_busca,
    extrair_jsonarray,
    montar_url_busca,
    total_de_resultados,
    url_publicacao,
)


@pytest.fixture
def html_busca(dir_fixtures: Path) -> str:
    return decodificar_busca((dir_fixtures / "dou" / "busca-ms-2026-09-03-p1.html").read_bytes())


def test_decodifica_em_utf8_preservando_acentuacao(html_busca: str):
    """Acento intacto e sem mojibake. Regressao critica de encoding."""
    assert "Ministério da Saúde" in html_busca
    # Sinais de ter lido UTF-8 como latin-1:
    assert "Ã©" not in html_busca
    assert "Âº" not in html_busca
    assert "�" not in html_busca


def test_cai_para_latin1_se_os_bytes_nao_forem_utf8_valido():
    """Rede de seguranca caso o portal mude o encoding servido."""
    bruto = "Ministério".encode("iso-8859-1")  # invalido em UTF-8
    assert decodificar_busca(bruto) == "Ministério"


def test_extrai_os_itens_do_bloco_json(html_busca: str):
    itens = extrair_jsonarray(html_busca)
    assert len(itens) == 75


def test_itens_trazem_os_campos_que_substituem_heuristica(html_busca: str):
    item = extrair_jsonarray(html_busca)[0]
    for campo in ("pubName", "artType", "hierarchyStr", "urlTitle", "title", "pubDate"):
        assert campo in item, campo


def test_secao_vem_da_fonte_e_cobre_as_tres(html_busca: str):
    secoes = {i["pubName"] for i in extrair_jsonarray(html_busca)}
    assert secoes <= {"DO1", "DO2", "DO3"}
    assert len(secoes) >= 2


def test_tipos_vem_da_fonte_nao_de_palavra_no_titulo(html_busca: str):
    tipos = {i["artType"] for i in extrair_jsonarray(html_busca)}
    assert "Portaria" in tipos
    assert any("Extrato" in t for t in tipos)


def test_total_de_resultados_e_lido_da_pagina(html_busca: str):
    assert total_de_resultados(html_busca) == 118


def test_todos_os_itens_sao_da_data_pedida(html_busca: str):
    """Regressao do parametro de data ignorado: pedir 03/09 tem que trazer 03/09."""
    assert {i["pubDate"] for i in extrair_jsonarray(html_busca)} == {"03/09/2026"}


def test_html_sem_bloco_json_levanta_erro():
    from radar.core.erros import ExtracaoParcial

    with pytest.raises(ExtracaoParcial):
        extrair_jsonarray("<html><body>nada aqui</body></html>")


# ── N4: chave "jsonArray" ausente é mudança de estrutura, não página vazia ──


def test_jsonarray_renomeada_levanta_extracao_parcial():
    """`.get("jsonArray", [])` devolvia [] em silêncio se a chave mudasse.

    Combinado com o total também ilegível (C4), o par virava coleta vazia sem
    nenhum aviso: `vazio`, exit 0, publicações do dia nunca chegam ao agente.
    """
    from radar.core.erros import ExtracaoParcial

    bloco = json.dumps({"itensResultado": [{"urlTitle": "ato-1"}]})
    html = (
        f'<script id="{ID_BLOCO_JSON}" type="application/json">{bloco}</script>'
    )
    with pytest.raises(ExtracaoParcial):
        extrair_jsonarray(html)


def test_jsonarray_presente_e_vazio_continua_legitimo():
    """Página real sem itens (`"jsonArray": []`) não pode virar erro."""
    bloco = json.dumps({"jsonArray": []})
    html = f'<script id="{ID_BLOCO_JSON}" type="application/json">{bloco}</script>'
    assert extrair_jsonarray(html) == []


def test_url_usa_data_personalizada_e_nunca_exactdate_dia():
    """`exactDate=dia` ignora a data pedida e devolve a edicao corrente."""
    url = montar_url_busca("Ministério da Saúde", date(2026, 9, 3), delta=75)
    assert "exactDate=personalizado" in url
    assert "publishFrom=03-09-2026" in url
    assert "publishTo=03-09-2026" in url
    assert "exactDate=dia" not in url
    assert "dateDay" not in url
    assert "delta=75" in url
    assert "Minist%C3%A9rio+da+Sa%C3%BAde" in url or "Minist%C3%A9rio%20da%20Sa%C3%BAde" in url


def test_primeira_pagina_nao_leva_cursor():
    url = montar_url_busca("MS", date(2026, 9, 3), delta=75)
    assert "newPage" not in url
    assert "score" not in url


def test_cursor_e_extraido_do_ultimo_item(html_busca: str):
    from radar.fontes.dou.busca import cursor_do_ultimo

    itens = extrair_jsonarray(html_busca)
    cursor = cursor_do_ultimo(itens)
    assert cursor.id == itens[-1]["classPK"]
    assert cursor.display_date == itens[-1]["displayDateSortable"]
    assert cursor.score == itens[-1]["score"]


def test_cursor_de_lista_vazia_e_none():
    from radar.fontes.dou.busca import cursor_do_ultimo

    assert cursor_do_ultimo([]) is None


def test_url_da_segunda_pagina_carrega_o_cursor(html_busca: str):
    from radar.fontes.dou.busca import cursor_do_ultimo

    cursor = cursor_do_ultimo(extrair_jsonarray(html_busca))
    url = montar_url_busca("MS", date(2026, 9, 3), delta=75, pagina=2, cursor=cursor)
    assert "currentPage=1" in url
    assert "newPage=2" in url
    assert f"id={cursor.id}" in url
    assert f"displayDate={cursor.display_date}" in url


def test_url_de_publicacao_usa_o_slug():
    assert url_publicacao("portaria-x-123") == "https://www.in.gov.br/web/dou/-/portaria-x-123"
