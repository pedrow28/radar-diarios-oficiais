import json
from datetime import date
from pathlib import Path

import pytest

from radar.cli import main

YAML = """
timezone: America/Sao_Paulo
fontes:
  dou:
    orgao: "Ministério da Saúde"
    delta: 75
    concorrencia: 2
    baixar_texto_integral: false
  iofmg:
    caderno: "Diário do Executivo"
    secao: "Secretaria de Estado de Saúde"
    tipos_publicacao: [PORTARIA]
armazenamento:
  dir_dados: "{dir_dados}"
  reter_bruto_dias: 30
"""


@pytest.fixture
def ambiente(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(YAML.format(dir_dados=(tmp_path / "data").as_posix()), encoding="utf-8")

    from radar.core.erros import Status
    from radar.core.modelos import Resultado

    def coleta_falsa(self, data, forcar=False):
        from radar.core.datas import agora_utc

        return Resultado(
            fonte=self.nome, data_publicacao=data, coletado_em=agora_utc(),
            status=Status.OK, escopo={}, publicacoes=[], avisos=[],
        )

    monkeypatch.setattr("radar.fontes.dou.coletor.FonteDOU.coletar", coleta_falsa)
    monkeypatch.setattr("radar.fontes.iofmg.coletor.FonteIOFMG.coletar", coleta_falsa)
    return cfg, tmp_path / "data"


def test_coletar_uma_fonte_devolve_exit_zero(ambiente):
    cfg, _ = ambiente
    assert main(["coletar", "--config", str(cfg), "--data", "2026-09-04", "--fonte", "dou"]) == 0


def test_coletar_grava_o_json_normalizado(ambiente):
    cfg, dir_dados = ambiente
    main(["coletar", "--config", str(cfg), "--data", "2026-09-04", "--fonte", "dou"])
    destino = dir_dados / "normalized" / "2026-09-04" / "dou.json"
    assert destino.exists()
    assert json.loads(destino.read_text(encoding="utf-8"))["status"] == "ok"


def test_coletar_todas_gera_um_json_por_fonte(ambiente):
    cfg, dir_dados = ambiente
    main(["coletar", "--config", str(cfg), "--data", "2026-09-04", "--fonte", "todas"])
    pasta = dir_dados / "normalized" / "2026-09-04"
    assert (pasta / "dou.json").exists()
    assert (pasta / "iofmg.json").exists()


def test_status_parcial_devolve_exit_um(ambiente, monkeypatch):
    cfg, _ = ambiente
    from radar.core.datas import agora_utc
    from radar.core.erros import Status
    from radar.core.modelos import Resultado

    def parcial(self, data, forcar=False):
        return Resultado(
            fonte=self.nome, data_publicacao=data, coletado_em=agora_utc(),
            status=Status.PARCIAL, escopo={}, publicacoes=[], avisos=["algo falhou"],
        )

    monkeypatch.setattr("radar.fontes.dou.coletor.FonteDOU.coletar", parcial)
    assert main(["coletar", "--config", str(cfg), "--data", "2026-09-04", "--fonte", "dou"]) == 1


def test_fonte_indisponivel_devolve_exit_dois(ambiente, monkeypatch):
    cfg, _ = ambiente
    from radar.core.erros import FonteIndisponivel

    def explode(self, data, forcar=False):
        raise FonteIndisponivel("rede caiu")

    monkeypatch.setattr("radar.fontes.dou.coletor.FonteDOU.coletar", explode)
    assert main(["coletar", "--config", str(cfg), "--data", "2026-09-04", "--fonte", "dou"]) == 2


def test_pior_status_entre_fontes_define_o_exit(ambiente, monkeypatch):
    cfg, _ = ambiente
    from radar.core.erros import FonteIndisponivel

    def explode(self, data, forcar=False):
        raise FonteIndisponivel("rede caiu")

    monkeypatch.setattr("radar.fontes.iofmg.coletor.FonteIOFMG.coletar", explode)
    assert main(["coletar", "--config", str(cfg), "--data", "2026-09-04", "--fonte", "todas"]) == 2


def test_data_invalida_devolve_exit_dois(ambiente):
    cfg, _ = ambiente
    assert main(["coletar", "--config", str(cfg), "--data", "ontem", "--fonte", "dou"]) == 2


def test_consultar_encontra_no_historico(ambiente, capsys):
    cfg, dir_dados = ambiente
    from datetime import datetime, timezone

    from radar.core.modelos import Publicacao, gerar_id
    from radar.core.storage import Storage

    s = Storage(dir_dados)
    d = date(2026, 9, 4)
    s.gravar([
        Publicacao(
            id=gerar_id("dou", d, "https://x/1", "T"), fonte="dou", data_publicacao=d,
            coletado_em=datetime(2026, 9, 4, tzinfo=timezone.utc), orgao="MS", unidade=None,
            secao="1", pagina=None, edicao=None, tipo="Portaria", numero=None, titulo="T",
            ementa=None, texto="ampliacao do teto MAC", url="https://x/1", origem={},
        )
    ])
    s.fechar()
    assert main(["consultar", "--config", str(cfg), "teto"]) == 0
    assert "teto MAC" in capsys.readouterr().out


def test_consultar_sem_resultado_devolve_zero(ambiente, capsys):
    cfg, _ = ambiente
    assert main(["consultar", "--config", str(cfg), "inexistente"]) == 0


def test_modulo_executavel_com_python_m():
    """Sem a guarda __main__, `python -m radar.cli` sai 0 em silencio.

    Um cron nessa forma reportaria sucesso todo dia sem coletar nada. Usamos
    --help porque ele exercita o despacho sem tocar a rede.
    """
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "radar.cli", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "coletar" in r.stdout, "o --help precisa listar os subcomandos"
    assert "consultar" in r.stdout


# ── C5: o exit code nunca é escolhido pelo Python ───────────────────────────


def test_excecao_inesperada_em_uma_fonte_devolve_exit_dois(ambiente, monkeypatch):
    """Antes: a exceção escapava e o Python saía 1, que é `parcial`."""

    def explode(self, data, forcar=False):
        raise RuntimeError("desembrulho do PKCS#7 quebrou")

    monkeypatch.setattr("radar.fontes.dou.coletor.FonteDOU.coletar", explode)
    assert main(["coletar", "--config", str(ambiente[0]), "--data", "2026-09-04",
                 "--fonte", "dou"]) == 2


def test_fonte_quebrada_nao_impede_a_seguinte(ambiente, monkeypatch):
    """A fonte sobrevivente precisa rodar e gravar o JSON dela."""
    cfg, dir_dados = ambiente

    def explode(self, data, forcar=False):
        raise TypeError("int() com totalPaginas None")

    monkeypatch.setattr("radar.fontes.dou.coletor.FonteDOU.coletar", explode)
    codigo = main(["coletar", "--config", str(cfg), "--data", "2026-09-04", "--fonte", "todas"])
    assert codigo == 2
    assert (dir_dados / "normalized" / "2026-09-04" / "iofmg.json").exists()
    assert not (dir_dados / "normalized" / "2026-09-04" / "dou.json").exists()


def test_falha_de_fonte_tambem_sai_em_stdout(ambiente, monkeypatch, capsys):
    """Quem captura só stdout perdia a informação de que uma fonte caiu."""
    cfg, _ = ambiente

    def explode(self, data, forcar=False):
        raise OSError("disco cheio")

    monkeypatch.setattr("radar.fontes.dou.coletor.FonteDOU.coletar", explode)
    main(["coletar", "--config", str(cfg), "--data", "2026-09-04", "--fonte", "todas"])
    saida = capsys.readouterr().out
    assert "dou: erro | disco cheio" in saida
    assert "iofmg: ok" in saida, "a linha da fonte que deu certo continua igual"


def test_excecao_fora_do_laco_de_fontes_devolve_exit_dois(ambiente, monkeypatch):
    """Falha ao abrir o storage não pode sair 1 nem estourar traceback."""

    def storage_quebrado(*args, **kwargs):
        raise OSError("permissão negada em ./data")

    monkeypatch.setattr("radar.cli.Storage", storage_quebrado)
    assert main(["coletar", "--config", str(ambiente[0]), "--data", "2026-09-04",
                 "--fonte", "dou"]) == 2


def test_erro_inesperado_no_consultar_devolve_exit_dois(ambiente, monkeypatch):
    cfg, _ = ambiente

    def consulta_quebrada(self, termo, desde=None):
        raise RuntimeError("banco corrompido")

    monkeypatch.setattr("radar.core.storage.Storage.consultar", consulta_quebrada)
    assert main(["consultar", "--config", str(cfg), "teto"]) == 2
