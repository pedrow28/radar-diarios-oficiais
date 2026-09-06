"""O contrato de saída do CLI é lido por cron e por agente, não por humano.

Por isso os testes olham o exit code antes do conteúdo: 0 é "publicou inteiro",
1 é "publicou com ressalva" e 2 é "não publicou". O caso que mais importa é o
último - um dia em que o LLM caiu não pode deixar meia edição no ar.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boletim.cli import main

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "boletim"
DATA = "2026-09-03"
DATA_VAZIA = "2026-09-06"


@pytest.fixture
def config(tmp_path) -> Path:
    caminho = tmp_path / "config.yaml"
    caminho.write_text(
        "armazenamento:\n"
        f"  dir_dados: {FIXTURES.as_posix()}\n"
        "boletim:\n"
        "  site_url: https://exemplo.test/radar\n"
        f"  dir_saida: {(tmp_path / 'saida').as_posix()}\n"
        f"  dir_site: {(tmp_path / 'site').as_posix()}\n"
        "  fontes:\n"
        "    - inlabs\n"
        "    - iofmg\n",
        encoding="utf-8",
    )
    return caminho


def _gerar(config: Path, data: str = DATA, *extra: str) -> int:
    return main(
        ["gerar", "--config", str(config), "--data", data, "--llm", "falso", *extra]
    )


def test_gerar_sai_1_porque_o_dia_veio_parcial(config, capsys):
    assert _gerar(config) == 1

    saida = capsys.readouterr().out
    assert "12 publicações" in saida
    assert "status=parcial" in saida


def test_gerar_grava_a_saida_do_dia_e_publica_no_site(config, tmp_path):
    _gerar(config)

    dia = tmp_path / "saida" / DATA
    assert (dia / "prefiltro.json").exists()
    assert (dia / "edicao.md").exists()
    assert "<!DOCTYPE html>" in (dia / "edicao.html").read_text(encoding="utf-8")

    itens = json.loads((dia / "itens.json").read_text(encoding="utf-8"))
    assert itens["edicao"]["titulo"]
    assert itens["edicao"]["em_30_segundos"]
    assert len(itens["itens"]) == 7
    assert itens["gerado_em"]

    assert (tmp_path / "site" / "edicoes" / f"{DATA}.html").exists()
    assert (tmp_path / "site" / "index.html").exists()


def test_gerar_com_sem_site_nao_toca_no_site(config, tmp_path):
    assert _gerar(config, DATA, "--sem-site") == 1
    assert (tmp_path / "saida" / DATA / "edicao.html").exists()
    assert not (tmp_path / "site").exists()


def test_dia_sem_publicacao_sai_0_e_nao_grava_nada(config, tmp_path, capsys):
    assert _gerar(config, DATA_VAZIA) == 0

    assert capsys.readouterr().out.strip() == "boletim: vazio"
    assert not (tmp_path / "saida").exists()
    assert not (tmp_path / "site").exists()


def test_llm_indisponivel_sai_2_e_deixa_o_site_intocado(config, tmp_path, capsys):
    vazio = tmp_path / "sem-respostas"
    vazio.mkdir()

    codigo = main(
        ["gerar", "--config", str(config), "--data", DATA,
         "--llm", "falso", "--respostas", str(vazio)]
    )

    assert codigo == 2
    assert "erro:" in capsys.readouterr().err
    assert not (tmp_path / "site").exists()


def test_renderizar_regrava_a_partir_do_disco_sem_chamar_o_llm(config, tmp_path):
    _gerar(config)
    dia = tmp_path / "saida" / DATA
    original = (dia / "edicao.html").read_text(encoding="utf-8")
    (dia / "edicao.html").unlink()
    (tmp_path / "site" / "edicoes" / f"{DATA}.html").unlink()

    assert main(["renderizar", "--config", str(config), "--data", DATA]) == 0

    assert (dia / "edicao.html").read_text(encoding="utf-8") == original
    assert (tmp_path / "site" / "edicoes" / f"{DATA}.html").exists()


def test_renderizar_sem_dia_gerado_sai_2(config, capsys):
    assert main(["renderizar", "--config", str(config), "--data", DATA]) == 2
    assert "erro:" in capsys.readouterr().err


def test_site_reconstroi_o_indice(config, tmp_path):
    _gerar(config)
    (tmp_path / "site" / "index.html").write_text("apagado", encoding="utf-8")

    assert main(["site", "--config", str(config)]) == 0
    assert "Radar de captação em saúde" in (
        tmp_path / "site" / "index.html"
    ).read_text(encoding="utf-8")


def test_config_inexistente_sai_2_sem_estourar_excecao(tmp_path, capsys):
    codigo = main(["site", "--config", str(tmp_path / "nao-existe.yaml")])
    assert codigo == 2
    assert "erro:" in capsys.readouterr().err
