from datetime import date, datetime, timezone

import pytest

from boletim.config import ConfigBoletim
from boletim.edicao import Item
from boletim.prompts import (
    SISTEMA_CLASSIFICACAO,
    SISTEMA_EDITORIAL,
    montar_editorial,
    montar_lote,
)
from radar.core.modelos import Publicacao, gerar_id


def _pub(titulo="PORTARIA Nº 1", **kw) -> Publicacao:
    base = dict(
        fonte="inlabs",
        data_publicacao=date(2026, 9, 3),
        coletado_em=datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc),
        orgao="Ministério da Saúde",
        unidade="Gabinete do Ministro",
        secao="1",
        pagina=41,
        edicao="169",
        tipo="Portaria",
        numero="3.412",
        titulo=titulo,
        ementa="Habilita leitos e destina R$ 1.234.567,89 ao Município de Manhuaçu.",
        texto="Texto do ato.",
        url="https://exemplo/1",
    )
    base.update(kw)
    base["id"] = gerar_id(base["fonte"], base["data_publicacao"], base["url"], titulo)
    return Publicacao(origem={}, **base)


def _item(**kw) -> Item:
    base = dict(
        id="abc123",
        fonte="inlabs",
        orgao="Ministério da Saúde",
        unidade=None,
        tipo="Portaria",
        numero="3.412",
        data_publicacao=date(2026, 9, 3),
        secao="1",
        pagina=41,
        edicao="169",
        titulo="PORTARIA Nº 3.412",
        url="https://exemplo/1",
        categoria="A",
        relevancia=3,
        resumo="resumo do ato",
    )
    base.update(kw)
    return Item(**base)


@pytest.fixture
def cfg() -> ConfigBoletim:
    return ConfigBoletim()


# ── SISTEMA_CLASSIFICACAO ───────────────────────────────────────────────
def test_sistema_de_classificacao_define_as_cinco_categorias():
    for categoria in ("A)", "B)", "C)", "D)", "X)"):
        assert categoria in SISTEMA_CLASSIFICACAO


def test_sistema_de_classificacao_carrega_as_regras_de_voz():
    for regra in ("travessão", "emoji", "Dica", "Truque", "incrível", "revolucionário"):
        assert regra in SISTEMA_CLASSIFICACAO
    assert "somente com o JSON" in SISTEMA_CLASSIFICACAO


def test_sistema_de_classificacao_manda_desempatar_para_x():
    assert "na dúvida entre D e X, use X" in SISTEMA_CLASSIFICACAO


def test_sistemas_nao_usam_travessao_nem_emoji():
    for sistema in (SISTEMA_CLASSIFICACAO, SISTEMA_EDITORIAL):
        # O travessão só pode aparecer quando a regra o nomeia, entre parênteses.
        assert sistema.count("—") == sistema.count("(— ou –)")


def test_sistema_editorial_pede_titulo_com_numero_e_limite():
    assert "90 caracteres" in SISTEMA_EDITORIAL
    assert "pelo menos um número" in SISTEMA_EDITORIAL
    assert "em_30_segundos" in SISTEMA_EDITORIAL


# ── montar_lote ─────────────────────────────────────────────────────────
def test_montar_lote_traz_um_bloco_por_id(cfg):
    pubs = [_pub("PORTARIA Nº 1"), _pub("PORTARIA Nº 2", url="https://exemplo/2")]
    prompt = montar_lote(pubs, cfg)
    for pub in pubs:
        assert f"### {pub.id}" in prompt


def test_montar_lote_traz_a_linha_de_identificacao(cfg):
    prompt = montar_lote([_pub()], cfg)
    assert (
        "inlabs | Ministério da Saúde | Gabinete do Ministro | Portaria nº 3.412 "
        "| 03/09/2026 | https://exemplo/1" in prompt
    )


def test_montar_lote_usa_traco_para_campo_ausente(cfg):
    prompt = montar_lote([_pub(unidade=None, tipo=None, numero=None)], cfg)
    assert "inlabs | Ministério da Saúde | - | - nº - | 03/09/2026" in prompt


def test_montar_lote_lista_valores_e_entes_detectados(cfg):
    prompt = montar_lote([_pub()], cfg)
    assert "Valores detectados: R$ 1.234.567,89" in prompt
    assert "Entes detectados: Município de Manhuaçu" in prompt


def test_montar_lote_omite_deteccoes_vazias(cfg):
    prompt = montar_lote([_pub(ementa="Institui grupo de trabalho.")], cfg)
    assert "Valores detectados" not in prompt
    assert "Entes detectados" not in prompt


def test_montar_lote_trunca_texto_longo_pela_cabeca_e_pela_cauda(cfg):
    cfg.max_chars_texto = 100
    texto = "A" * 500 + "FIM DO ATO"
    prompt = montar_lote([_pub(texto=texto)], cfg)
    assert "[...]" in prompt
    assert "FIM DO ATO" in prompt
    assert "A" * 500 not in prompt


def test_montar_lote_nao_trunca_texto_curto(cfg):
    prompt = montar_lote([_pub(texto="Texto curto do ato.")], cfg)
    assert "[...]" not in prompt
    assert "Texto curto do ato." in prompt


def test_montar_lote_fecha_pedindo_a_contagem_exata(cfg):
    prompt = montar_lote([_pub("PORTARIA Nº 1"), _pub("PORTARIA Nº 2")], cfg)
    assert "Classifique cada um dos 2 itens acima." in prompt
    assert "Devolva exatamente 2 itens, um por id." in prompt


# ── montar_editorial ────────────────────────────────────────────────────
def test_montar_editorial_lista_so_a_b_c():
    itens = [
        _item(id="ida", categoria="A", resumo="resumo A"),
        _item(id="idb", categoria="B", resumo="resumo B"),
        _item(id="idc", categoria="C", resumo="resumo C"),
        _item(id="idd", categoria="D", resumo="resumo D"),
        _item(id="idx", categoria="X", resumo="resumo X"),
    ]
    prompt = montar_editorial(itens, {"A": 1, "B": 1, "C": 1, "D": 1}, date(2026, 9, 3))
    assert "resumo A" in prompt
    assert "resumo B" in prompt
    assert "resumo C" in prompt
    assert "resumo D" not in prompt
    assert "resumo X" not in prompt


def test_montar_editorial_traz_data_contagens_e_valor():
    prompt = montar_editorial(
        [_item(valor_brl=28100000.0)], {"A": 1, "B": 0, "C": 0, "D": 2}, date(2026, 9, 3)
    )
    assert "03/09/2026" in prompt
    assert "R$ 28.100.000,00" in prompt
    assert "A: 1" in prompt
    assert "D: 2" in prompt
