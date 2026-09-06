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


ORGAOS_DOU_PADRAO = [
    "Ministério da Saúde",
    "Presidência da República",
    "Ministério da Fazenda",
    "Ministério do Planejamento e Orçamento",
]


def _com_bloco_dou(tmp_path: Path, bloco: str) -> Path:
    """Escreve o YAML mínimo trocando o corpo do bloco `fontes.dou`."""
    conteudo = YAML_MINIMO.replace(
        '  dou:\n'
        '    orgao: "Ministério da Saúde"\n'
        "    delta: 75\n"
        "    concorrencia: 5\n"
        "    baixar_texto_integral: true\n",
        f"  dou:\n{bloco}",
    )
    p = tmp_path / "c.yaml"
    p.write_text(conteudo, encoding="utf-8")
    return p


def test_dou_orgao_legado_vira_lista_de_um_orgao(caminho_config: Path):
    """O YAML antigo tem `orgao:` e precisa continuar coletando o mesmo órgão."""
    cfg = Config.carregar(caminho_config)
    assert cfg.dou.orgaos == ["Ministério da Saúde"]


def test_dou_orgaos_vence_o_orgao_legado_e_avisa(tmp_path: Path):
    """Com as duas chaves, mandar na antiga esconderia metade do escopo."""
    p = _com_bloco_dou(
        tmp_path,
        '    orgao: "Ministério da Educação"\n'
        "    orgaos:\n"
        '      - "Ministério da Saúde"\n'
        '      - "Ministério da Fazenda"\n',
    )
    logger = configurar_log()
    registros: list[str] = []

    class Coletor(logging.Handler):
        def emit(self, registro: logging.LogRecord) -> None:
            registros.append(registro.getMessage())

    handler = Coletor(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        cfg = Config.carregar(p)
    finally:
        logger.removeHandler(handler)

    assert cfg.dou.orgaos == ["Ministério da Saúde", "Ministério da Fazenda"]
    assert any("orgao" in m and "obsoleto" in m for m in registros), registros


def test_dou_usa_defaults_quando_o_yaml_nao_traz_orgao_nenhum(tmp_path: Path):
    p = _com_bloco_dou(tmp_path, "    delta: 75\n")
    cfg = Config.carregar(p)
    assert cfg.dou.orgaos == ORGAOS_DOU_PADRAO
    assert cfg.dou.subunidades_extra == ["Casa Civil"]


def test_dou_le_orgaos_e_subunidades_do_yaml(tmp_path: Path):
    p = _com_bloco_dou(
        tmp_path,
        "    orgaos:\n"
        '      - "Presidência da República"\n'
        "    subunidades_extra:\n"
        '      - "Casa Civil"\n'
        '      - "Vice-Presidência"\n',
    )
    cfg = Config.carregar(p)
    assert cfg.dou.orgaos == ["Presidência da República"]
    assert cfg.dou.subunidades_extra == ["Casa Civil", "Vice-Presidência"]


def test_config_padrao_do_projeto_cobre_o_escopo_decidido():
    """O `config/config.yaml` versionado é o que roda na nuvem."""
    raiz = Path(__file__).resolve().parent.parent
    cfg = Config.carregar(raiz / "config" / "config.yaml")
    assert cfg.dou.orgaos == ORGAOS_DOU_PADRAO
    assert cfg.dou.subunidades_extra == ["Casa Civil"]


def test_inlabs_usa_defaults_quando_bloco_nao_existe(caminho_config: Path):
    cfg = Config.carregar(caminho_config)
    assert cfg.inlabs.secoes == ["DO1"]
    assert cfg.inlabs.orgaos == [
        "Ministério da Saúde",
        "Agência Nacional de Vigilância Sanitária",
        "Presidência da República",
        "Ministério da Fazenda",
        "Ministério do Planejamento e Orçamento",
    ]
    assert cfg.inlabs.subunidades_extra == ["Casa Civil"]


def test_inlabs_le_valores_do_yaml(tmp_path: Path):
    # `YAML_MINIMO` já declara um mapa `fontes:`; um segundo mapa `fontes:`
    # no mesmo arquivo sobrescreveria o primeiro, então o bloco `inlabs`
    # entra dentro do mapa `fontes:` existente.
    conteudo = YAML_MINIMO.rstrip().replace(
        "armazenamento:",
        "  inlabs:\n"
        "    secoes: [DO1, DO2]\n"
        "    orgaos: [Ministério da Saúde]\n"
        "    subunidades_extra: [Casa Civil, Vice-Presidência]\n"
        "armazenamento:",
    )
    p = tmp_path / "c.yaml"
    p.write_text(conteudo, encoding="utf-8")
    cfg = Config.carregar(p)
    assert cfg.inlabs.secoes == ["DO1", "DO2"]
    assert cfg.inlabs.orgaos == ["Ministério da Saúde"]
    assert cfg.inlabs.subunidades_extra == ["Casa Civil", "Vice-Presidência"]


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
