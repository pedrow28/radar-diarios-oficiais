from datetime import date, timezone

import pytest

from boletim.carga import Carga, carregar
from boletim.edicao import FonteResumo


@pytest.fixture
def dir_dados(dir_fixtures):
    return dir_fixtures / "boletim"


def test_carrega_as_duas_fontes_do_dia(dir_dados):
    carga = carregar(dir_dados, date(2026, 9, 3), ["inlabs", "iofmg"])
    assert len(carga.publicacoes) == 12
    assert [f.nome for f in carga.fontes] == ["inlabs", "iofmg"]
    assert carga.data == date(2026, 9, 3)


def test_publicacoes_saem_reidratadas_com_data_e_fuso(dir_dados):
    carga = carregar(dir_dados, date(2026, 9, 3), ["inlabs"])
    primeira = carga.publicacoes[0]
    assert primeira.data_publicacao == date(2026, 9, 3)
    assert primeira.coletado_em.tzinfo == timezone.utc
    assert primeira.titulo.startswith("PORTARIA GM/MS Nº 3.412")


def test_resumo_da_fonte_traz_status_edicao_paginas_e_avisos(dir_dados):
    carga = carregar(dir_dados, date(2026, 9, 3), ["inlabs", "iofmg"])
    iofmg = next(f for f in carga.fontes if f.nome == "iofmg")
    assert iofmg.status == "parcial"
    assert iofmg.edicao == "2026-09-03"
    assert iofmg.paginas == "pp. 12-27"
    assert iofmg.avisos == ("página 31 do caderno não pôde ser extraída",)


def test_dia_com_as_duas_fontes_lidas_e_uma_parcial_e_parcial(dir_dados):
    carga = carregar(dir_dados, date(2026, 9, 3), ["inlabs", "iofmg"])
    assert carga.parcial is True
    assert carga.todas_vazias is False


def test_fonte_ausente_vira_resumo_ausente_sem_quebrar(dir_dados):
    carga = carregar(dir_dados, date(2026, 9, 3), ["inlabs", "dou"])
    dou = next(f for f in carga.fontes if f.nome == "dou")
    assert dou == FonteResumo(
        nome="dou",
        status="ausente",
        edicao=None,
        paginas=None,
        avisos=("arquivo não encontrado",),
    )
    assert carga.parcial is True
    assert len(carga.publicacoes) == 8


def test_dia_sem_edicao_e_todas_vazias(dir_dados):
    carga = carregar(dir_dados, date(2026, 9, 6), ["iofmg"])
    assert carga.todas_vazias is True
    assert carga.todas_ausentes is False
    assert carga.parcial is False
    assert carga.publicacoes == ()


def test_dia_com_todas_as_fontes_ausentes_nao_e_vazio(dir_dados):
    """Nenhuma fonte coletada é filtro quebrado, não domingo.

    `ausente` contando como `vazio` fazia o dia sair verde e silencioso: o
    mesmo defeito que a `FonteINLABS` evita de proposito quando distingue
    "sem arquivo" de "nada no escopo".
    """
    carga = carregar(dir_dados, date(2026, 9, 6), ["inlabs"])
    assert carga.todas_ausentes is True
    assert carga.todas_vazias is False
    assert carga.parcial is True


def test_uma_fonte_ausente_e_o_resto_vazio_e_vazio_parcial(dir_dados):
    """Sai `vazio` - não há o que publicar -, mas marcado como parcial."""
    carga = carregar(dir_dados, date(2026, 9, 6), ["inlabs", "iofmg"])
    assert carga.todas_ausentes is False
    assert carga.todas_vazias is True
    assert carga.parcial is True


def test_fonte_ok_com_publicacoes_nao_e_vazia(dir_dados):
    carga = carregar(dir_dados, date(2026, 9, 3), ["inlabs"])
    assert carga.todas_vazias is False
    assert carga.parcial is False


def test_carga_e_imutavel():
    carga = Carga(data=date(2026, 9, 3), fontes=(), publicacoes=())
    with pytest.raises(Exception):
        carga.data = date(2026, 9, 4)
