import json
import logging
from datetime import date, datetime, timezone

import pytest

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
from radar.core.log import configurar_log


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


# ── Title Case: nome próprio dentro da frase não é Title Case da frase ──
def test_validar_voz_aceita_nome_proprio_longo_dentro_da_sentenca():
    """O nome do programa tem 4 iniciais maiúsculas seguidas e não é Title Case.

    Era este o falso positivo que jogou 3 dos 5 dias da primeira semana real no
    título determinístico: a regra antiga contava palavras capitalizadas
    seguidas, e todo nome próprio de programa ou de hospital estourava o limite.
    """
    assert validar_voz("3 habilitações do Programa Agora Tem Especialistas somam R$ 180 milhões") == []


def test_validar_voz_reprova_sentenca_inteira_em_title_case():
    assert validar_voz("Habilitações Do Programa Somam Cento E Oitenta Milhões") != []


def test_validar_voz_aceita_titulo_real_reprovado_do_programa():
    """Um dos dois títulos reais que caíram no fallback na semana de 31/08."""
    assert validar_voz("3 hospitais entram no Programa Agora Tem Especialistas com R$ 180 milhões") == []


def test_validar_voz_aceita_titulo_real_reprovado_da_fundacao():
    """O outro: um nome de instituição com 7 iniciais maiúsculas."""
    assert (
        validar_voz(
            "1 hospital de São José do Rio Preto recebe R$ 104,8 milhões em terapia renal"
        )
        == []
    )


def test_validar_voz_ignora_siglas_e_numeros_na_conta_de_title_case():
    assert validar_voz("SES-MG e CIB-SUS/MG aprovam 12 deliberações") == []


def test_validar_voz_reprova_title_case_com_conectivo_em_minuscula():
    """Title Case de verdade escapou na rodada 2 e voltou a ser pego.

    O título de 02/09 saiu "Santa Casa de Passos Recebe R$ 168,8 Milhões:
    Edição com Destaque para Incorporações MAC..." - conectivos em minúscula,
    todo o resto capitalizado. É a frase inteira em Title Case, e a proporção
    (11 de 11 palavras) é o que a denuncia.
    """
    assert (
        validar_voz(
            "Santa Casa de Passos Recebe R$ 168,8 Milhões: Edição com Destaque para "
            "Incorporações MAC e Investimentos em Infraestrutura Rural"
        )
        != []
    )


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
    ruim = dict(_editorial_bom(), titulo="O que mudou hoje no SUS?")
    llm = LLMFalso({"editorial": [ruim, _editorial_bom()]})
    edicao = _montar([_item(categoria="A")], llm)

    assert edicao.titulo == "3 habilitações e 1 teto MAC ampliado em MG"
    assert len(llm.chamadas) == 2
    assert "Correções obrigatórias:" in llm.chamadas[1][2]
    assert "pergunta retórica" in llm.chamadas[1][2]


def test_titulo_acima_de_90_caracteres_volta_para_o_modelo():
    """Os limites do prompt não eram checados, e em v2 saíram títulos de 128 e
    98 caracteres. O comprimento é a única regra de voz que dá para conferir
    sozinho, e o caminho da correção já existe: entra em `_erros_de_voz` e o
    modelo recebe o número junto com o pedido.
    """
    longo = (
        "3 hospitais de Minas entram no programa federal de especialidades e "
        "somam R$ 180 milhões em créditos anuais"
    )
    assert len(longo) > 90
    llm = LLMFalso({"editorial": [dict(_editorial_bom(), titulo=longo), _editorial_bom()]})
    edicao = _montar([_item(categoria="A")], llm)

    assert edicao.titulo == "3 habilitações e 1 teto MAC ampliado em MG"
    assert len(llm.chamadas) == 2
    assert f"título com {len(longo)} caracteres (máx. 90)" in llm.chamadas[1][2]


def test_titulo_de_90_caracteres_passa():
    no_limite = (
        "3 hospitais de Minas entram no programa federal e somam "
        "R$ 180 milhões em créditos anuais."
    )
    assert len(no_limite) == 90
    llm = LLMFalso({"editorial": dict(_editorial_bom(), titulo=no_limite)})
    edicao = _montar([_item(categoria="A")], llm)

    assert edicao.titulo == no_limite
    assert len(llm.chamadas) == 1


def test_bullet_acima_de_140_caracteres_volta_para_o_modelo():
    longo = "a" * 141
    ruim = dict(_editorial_bom(), em_30_segundos=["fato 1", longo, "fato 3"])
    llm = LLMFalso({"editorial": [ruim, _editorial_bom()]})
    edicao = _montar([_item(categoria="A")], llm)

    assert len(llm.chamadas) == 2
    assert "bullet com 141 caracteres (máx. 140)" in llm.chamadas[1][2]
    assert edicao.em_30_segundos == ("fato 1", "fato 2", "fato 3")


def test_intro_acima_de_1100_caracteres_volta_para_o_modelo():
    longa = "b" * 1101
    llm = LLMFalso({"editorial": [dict(_editorial_bom(), intro=longa), _editorial_bom()]})
    _montar([_item(categoria="A")], llm)

    assert len(llm.chamadas) == 2
    assert "intro com 1101 caracteres (máx. 1100)" in llm.chamadas[1][2]


def test_intro_real_de_mil_caracteres_passa():
    """O limite antigo era 400 e nenhuma das sete edições reais cabia nele.

    O modelo entregou de 716 a 1102 caracteres, e reprovar 7 de 7 gastava uma
    segunda chamada por dia para nada - e, com a validação em bloco, levava o
    título junto.
    """
    llm = LLMFalso({"editorial": dict(_editorial_bom(), intro="b" * 1000)})
    edicao = _montar([_item(categoria="A")], llm)

    assert len(edicao.intro) == 1000
    assert len(llm.chamadas) == 1


# ── replay das cinco edições reais da semana (v2) ───────────────────────
# As cinco aberturas que o Haiku escreveu em 31/08-04/09, como saíram no
# `itens.json` de cada dia. Elas são a prova da correção: com o limite de 400 e
# a validação em bloco, as cinco caíam inteiras no fallback, inclusive os dois
# títulos que não tinham defeito nenhum.
_FALLBACK_ESPERADO = {
    "2026-08-31": (),                                  # intro de 993: passava a caber
    "2026-09-01": (),                                  # intro de 716
    "2026-09-02": ("titulo", "em_30_segundos", "intro"),  # 128 chars, 155, 1102
    "2026-09-03": ("titulo",),                         # Title Case e 98 chars
    "2026-09-04": ("titulo", "em_30_segundos"),        # Title Case e bullet de 152
}


def _editoriais_reais(dir_fixtures) -> dict:
    caminho = dir_fixtures / "boletim" / "reais" / "editoriais-semana.json"
    return json.loads(caminho.read_text(encoding="utf-8"))


@pytest.mark.parametrize("dia", sorted(_FALLBACK_ESPERADO))
def test_replay_das_edicoes_reais_da_semana(dia, dir_fixtures):
    editorial = _editoriais_reais(dir_fixtures)[dia]
    llm = LLMFalso({"editorial": [editorial, editorial]})
    itens = [_item(id="1", categoria="A", resumo="resumo A")]
    edicao = _montar(itens, llm)
    caidos = _FALLBACK_ESPERADO[dia]

    if "titulo" in caidos:
        assert edicao.titulo == "Boletim de 03/09/2026: 1 publicações relevantes"
    else:
        assert edicao.titulo == editorial["titulo"]
    if "em_30_segundos" in caidos:
        assert edicao.em_30_segundos == ("resumo A",)
    else:
        assert edicao.em_30_segundos == tuple(editorial["em_30_segundos"])
    if "intro" in caidos:
        assert "não pôde ser gerado" in edicao.intro
    else:
        assert edicao.intro == editorial["intro"]


def test_replay_de_31_08_e_01_09_mantem_o_titulo_gerado(dir_fixtures):
    """Os dois títulos que a validação em bloco descartava por causa da intro."""
    editoriais = _editoriais_reais(dir_fixtures)
    for dia in ("2026-08-31", "2026-09-01"):
        editorial = editoriais[dia]
        llm = LLMFalso({"editorial": editorial})
        edicao = _montar([_item(categoria="A")], llm)
        assert edicao.titulo == editorial["titulo"]
        assert len(llm.chamadas) == 1, "a abertura aprovada não pede segunda chamada"


def test_replay_de_03_09_nomeia_o_campo_reprovado_no_log(caplog, dir_fixtures):
    editorial = _editoriais_reais(dir_fixtures)["2026-09-03"]
    llm = LLMFalso({"editorial": [editorial, editorial]})
    logger = configurar_log()
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="radar"):
            edicao = _montar([_item(categoria="A")], llm)
    finally:
        logger.removeHandler(caplog.handler)

    assert "titulo reprovado 2x" in caplog.text
    assert "título com 98 caracteres" in caplog.text
    assert edicao.intro == editorial["intro"]


def test_montar_edicao_normaliza_o_travessao_em_vez_de_reprovar():
    """Travessão é erro de digitação do modelo, não de julgamento editorial.

    Reprovar por causa dele custava uma segunda chamada e, quando o modelo
    repetia, o dia inteiro perdia o título. Trocar por hífen antes de validar
    resolve na origem e mantém a regra de travessão para os outros usos.
    """
    ruim = {
        "titulo": "Radar do dia — 3 habilitações",
        "em_30_segundos": ["fato 1 — com traço", "fato 2", "fato 3"],
        "intro": "O dia trouxe 2 atos – com dinheiro novo. Vale olhar os prazos.",
    }
    llm = LLMFalso({"editorial": ruim})
    edicao = _montar([_item(categoria="A")], llm)

    assert edicao.titulo == "Radar do dia - 3 habilitações"
    assert edicao.em_30_segundos[0] == "fato 1 - com traço"
    assert "–" not in edicao.intro and "-" in edicao.intro
    assert len(llm.chamadas) == 1


def test_apos_duas_reprovacoes_so_o_campo_ruim_cai_no_fallback():
    """A reprovação é por campo: o título ruim não leva junto a intro boa.

    Antes a abertura era aprovada ou reprovada em bloco, e na semana real isso
    custou o título gerado de 31/08 e 01/09 por causa do tamanho da intro.
    """
    ruim = dict(_editorial_bom(), titulo="O que mudou hoje no SUS?")
    llm = LLMFalso({"editorial": [ruim, ruim]})
    itens = [
        _item(id="1", categoria="A", resumo="resumo A"),
        _item(id="2", categoria="B", resumo="resumo B"),
    ]
    edicao = _montar(itens, llm)

    assert edicao.titulo == "Boletim de 03/09/2026: 2 publicações relevantes"
    assert edicao.em_30_segundos == ("fato 1", "fato 2", "fato 3")
    assert edicao.intro == _editorial_bom()["intro"]
    assert len(llm.chamadas) == 2


def test_intro_reprovada_duas_vezes_nao_custa_o_titulo():
    ruim = dict(_editorial_bom(), intro="b" * 1101)
    llm = LLMFalso({"editorial": [ruim, ruim]})
    edicao = _montar([_item(categoria="A", resumo="resumo A")], llm)

    assert edicao.titulo == "3 habilitações e 1 teto MAC ampliado em MG"
    assert edicao.em_30_segundos == ("fato 1", "fato 2", "fato 3")
    assert "não pôde ser gerado" in edicao.intro


def test_todos_os_campos_reprovados_caem_no_fallback_inteiro():
    ruim = {
        "titulo": "O que mudou hoje no SUS?",
        "em_30_segundos": ["a" * 141, "fato 2"],
        "intro": "b" * 1101,
    }
    llm = LLMFalso({"editorial": [ruim, ruim]})
    itens = [
        _item(id="1", categoria="A", resumo="resumo A"),
        _item(id="2", categoria="B", resumo="resumo B"),
    ]
    edicao = _montar(itens, llm)

    assert edicao.titulo == "Boletim de 03/09/2026: 2 publicações relevantes"
    assert edicao.em_30_segundos == ("resumo A", "resumo B")
    assert "não pôde ser gerado" in edicao.intro


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


def test_montar_edicao_loga_aviso_quando_llm_esta_fora_do_ar(caplog):
    logger = configurar_log()
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="radar"):
            _montar([_item(categoria="A", resumo="resumo A")], LLMFalso({}))
    finally:
        logger.removeHandler(caplog.handler)

    assert "editorial" in caplog.text
    assert "LLM indisponível" in caplog.text


def test_montar_edicao_loga_aviso_quando_voz_reprova_duas_vezes(caplog):
    """O aviso diz qual campo caiu: é a única pista de que a edição saiu mista."""
    ruim = dict(_editorial_bom(), titulo="O que mudou hoje no SUS?")
    llm = LLMFalso({"editorial": [ruim, ruim]})
    logger = configurar_log()
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="radar"):
            _montar(
                [_item(id="1", categoria="A"), _item(id="2", categoria="B")], llm
            )
    finally:
        logger.removeHandler(caplog.handler)

    assert "titulo reprovado 2x" in caplog.text
    assert "pergunta retórica" in caplog.text
    assert "intro" not in caplog.text.split("(")[0]


def test_editorial_deterministico_lista_no_maximo_tres_titulos_de_d():
    itens = [_item(id=str(n), categoria="D", titulo=f"Ato {n}") for n in range(1, 6)]
    edicao = _montar(itens, LLMFalso({}))
    assert len(edicao.em_30_segundos) == 3
