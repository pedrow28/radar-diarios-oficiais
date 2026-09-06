"""O site é o arquivo público do boletim e o destino do link "ler completa".

O que importa aqui é a idempotência: publicar duas vezes a mesma data não pode
duplicar a entrada no índice, e reconstruir o índice não pode perder edição
antiga. Um arquivo que some é pior que um arquivo que nunca existiu.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date

import pytest

from boletim.config import ConfigBoletim
from boletim.render import render_web
from boletim.site import publicar, reconstruir_indice
from tests.fixtures.boletim.edicao_exemplo import edicao_exemplo


@pytest.fixture
def cfg(tmp_path) -> ConfigBoletim:
    return ConfigBoletim(dir_site=tmp_path / "site")


@pytest.fixture
def edicao():
    return edicao_exemplo()


def _publicar(edicao, cfg):
    return publicar(edicao, render_web(edicao, cfg), cfg)


def test_publicar_grava_pagina_indice_assets_e_nojekyll(edicao, cfg):
    pagina = _publicar(edicao, cfg)

    assert pagina == cfg.dir_site / "edicoes" / "2026-09-03.html"
    assert "3 habilitações" in pagina.read_text(encoding="utf-8")
    assert (cfg.dir_site / "index.html").exists()
    assert (cfg.dir_site / "assets" / "logo-navy.png").exists()
    assert (cfg.dir_site / "assets" / "logo-branco.png").exists()
    # Sem `.nojekyll` o GitHub Pages ignora tudo que começa com underscore.
    assert (cfg.dir_site / ".nojekyll").read_bytes() == b""


def test_edicoes_json_guarda_a_ficha_da_edicao(edicao, cfg):
    _publicar(edicao, cfg)

    entradas = json.loads((cfg.dir_site / "edicoes.json").read_text(encoding="utf-8"))
    assert entradas == [
        {
            "data": "2026-09-03",
            "titulo": edicao.titulo,
            "url": "edicoes/2026-09-03.html",
            "contagens": {"A": 2, "B": 1, "C": 1, "D": 2},
            "parcial": True,
        }
    ]


def test_publicar_a_mesma_data_substitui_em_vez_de_duplicar(edicao, cfg):
    _publicar(edicao, cfg)
    corrigida = replace(edicao, titulo="Título corrigido")
    _publicar(corrigida, cfg)

    entradas = json.loads((cfg.dir_site / "edicoes.json").read_text(encoding="utf-8"))
    assert len(entradas) == 1
    assert entradas[0]["titulo"] == "Título corrigido"


def test_indice_fica_ordenado_da_data_mais_recente_para_a_mais_antiga(edicao, cfg):
    _publicar(replace(edicao, data=date(2026, 9, 2)), cfg)
    _publicar(replace(edicao, data=date(2026, 9, 4)), cfg)
    _publicar(edicao, cfg)

    entradas = json.loads((cfg.dir_site / "edicoes.json").read_text(encoding="utf-8"))
    assert [e["data"] for e in entradas] == ["2026-09-04", "2026-09-03", "2026-09-02"]

    indice = (cfg.dir_site / "index.html").read_text(encoding="utf-8")
    assert indice.index("4 de setembro") < indice.index("2 de setembro")


def test_reconstruir_indice_regenera_a_partir_do_json(edicao, cfg):
    _publicar(edicao, cfg)
    (cfg.dir_site / "index.html").write_text("apagado", encoding="utf-8")

    caminho = reconstruir_indice(cfg)

    assert caminho == cfg.dir_site / "index.html"
    assert "Radar de captação em saúde" in caminho.read_text(encoding="utf-8")
    assert "3 de setembro de 2026" in caminho.read_text(encoding="utf-8")


def test_reconstruir_indice_sem_edicoes_ainda_gera_a_pagina(cfg):
    caminho = reconstruir_indice(cfg)
    assert "Radar de captação em saúde" in caminho.read_text(encoding="utf-8")
