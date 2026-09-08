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
from boletim.site import publicar, reconstruir_indice, valor_dia
from tests.fixtures.boletim.edicao_exemplo import edicao_exemplo


@pytest.fixture
def cfg(tmp_path) -> ConfigBoletim:
    # `dir_saida` também vai para o tmp: `reconstruir_indice` lê o `itens.json`
    # do dia para recalcular `valor_dia`, e apontado para o padrão ele leria a
    # saída real do repositório - o teste passaria a depender de qual dia
    # alguém gerou por último na máquina.
    return ConfigBoletim(dir_site=tmp_path / "site", dir_saida=tmp_path / "saida")


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


def test_publicar_leva_a_folha_de_estilo_junto_com_a_pagina(edicao, cfg):
    """O site tem CSS externo desde que saiu do template do e-mail.

    Página publicada com um `site.css` de duas semanas atrás é pior que página
    sem estilo nenhum, porque ninguém repara: o asset anda junto do HTML.
    """
    pagina = _publicar(edicao, cfg)

    css = cfg.dir_site / "assets" / "site.css"
    assert css.exists()
    assert "--luz: #40D7FF" in css.read_text(encoding="utf-8")
    assert "assets/site.css" in pagina.read_text(encoding="utf-8")


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
            # A soma dos `valor_brl` dos atos de captação: é a coluna do
            # dinheiro do índice, e ela sai daqui.
            "valor_dia": 29334567.89,
            "total_relevante": 4,
        }
    ]


def test_dia_sem_cifra_declarada_fica_com_valor_dia_nulo(edicao, cfg):
    """Zero e "não declarado" são coisas diferentes.

    Um dia em que nenhum ato de captação trouxe cifra não recebe `R$ 0,00` no
    índice: a coluna do dinheiro fica vazia, que é a resposta honesta.
    """
    sem_cifra = replace(
        edicao,
        secoes={
            **edicao.secoes,
            "A": tuple(replace(i, valor_brl=None) for i in edicao.secoes["A"]),
        },
    )
    _publicar(sem_cifra, cfg)

    entradas = json.loads((cfg.dir_site / "edicoes.json").read_text(encoding="utf-8"))
    assert entradas[0]["valor_dia"] is None
    assert "R$" not in (cfg.dir_site / "index.html").read_text(encoding="utf-8")


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
    # Reconstruir não inventa arquivo: um site sem edição nenhuma não ganha um
    # `edicoes.json` vazio só por causa da regeneração do índice.
    assert not (cfg.dir_site / "edicoes.json").exists()


def test_reconstruir_indice_leva_os_assets_junto(edicao, cfg):
    """`boletim site` é o comando de quem mexeu no CSS e quer ver o site novo.

    Sem copiar os assets ele regerava um `index.html` que pedia uma folha de
    estilo antiga - e página com CSS velho é pior que página sem CSS nenhum,
    porque ninguém repara.
    """
    _publicar(edicao, cfg)
    for asset in ("site.css", "hero.jpg"):
        (cfg.dir_site / "assets" / asset).unlink()

    reconstruir_indice(cfg)

    assert (cfg.dir_site / "assets" / "site.css").exists()
    assert (cfg.dir_site / "assets" / "hero.jpg").exists()


def test_reconstruir_num_site_vazio_ja_publica_os_assets(cfg):
    """Reconstruir não depende de haver edição: o índice em si pede a folha."""
    reconstruir_indice(cfg)

    assert (cfg.dir_site / "assets" / "site.css").exists()
    assert (cfg.dir_site / "assets" / "hero.jpg").exists()


def test_valor_dia_sai_arredondado_em_centavos(edicao, cfg):
    """Somar float acumula binário: `edicoes.json` é arquivo público e legível.

    Sem o arredondamento a soma de dois valores em reais vira
    `29334567.890000004` no arquivo e na página.
    """
    duas_cifras = replace(
        edicao,
        secoes={
            **edicao.secoes,
            "A": (
                replace(edicao.secoes["A"][0], valor_brl=0.1),
                replace(edicao.secoes["A"][1], valor_brl=0.2),
            ),
        },
    )
    assert 0.1 + 0.2 != 0.3  # a premissa do teste, explícita
    assert valor_dia(duas_cifras) == 0.3

    _publicar(duas_cifras, cfg)
    bruto = (cfg.dir_site / "edicoes.json").read_text(encoding="utf-8")
    assert '"valor_dia": 0.3' in bruto


def test_valor_dia_reconstruido_do_disco_tambem_sai_arredondado(cfg):
    """O caminho da ficha antiga soma os mesmos floats e tem o mesmo dever."""
    antiga = {
        "data": "2026-09-03",
        "titulo": "Boletim de 03/09",
        "url": "edicoes/2026-09-03.html",
        "contagens": {"A": 2, "B": 0, "C": 0, "D": 0},
        "parcial": False,
    }
    cfg.dir_site.mkdir(parents=True)
    (cfg.dir_site / "edicoes.json").write_text(
        json.dumps([antiga], ensure_ascii=False), encoding="utf-8"
    )
    dia = cfg.dir_saida / "2026-09-03"
    dia.mkdir(parents=True)
    (dia / "itens.json").write_text(
        json.dumps(
            {
                "itens": [
                    {"categoria": "A", "valor_brl": 0.1},
                    {"categoria": "A", "valor_brl": 0.2},
                ]
            }
        ),
        encoding="utf-8",
    )

    reconstruir_indice(cfg)

    entradas = json.loads((cfg.dir_site / "edicoes.json").read_text(encoding="utf-8"))
    assert entradas[0]["valor_dia"] == 0.3


def test_reconstruir_indice_recalcula_o_valor_dia_que_faltava(edicao, cfg):
    """`valor_dia` e `total_relevante` nasceram depois das primeiras edições.

    Um `edicoes.json` gravado antes deles não pode obrigar o arquivo inteiro a
    ser regerado dia a dia só para preencher uma coluna: `reconstruir` lê o
    `itens.json` do dia e completa a ficha antiga no lugar.
    """
    antiga = {
        "data": "2026-09-03",
        "titulo": edicao.titulo,
        "url": "edicoes/2026-09-03.html",
        "contagens": {"A": 2, "B": 1, "C": 1, "D": 2},
        "parcial": True,
    }
    cfg.dir_site.mkdir(parents=True)
    (cfg.dir_site / "edicoes.json").write_text(
        json.dumps([antiga], ensure_ascii=False), encoding="utf-8"
    )
    dia = cfg.dir_saida / "2026-09-03"
    dia.mkdir(parents=True)
    (dia / "itens.json").write_text(
        json.dumps(
            {
                "itens": [
                    {"categoria": "A", "valor_brl": 1234567.89},
                    {"categoria": "A", "valor_brl": None},
                    {"categoria": "B", "valor_brl": 999.0},
                ]
            }
        ),
        encoding="utf-8",
    )

    indice = reconstruir_indice(cfg).read_text(encoding="utf-8")

    entradas = json.loads((cfg.dir_site / "edicoes.json").read_text(encoding="utf-8"))
    # Só a categoria A entra na soma; item sem cifra não vira zero.
    assert entradas[0]["valor_dia"] == 1234567.89
    assert entradas[0]["total_relevante"] == 4
    assert "R$ 1.234.567,89" in indice


def test_ficha_antiga_sem_o_dia_no_disco_fica_sem_valor_em_vez_de_zero(edicao, cfg):
    """A pasta de saída não guarda o dia para sempre. Perdido o `itens.json`, a
    coluna do dinheiro daquela edição fica vazia - um zero seria mentira."""
    antiga = {
        "data": "2026-08-31",
        "titulo": "Boletim antigo",
        "url": "edicoes/2026-08-31.html",
        "contagens": {"A": 3, "B": 0, "C": 1, "D": 0},
        "parcial": False,
    }
    cfg.dir_site.mkdir(parents=True)
    (cfg.dir_site / "edicoes.json").write_text(
        json.dumps([antiga], ensure_ascii=False), encoding="utf-8"
    )

    reconstruir_indice(cfg)

    entradas = json.loads((cfg.dir_site / "edicoes.json").read_text(encoding="utf-8"))
    assert entradas[0]["valor_dia"] is None
    assert entradas[0]["total_relevante"] == 4


def test_publicar_completa_as_fichas_antigas_do_arquivo(edicao, cfg):
    """Publicar o dia de hoje não pode estourar por causa da ficha de ontem.

    `render_index` roda com `StrictUndefined`: uma entrada antiga sem
    `valor_dia` derrubaria a publicação inteira se `publicar` não completasse o
    arquivo antes de renderizar.
    """
    antiga = {
        "data": "2026-09-02",
        "titulo": "Boletim de 02/09",
        "url": "edicoes/2026-09-02.html",
        "contagens": {"A": 1, "B": 0, "C": 0, "D": 0},
        "parcial": False,
    }
    cfg.dir_site.mkdir(parents=True)
    (cfg.dir_site / "edicoes.json").write_text(
        json.dumps([antiga], ensure_ascii=False), encoding="utf-8"
    )

    _publicar(edicao, cfg)

    entradas = json.loads((cfg.dir_site / "edicoes.json").read_text(encoding="utf-8"))
    assert [e["data"] for e in entradas] == ["2026-09-03", "2026-09-02"]
    assert entradas[1]["valor_dia"] is None


def test_publicar_com_edicoes_json_corrompido_nao_deixa_site_pela_metade(edicao, cfg):
    """Um `edicoes.json` ilegível tem de estourar antes de qualquer gravação.

    `publicar` lê e mescla o arquivo, e só depois grava; se a ordem regredir
    para "grava a página primeiro", este teste falha porque a página passa a
    existir mesmo com a exceção.
    """
    cfg.dir_site.mkdir(parents=True)
    corrompido = "{ isto não é json"
    (cfg.dir_site / "edicoes.json").write_text(corrompido, encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        _publicar(edicao, cfg)

    assert not (cfg.dir_site / "edicoes" / "2026-09-03.html").exists()
    assert (cfg.dir_site / "edicoes.json").read_text(encoding="utf-8") == corrompido
