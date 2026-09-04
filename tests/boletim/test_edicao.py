import json
from datetime import date, datetime, timezone

from boletim.edicao import (
    ROTULOS,
    Edicao,
    FonteResumo,
    Item,
    item_de_dict,
    item_para_dict,
)


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
