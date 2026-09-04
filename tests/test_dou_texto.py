from pathlib import Path

import pytest

from radar.fontes.dou.texto import TextoDOU, extrair_texto


@pytest.fixture
def html_pub(dir_fixtures: Path) -> str:
    return (dir_fixtures / "dou" / "pub-portaria-gm-ms-12141.html").read_bytes().decode("utf-8")


def test_extrai_identifica(html_pub: str):
    assert "12.141" in extrair_texto(html_pub).identifica


def test_extrai_ementa(html_pub: str):
    ementa = extrair_texto(html_pub).ementa
    assert "SAMU 192" in ementa


def test_texto_integral_e_muito_maior_que_o_snippet_da_listagem(html_pub: str):
    """A listagem trunca em ~420 chars; e por isso que existe o estagio 2."""
    assert len(extrair_texto(html_pub).texto) > 1500


def test_texto_preserva_valor_monetario(html_pub: str):
    """O dado que sustenta o juizo de captacao no agente."""
    assert "274.372,80" in extrair_texto(html_pub).texto


def test_texto_contem_o_articulado(html_pub: str):
    texto = extrair_texto(html_pub).texto
    assert "Art. 1" in texto
    assert "Art. 2" in texto


def test_texto_nao_contem_tags_html(html_pub: str):
    texto = extrair_texto(html_pub).texto
    assert "<" not in texto
    assert "&nbsp;" not in texto


def test_html_sem_corpo_devolve_texto_vazio_sem_estourar():
    resultado = extrair_texto("<html><body><p>nada</p></body></html>")
    assert isinstance(resultado, TextoDOU)
    assert resultado.texto == ""
    assert resultado.identifica is None
