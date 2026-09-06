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


def escrever_config(tmp_path: Path, *fontes: str) -> Path:
    """Config do dia, com a lista de fontes esperadas explícita.

    É a lista que decide o exit code do dia sem publicação: fonte esperada e
    sem arquivo vira `ausente`, e `ausente` não é `vazio`. Por isso cada teste
    de dia vazio precisa dizer o que o dia deveria ter trazido.
    """
    caminho = tmp_path / "config.yaml"
    linhas = "".join(f"    - {fonte}\n" for fonte in fontes)
    caminho.write_text(
        "armazenamento:\n"
        f"  dir_dados: {FIXTURES.as_posix()}\n"
        "boletim:\n"
        "  site_url: https://exemplo.test/radar\n"
        f"  dir_saida: {(tmp_path / 'saida').as_posix()}\n"
        f"  dir_site: {(tmp_path / 'site').as_posix()}\n"
        "  fontes:\n" + linhas,
        encoding="utf-8",
    )
    return caminho


@pytest.fixture
def config(tmp_path) -> Path:
    return escrever_config(tmp_path, "inlabs", "iofmg")


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


def test_dia_sem_publicacao_sai_0_e_nao_grava_nada(tmp_path, capsys):
    """Domingo e feriado: a fonte esperada coletou, e o dia veio vazio."""
    config = escrever_config(tmp_path, "iofmg")
    assert _gerar(config, DATA_VAZIA) == 0

    assert capsys.readouterr().out.strip() == "boletim: vazio"
    assert not (tmp_path / "saida").exists()
    assert not (tmp_path / "site").exists()


def test_dia_vazio_com_uma_fonte_ausente_sai_1(config, tmp_path, capsys):
    """Sem o que publicar, mas a rodada é degradada: `vazio` no stdout, exit 1.

    O workflow lê `boletim: vazio` do stdout para não publicar; o 1 é o que
    impede a execução de terminar verde com uma fonte que nunca chegou.
    """
    assert _gerar(config, DATA_VAZIA) == 1

    assert capsys.readouterr().out.strip() == "boletim: vazio"
    assert not (tmp_path / "saida").exists()
    assert not (tmp_path / "site").exists()


def test_dia_com_todas_as_fontes_ausentes_sai_2(config, tmp_path, capsys):
    """Nada coletado é erro, não dia vazio.

    Era o desfecho mais perigoso do CLI: `ausente` contava como `vazio`, o
    comando saía 0 e a rotina ficava verde e muda enquanto ninguém olhava.
    """
    assert _gerar(config, "2026-09-05") == 2

    assert "erro: nenhuma fonte coletada em 2026-09-05" in capsys.readouterr().err
    assert not (tmp_path / "saida").exists()
    assert not (tmp_path / "site").exists()


def test_llm_indisponivel_sai_2_e_deixa_o_site_intocado(config, tmp_path, capsys):
    """Queda de verdade: a pasta tem resposta para o editorial, não para o lote.

    É o caminho de um modelo que caiu no meio da execução - diferente da pasta
    vazia (abaixo), que é configuração errada, não indisponibilidade.
    """
    so_editorial = tmp_path / "so-editorial"
    so_editorial.mkdir()
    (so_editorial / "editorial.json").write_text(
        (FIXTURES / "llm" / "editorial.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    codigo = main(
        ["gerar", "--config", str(config), "--data", DATA,
         "--llm", "falso", "--respostas", str(so_editorial)]
    )

    assert codigo == 2
    assert "erro:" in capsys.readouterr().err
    assert not (tmp_path / "site").exists()


def test_llm_falso_com_pasta_vazia_sai_2_com_mensagem_que_nomeia_a_pasta(
    config, tmp_path, capsys
):
    """Pasta sem nenhum arquivo de resposta é `--respostas` errado, não modelo fora do ar.

    A mensagem precisa nomear a pasta para o agente distinguir os dois casos
    no log, em vez de cair no mesmo caminho silencioso da queda.
    """
    vazio = tmp_path / "sem-respostas"
    vazio.mkdir()

    codigo = main(
        ["gerar", "--config", str(config), "--data", DATA,
         "--llm", "falso", "--respostas", str(vazio)]
    )

    assert codigo == 2
    erro = capsys.readouterr().err
    assert "erro:" in erro
    assert str(vazio) in erro
    assert not (tmp_path / "site").exists()


def test_llm_falso_usa_pasta_padrao_das_fixtures_mesmo_fora_da_raiz_do_repo(
    config, tmp_path, monkeypatch
):
    """O padrão de `--respostas` é ancorado no arquivo, não no cwd do processo.

    Antes da correção, `Path("tests/fixtures/boletim/llm")` só resolvia a
    partir da raiz do repositório; rodando de outro diretório, a pasta padrão
    "sumia" e um `--llm falso` sem `--respostas` caía no mesmo caminho de uma
    queda real do modelo.
    """
    monkeypatch.chdir(tmp_path)
    assert _gerar(config) == 1


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
