"""Doações do Ministério da Saúde a entes públicos, extraídas sem modelo.

Os textos da fixture são extratos reais do DOU de 16/09/2026 (texto truncado e
sem signatários). Em 16/09 as 54 doações do dia somaram R$ 27.768.076,00 e
foram todas descartadas pelo prefiltro: a edição saiu com zero relevantes.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from boletim.config import ConfigBoletim
from boletim.doacoes import Doacao, agrupar, extrair
from boletim.render import titulo_ato
from radar.core.modelos import Publicacao, publicacao_de_dict

_RAIZ = Path(__file__).resolve().parents[2]
_FIXTURE = _RAIZ / "tests" / "fixtures" / "boletim" / "doacoes-2026-09-16.json"
_DIA_REAL = _RAIZ / "data" / "normalized" / "2026-09-16"
DATA = date(2026, 9, 16)
MARCAS = tuple(ConfigBoletim().marcas_mg)


@pytest.fixture(scope="module")
def pubs() -> list[Publicacao]:
    bruto = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return [publicacao_de_dict(p, DATA) for p in bruto]


def _por_donatario(pubs: list[Publicacao], trecho: str) -> Publicacao:
    return next(p for p in pubs if f"Donatário: {trecho}" in p.texto)


def _doacoes_ms(pubs: list[Publicacao]) -> list[Publicacao]:
    return [p for p in pubs if "Doador: Ministério da Saúde" in p.texto]


# ── extrair ─────────────────────────────────────────────────────────────
def test_extrai_micro_onibus(pubs):
    pub = _por_donatario(pubs, "Prefeitura Municipal de Irani/SC")
    assert extrair(pub) == Doacao(
        id=pub.id,
        municipio="Irani",
        uf="SC",
        donatario="Prefeitura Municipal de Irani/SC",
        quantidade=1,
        objeto="transporte sanitário eletivo do tipo micro-ônibus com acessibilidade",
        valor_brl=584600.00,
        url=pub.url,
    )


def test_extrai_samu_renovacao_com_dois_veiculos(pubs):
    doacao = extrair(_por_donatario(pubs, "Prefeitura Municipal de Blumenau/SC"))
    assert doacao is not None
    assert (doacao.municipio, doacao.uf) == ("Blumenau", "SC")
    assert doacao.quantidade == 2
    assert doacao.objeto == "renovação de frota"
    assert doacao.valor_brl == 585200.00


def test_extrai_samu_expansao_com_apostrofo_no_nome(pubs):
    doacao = extrair(_por_donatario(pubs, "Prefeitura Municipal de Novo Horizonte"))
    assert doacao is not None
    assert doacao.municipio == "Novo Horizonte D'Oeste"
    assert doacao.uf == "RO"
    assert doacao.objeto == "Expansão de frota"
    assert doacao.valor_brl == 323037.00


def test_extrai_ambulancia_em_minas(pubs):
    doacao = extrair(_por_donatario(pubs, "Prefeitura Municipal de Almenara/MG"))
    assert doacao is not None
    assert (doacao.municipio, doacao.uf) == ("Almenara", "MG")
    assert doacao.quantidade == 1
    assert doacao.objeto == "ambulância padrão suporte básico tipo a - especial"
    assert doacao.valor_brl == 274977.00


def test_extrai_secretaria_estadual_sem_municipio(pubs):
    doacao = extrair(_por_donatario(pubs, "Secretaria de Estado da Saúde do Piauí"))
    assert doacao is not None
    assert doacao.municipio is None
    assert doacao.uf is None
    assert doacao.donatario == "Secretaria de Estado da Saúde do Piauí"
    assert doacao.quantidade == 11
    assert doacao.valor_brl == 3350600.00


def test_prefixos_municipais_saem_do_nome(pubs):
    base = _por_donatario(pubs, "Prefeitura Municipal de Irani/SC")
    for prefixo in ("Município de", "Fundo Municipal de Saúde de",
                    "Secretaria Municipal de Saúde de"):
        texto = base.texto.replace("Prefeitura Municipal de", prefixo)
        doacao = extrair(replace(base, texto=texto))
        assert doacao is not None and doacao.municipio == "Irani", prefixo


def test_sem_donatario_devolve_none(pubs):
    base = _por_donatario(pubs, "Prefeitura Municipal de Irani/SC")
    texto = base.texto.replace("Donatário: Prefeitura Municipal de Irani/SC, ", "")
    assert extrair(replace(base, texto=texto)) is None


def test_sem_valor_devolve_none(pubs):
    # O extrato da Saps (equipamentos para UBS) não traz cifra.
    assert extrair(_por_donatario(pubs, "Indiaporã/SP")) is None


# ── agrupar ─────────────────────────────────────────────────────────────
def test_agrupa_em_um_item_com_minas_primeiro(pubs):
    item, avisos = agrupar(_doacoes_ms(pubs), DATA, MARCAS)
    assert avisos == []
    assert item is not None
    assert item.categoria == "A"
    assert item.relevancia == 3
    assert item.entes[:2] == ("Almenara", "Córrego Novo")
    assert item.entes[2:] == (
        "Blumenau", "Irani", "Novo Horizonte D'Oeste",
        "Secretaria de Estado da Saúde do Piauí", "Taquaral de Goiás",
    )
    assert item.valor_brl == round(
        585200 + 584600 + 323037 + 304600 + 3350600 + 274977 + 304600, 2
    )
    assert item.orgao == "Ministério da Saúde"
    assert item.unidade == "Secretaria de Atenção Especializada à Saúde"
    assert item.tipo == "Extrato de Termo de Doação"
    assert item.numero is None
    assert item.fallback is False
    assert item.url == _por_donatario(pubs, "Prefeitura Municipal de Almenara/MG").url
    assert item.por_que_importa and "mineiros" in item.por_que_importa


def test_resumo_traz_contagens_valor_e_minas_sem_travessao(pubs):
    item, _ = agrupar(_doacoes_ms(pubs), DATA, MARCAS)
    assert item is not None
    assert "—" not in item.resumo and "–" not in item.resumo
    assert len(item.resumo) <= 260
    assert "18 veículos" in item.resumo
    assert "13 vans de transporte sanitário" in item.resumo
    assert "R$ 5,7 milhões" in item.resumo
    assert item.resumo.endswith("Em Minas: Almenara e Córrego Novo.")


def test_sem_minas_relevancia_2_e_sem_por_que_importa(pubs):
    fora = [p for p in _doacoes_ms(pubs) if "/MG" not in p.texto]
    item, _ = agrupar(fora, DATA, MARCAS)
    assert item is not None
    assert item.relevancia == 2
    assert item.por_que_importa is None
    assert "Em Minas" not in item.resumo
    assert item.url == fora[0].url


def test_id_estavel_por_data(pubs):
    a, _ = agrupar(_doacoes_ms(pubs), DATA, MARCAS)
    b, _ = agrupar(list(reversed(_doacoes_ms(pubs))), DATA, MARCAS)
    assert a is not None and b is not None
    assert a.id == b.id and len(a.id) == 16


def test_titulo_sobrevive_ao_filtro_titulo_ato(pubs):
    item, _ = agrupar(_doacoes_ms(pubs), DATA, MARCAS)
    assert item is not None
    assert titulo_ato(item.titulo) == item.titulo
    assert item.titulo == "Doação de 18 veículos do SUS a 6 municípios e 1 estado"


def test_falha_do_parser_vira_aviso_e_sem_extraidas_nao_ha_item(pubs):
    sem_valor = _por_donatario(pubs, "Indiaporã/SP")
    item, avisos = agrupar([sem_valor], DATA, MARCAS)
    assert item is None
    assert len(avisos) == 1 and sem_valor.id in avisos[0]


def test_nenhuma_publicacao_nao_gera_item():
    assert agrupar([], DATA, MARCAS) == (None, [])


def test_mais_de_cinco_mineiros_resume_com_e_mais(pubs):
    base = _por_donatario(pubs, "Prefeitura Municipal de Almenara/MG")
    nomes = ["Abaeté", "Bocaiúva", "Caeté", "Diamantina", "Espinosa", "Formiga", "Guaxupé"]
    mineiros = [
        replace(base, id=f"id{i}", texto=base.texto.replace("Almenara", nome))
        for i, nome in enumerate(nomes)
    ]
    item, _ = agrupar(mineiros, DATA, MARCAS)
    assert item is not None
    assert item.resumo.endswith(
        "Em Minas: Abaeté, Bocaiúva, Caeté, Diamantina, Espinosa e mais 2."
    )


# ── dia real ────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _DIA_REAL.is_dir(), reason="dados de 16/09/2026 ausentes")
def test_dia_real_16_09_agrupa_as_54_doacoes():
    from boletim.carga import carregar
    from boletim.prefiltro import triar

    cfg = ConfigBoletim()
    carga = carregar(_RAIZ / "data", DATA, ["dou", "iofmg"])
    triagem = triar(carga.publicacoes, cfg)
    # O controlador contou 56 títulos de doação no dia; 54 têm o Ministério da
    # Saúde como doador literal. A 55ª ("a UNIÃO, por intermédio do MS") e a
    # doação simplificada ao INCA seguem para o modelo.
    assert len(triagem.doacoes) == 54
    item, avisos = agrupar(triagem.doacoes, DATA, tuple(cfg.marcas_mg))
    assert avisos == []
    assert item is not None
    assert item.valor_brl == 27768076.00
    assert set(item.entes[:2]) == {"Almenara", "Córrego Novo"}
    assert item.relevancia == 3
    assert len(item.resumo) <= 260
    assert titulo_ato(item.titulo) == item.titulo
