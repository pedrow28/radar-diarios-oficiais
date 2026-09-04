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
