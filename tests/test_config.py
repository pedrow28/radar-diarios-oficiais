import logging
from pathlib import Path

import pytest

from radar.core.config import Config
from radar.core.log import configurar_log

YAML_MINIMO = """
timezone: America/Sao_Paulo
fontes:
  dou:
    orgao: "Ministério da Saúde"
    delta: 75
    concorrencia: 5
    baixar_texto_integral: true
  iofmg:
    caderno: "Diário do Executivo"
    secao: "Secretaria de Estado de Saúde"
    tipos_publicacao: [PORTARIA, RESOLUÇÃO, DELIBERAÇÃO]
armazenamento:
  dir_dados: ./data
  reter_bruto_dias: 30
"""


@pytest.fixture
def caminho_config(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(YAML_MINIMO, encoding="utf-8")
    return p


def test_carrega_config_do_yaml(caminho_config: Path):
    cfg = Config.carregar(caminho_config)
    assert cfg.timezone == "America/Sao_Paulo"
    assert cfg.dou.orgao == "Ministério da Saúde"
    assert cfg.dou.delta == 75
    assert cfg.dou.baixar_texto_integral is True
    assert cfg.iofmg.secao == "Secretaria de Estado de Saúde"
    assert "DELIBERAÇÃO" in cfg.iofmg.tipos_publicacao
    assert cfg.reter_bruto_dias == 30


def test_tipos_de_publicacao_sao_configuraveis_nao_fixos(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text(
        YAML_MINIMO.replace("[PORTARIA, RESOLUÇÃO, DELIBERAÇÃO]", "[EDITAL]"),
        encoding="utf-8",
    )
    assert Config.carregar(p).iofmg.tipos_publicacao == ["EDITAL"]


def test_config_inexistente_da_erro_claro(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        Config.carregar(tmp_path / "nao-existe.yaml")


def test_nenhum_email_hardcoded_no_pacote():
    """Regressão: hoje pedrowilliamrd@gmail.com está fixo em 2 scripts."""
    raiz = Path(__file__).resolve().parent.parent / "radar"
    for arquivo in raiz.rglob("*.py"):
        assert "@gmail.com" not in arquivo.read_text(encoding="utf-8"), arquivo


def test_configurar_log_e_idempotente(tmp_path: Path):
    """Chamar duas vezes nao pode duplicar handlers (bug 7 da spec)."""
    destino = tmp_path / "radar.log"
    primeiro = configurar_log(arquivo=destino)
    quantos = len(primeiro.handlers)
    segundo = configurar_log(arquivo=destino)
    assert segundo is primeiro
    assert len(segundo.handlers) == quantos


def test_configurar_log_escreve_no_arquivo(tmp_path: Path):
    destino = tmp_path / "radar.log"
    logger = configurar_log(arquivo=destino)
    logger.info("mensagem de teste")
    for h in logger.handlers:
        h.flush()
    assert "mensagem de teste" in destino.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _limpa_logger():
    yield
    logger = logging.getLogger("radar")
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)
