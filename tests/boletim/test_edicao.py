import json
from datetime import date, datetime, timezone

from boletim.edicao import (
    ROTULOS,
    Edicao,
    FonteResumo,
    Item,
    item_de_dict,
    item_para_dict,
    montar_edicao,
    ordenar,
    titulo_fallback,
    validar_voz,
)
from boletim.llm import LLMFalso


def _item(**kw) -> Item:
    base = dict(
        id="abc123",
        fonte="inlabs",
        orgao="Ministério da Saúde",
        unidade=None,
        tipo="Portaria",
        numero="123",
        data_publicacao=date(2026, 9, 3),
        secao="DO1",
        pagina=5,
        edicao="168",
        titulo="Portaria X",
        url="https://x",
        categoria="A",
        relevancia=8,
        resumo="resumo curto",
    )
    base.update(kw)
    return Item(**base)


def test_item_e_imutavel():
    import pytest

    item = _item()
    with pytest.raises(Exception):
        item.titulo = "outro"


def test_item_para_dict_serializa_data_em_iso():
    d = item_para_dict(_item())
    assert d["data_publicacao"] == "2026-09-03"
    json.dumps(d)  # não pode conter tuplas/objetos que o json rejeite


def test_item_ida_e_volta_preserva_todos_os_campos():
    item = _item(
        por_que_importa="motivo",
        valor_brl=15000.5,
        entes=("Casa Civil", "Vice-Presidência"),
        tags=("saude", "captacao"),
        fallback=True,
    )
    d = item_para_dict(item)
    de_volta = item_de_dict(d)
    assert de_volta == item


def test_item_de_dict_usa_defaults_quando_campos_opcionais_ausentes():
    d = item_para_dict(_item())
    de_volta = item_de_dict(d)
    assert de_volta.por_que_importa is None
    assert de_volta.valor_brl is None
    assert de_volta.entes == ()
    assert de_volta.tags == ()
    assert de_volta.fallback is False


def test_rotulos_cobre_as_quatro_categorias_relevantes():
    assert ROTULOS == {
        "A": "Captação de recursos",
        "B": "Mudança de regra",
        "C": "Editais e chamamentos",
        "D": "Outros atos",
    }


def test_total_relevante_soma_a_b_c_mas_nao_d():
    edicao = Edicao(
        data=date(2026, 9, 3),
        titulo="Radar de captação",
        em_30_segundos=("resumo 1",),
        intro="intro",
        secoes={
            "A": (_item(categoria="A"),),
            "B": (_item(categoria="B"), _item(categoria="B")),
            "C": (),
            "D": (_item(categoria="D"), _item(categoria="D"), _item(categoria="D")),
        },
        fontes=(FonteResumo(nome="inlabs", status="ok", edicao="168", paginas="1-30"),),
        parcial=False,
        gerado_em=datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc),
    )
    assert edicao.total_relevante() == 3


# ── ordenar ─────────────────────────────────────────────────────────────
def test_ordenar_devolve_as_quatro_secoes_e_exclui_x():
    secoes = ordenar([_item(categoria="X")])
    assert set(secoes) == {"A", "B", "C", "D"}
    assert all(secoes[cat] == () for cat in secoes)


def test_ordenar_a_por_relevancia_e_depois_por_valor():
    baixa = _item(id="1", categoria="A", relevancia=2, valor_brl=99.0)
    grande = _item(id="2", categoria="A", relevancia=3, valor_brl=1000.0)
    media = _item(id="3", categoria="A", relevancia=3, valor_brl=500.0)
    sem_valor = _item(id="4", categoria="A", relevancia=3, valor_brl=None)
    secoes = ordenar([baixa, sem_valor, media, grande])
    assert [i.id for i in secoes["A"]] == ["2", "3", "4", "1"]


def test_ordenar_b_e_c_apenas_por_relevancia():
    secoes = ordenar(
        [
            _item(id="1", categoria="B", relevancia=1),
            _item(id="2", categoria="B", relevancia=3),
            _item(id="3", categoria="C", relevancia=1),
            _item(id="4", categoria="C", relevancia=2),
        ]
    )
    assert [i.id for i in secoes["B"]] == ["2", "1"]
    assert [i.id for i in secoes["C"]] == ["4", "3"]


def test_ordenar_d_por_titulo():
    secoes = ordenar(
        [
            _item(id="1", categoria="D", titulo="Portaria Z"),
            _item(id="2", categoria="D", titulo="Ato A"),
        ]
    )
    assert [i.id for i in secoes["D"]] == ["2", "1"]


# ── validar_voz ─────────────────────────────────────────────────────────
def test_validar_voz_aprova_frase_no_formato_de_sentenca():
    assert validar_voz("3 habilitações e 1 teto MAC ampliado em MG") == []


def test_validar_voz_reprova_travessao():
    assert validar_voz("Radar do dia — 3 habilitações") != []
    assert validar_voz("Radar do dia – 3 habilitações") != []


def test_validar_voz_reprova_emoji():
    assert validar_voz("3 habilitações 🚀 hoje") != []
    assert validar_voz("3 habilitações ✅ hoje") != []


def test_validar_voz_reprova_pergunta_retorica():
    assert validar_voz("Sabe o que mudou hoje?") != []


def test_validar_voz_reprova_dica_e_truque_em_qualquer_caixa():
    assert validar_voz("dica para o gestor") != []
    assert validar_voz("Truque de captação") != []


def test_validar_voz_reprova_title_case():
    assert validar_voz("Novo Teto MAC Ampliado Para Minas") != []


def test_validar_voz_aceita_ate_tres_palavras_capitalizadas_seguidas():
    assert validar_voz("Portaria Ministério Saúde altera o piso") == []


def test_validar_voz_acumula_erros():
    assert len(validar_voz("Dica: o que mudou — hoje?")) == 3


# ── titulo_fallback ─────────────────────────────────────────────────────
def test_titulo_fallback_traz_data_e_contagem():
    assert titulo_fallback(date(2026, 9, 3), 7) == (
        "Boletim de 03/09/2026: 7 publicações relevantes"
    )


# ── montar_edicao ───────────────────────────────────────────────────────
_AGORA = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
_FONTES = (FonteResumo(nome="inlabs", status="ok", edicao="169", paginas="pp. 41-89"),)


def _editorial_bom() -> dict:
    return {
        "titulo": "3 habilitações e 1 teto MAC ampliado em MG",
        "em_30_segundos": ["fato 1", "fato 2", "fato 3"],
        "intro": "O dia trouxe 2 atos com dinheiro novo. Vale olhar os prazos.",
    }


def _montar(itens, llm, parcial=False):
    return montar_edicao(itens, _FONTES, parcial, llm, date(2026, 9, 3), _AGORA)


def test_montar_edicao_usa_o_editorial_do_llm(dir_fixtures):
    editorial = json.loads(
        (dir_fixtures / "boletim" / "llm" / "editorial.json").read_text(encoding="utf-8")
    )
    llm = LLMFalso({"editorial": editorial})
    edicao = _montar([_item(categoria="A")], llm)

    assert edicao.titulo == "3 habilitações e 1 teto MAC ampliado em MG"
    assert len(edicao.em_30_segundos) == 4
    assert edicao.intro == editorial["intro"]
    assert edicao.data == date(2026, 9, 3)
    assert edicao.gerado_em == _AGORA
    assert edicao.fontes == _FONTES
    assert edicao.parcial is False
    assert len(llm.chamadas) == 1


def test_montar_edicao_repete_uma_vez_quando_a_voz_reprova():
    ruim = dict(_editorial_bom(), titulo="Radar do dia — 3 habilitações")
    llm = LLMFalso({"editorial": [ruim, _editorial_bom()]})
    edicao = _montar([_item(categoria="A")], llm)

    assert edicao.titulo == "3 habilitações e 1 teto MAC ampliado em MG"
    assert len(llm.chamadas) == 2
    assert "Correções obrigatórias:" in llm.chamadas[1][2]
    assert "travessão" in llm.chamadas[1][2]


def test_montar_edicao_cai_no_fallback_apos_duas_reprovacoes():
    ruim = dict(_editorial_bom(), titulo="Radar do dia — 3 habilitações")
    llm = LLMFalso({"editorial": [ruim, ruim]})
    itens = [
        _item(id="1", categoria="A", resumo="resumo A"),
        _item(id="2", categoria="B", resumo="resumo B"),
    ]
    edicao = _montar(itens, llm)

    assert edicao.titulo == "Boletim de 03/09/2026: 2 publicações relevantes"
    assert edicao.em_30_segundos == ("resumo A", "resumo B")
    assert len(llm.chamadas) == 2


def test_montar_edicao_cai_no_fallback_quando_o_llm_esta_fora_do_ar():
    edicao = _montar([_item(categoria="A", resumo="resumo A")], LLMFalso({}))
    assert edicao.titulo == "Boletim de 03/09/2026: 1 publicações relevantes"
    assert edicao.em_30_segundos == ("resumo A",)


def test_montar_edicao_sem_a_b_c_nao_chama_o_llm():
    llm = LLMFalso({})
    edicao = _montar([_item(categoria="D", titulo="Ato administrativo")], llm)

    assert llm.chamadas == []
    assert edicao.titulo == "Boletim de 03/09/2026: 0 publicações relevantes"
    assert edicao.em_30_segundos == ("Ato administrativo",)
    assert edicao.intro


def test_montar_edicao_de_dia_sem_publicacao_alguma():
    edicao = _montar([], LLMFalso({}))
    assert edicao.em_30_segundos == ("Sem publicações relevantes nesta data",)
    assert edicao.secoes == {"A": (), "B": (), "C": (), "D": ()}


def test_montar_edicao_marca_parcial_quando_ha_item_de_fallback():
    llm = LLMFalso({"editorial": _editorial_bom()})
    edicao = _montar([_item(categoria="A"), _item(id="2", categoria="D", fallback=True)], llm)
    assert edicao.parcial is True


def test_montar_edicao_propaga_o_parcial_da_coleta():
    llm = LLMFalso({"editorial": _editorial_bom()})
    assert _montar([_item(categoria="A")], llm, parcial=True).parcial is True


def test_editorial_deterministico_lista_no_maximo_tres_titulos_de_d():
    itens = [_item(id=str(n), categoria="D", titulo=f"Ato {n}") for n in range(1, 6)]
    edicao = _montar(itens, LLMFalso({}))
    assert len(edicao.em_30_segundos) == 3
