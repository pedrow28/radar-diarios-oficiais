from datetime import date
from pathlib import Path

from boletim.config import ConfigBoletim, ConfigCTA

YAML_MINIMO = """
armazenamento:
  dir_dados: ./data
"""

YAML_COM_BOLETIM = """
armazenamento:
  dir_dados: ./outros-dados
boletim:
  modelo: claude-opus-4
  lote: 5
  max_chars_texto: 1000
  max_itens_dia: 50
  tentativas_llm: 3
  timeout_llm_s: 60
  site_url: "https://exemplo.com/radar"
  fontes: [iofmg]
  dir_saida: ./outra-saida
  dir_site: ./outro-site
  marcas_mg: ["Minas Gerais", "Uberlândia"]
  cta:
    whatsapp: "5500000000000"
    texto_botao: "Fale conosco"
    mensagem: "Oi, vi o boletim de {data}"
"""


def _escrever(tmp_path: Path, conteudo: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(conteudo, encoding="utf-8")
    return p


def test_defaults_quando_bloco_boletim_nao_existe(tmp_path: Path):
    caminho = _escrever(tmp_path, YAML_MINIMO)
    cfg = ConfigBoletim.carregar(caminho)
    assert cfg.modelo == "claude-haiku-4-5"
    assert cfg.lote == 12
    assert cfg.max_chars_texto == 3000
    assert cfg.max_itens_dia == 120
    assert cfg.tentativas_llm == 2
    assert cfg.timeout_llm_s == 180
    assert cfg.site_url == "https://pedrow28.github.io/radar-diarios-oficiais"
    assert cfg.fontes == ["dou", "iofmg"]
    assert cfg.dir_saida == Path("./boletim/saida")
    assert cfg.dir_site == Path("./site")
    assert cfg.dir_dados == Path("./data")
    assert cfg.marcas_mg[0] == "Minas Gerais"
    assert "mineir" in cfg.marcas_mg
    assert cfg.cta == ConfigCTA()


def test_yaml_sobrescreve_os_defaults(tmp_path: Path):
    caminho = _escrever(tmp_path, YAML_COM_BOLETIM)
    cfg = ConfigBoletim.carregar(caminho)
    assert cfg.modelo == "claude-opus-4"
    assert cfg.lote == 5
    assert cfg.max_chars_texto == 1000
    assert cfg.max_itens_dia == 50
    assert cfg.tentativas_llm == 3
    assert cfg.timeout_llm_s == 60
    assert cfg.site_url == "https://exemplo.com/radar"
    assert cfg.fontes == ["iofmg"]
    assert cfg.dir_saida == Path("./outra-saida")
    assert cfg.dir_site == Path("./outro-site")
    # dir_dados vem do topo do YAML (armazenamento.dir_dados), nao do bloco boletim.
    assert cfg.dir_dados == Path("./outros-dados")
    assert cfg.cta.whatsapp == "5500000000000"
    assert cfg.cta.texto_botao == "Fale conosco"
    assert cfg.cta.mensagem == "Oi, vi o boletim de {data}"
    assert cfg.marcas_mg == ["Minas Gerais", "Uberlândia"]


def test_bloco_parcial_mantem_defaults_dos_campos_omitidos(tmp_path: Path):
    yaml_parcial = """
armazenamento:
  dir_dados: ./data
boletim:
  lote: 7
  cta:
    whatsapp: "5511999999999"
"""
    caminho = _escrever(tmp_path, yaml_parcial)
    cfg = ConfigBoletim.carregar(caminho)
    # Campo sobrescrito.
    assert cfg.lote == 7
    assert cfg.cta.whatsapp == "5511999999999"
    # Campos omitidos no bloco `boletim` continuam com o default da dataclass
    # (prova de que `carregar` usa o spread e não uma lista paralela de literais).
    assert cfg.modelo == "claude-haiku-4-5"
    assert cfg.max_chars_texto == 3000
    assert cfg.max_itens_dia == 120
    assert cfg.tentativas_llm == 2
    assert cfg.timeout_llm_s == 180
    assert cfg.site_url == "https://pedrow28.github.io/radar-diarios-oficiais"
    assert cfg.fontes == ["dou", "iofmg"]
    assert cfg.dir_saida == Path("./boletim/saida")
    assert cfg.dir_site == Path("./site")
    # Default do ConfigCTA preservado para os campos não sobrescritos.
    assert cfg.cta.texto_botao == ConfigCTA().texto_botao
    assert cfg.cta.mensagem == ConfigCTA().mensagem


def test_config_boletim_inexistente_da_erro_claro(tmp_path: Path):
    import pytest

    with pytest.raises(FileNotFoundError):
        ConfigBoletim.carregar(tmp_path / "nao-existe.yaml")


def test_cta_url_contem_whatsapp_e_data_formatada_url_encoded():
    cta = ConfigCTA()
    url = cta.url(date(2026, 9, 3))
    assert "wa.me/5531984483183?text=" in url
    assert "03%2F09%2F2026" in url
