"""Parse do zip do INLABS: um XML por matéria, dentro de um zip por seção."""

import io
import zipfile
from pathlib import Path

import pytest

from radar.fontes.inlabs.xml import Artigo, listar_artigos


@pytest.fixture
def zip_do1(dir_fixtures: Path) -> bytes:
    return (dir_fixtures / "inlabs" / "2026-09-03-DO1.zip").read_bytes()


def _por_materia(artigos: list[Artigo]) -> dict[str, Artigo]:
    return {a.id_materia: a for a in artigos}


def test_le_os_quatro_artigos_da_edicao(zip_do1):
    artigos, avisos = listar_artigos(zip_do1)
    assert len(artigos) == 4
    assert avisos == []


def test_atributos_do_article_viram_campos_do_artigo(zip_do1):
    artigos, _ = listar_artigos(zip_do1)
    a = _por_materia(artigos)["12345678"]
    assert a.id == "1234567"
    assert a.pub_name == "DO1"
    assert a.art_type == "Portaria"
    assert a.pub_date == "03/09/2026"
    assert a.art_category == "Ministério da Saúde/Gabinete do Ministro"
    assert a.number_page == "45"
    assert a.pdf_page == "https://pdf.in.gov.br/pdf/2026/09/03/1234567.pdf"
    assert a.edition_number == "168"
    assert a.nome == "PORTARIA GM/MS Nº 1.234, DE 2 DE SETEMBRO DE 2026"


def test_filhos_do_body_viram_campos_do_artigo(zip_do1):
    artigos, _ = listar_artigos(zip_do1)
    a = _por_materia(artigos)["12345678"]
    assert a.identifica == "PORTARIA GM/MS Nº 1.234, DE 2 DE SETEMBRO DE 2026"
    assert a.ementa.startswith("Habilita leitos")
    assert a.titulo == "PORTARIA GM/MS Nº 1.234, DE 2 DE SETEMBRO DE 2026"


def test_filho_ausente_vira_string_vazia_nunca_none(zip_do1):
    """O ato do MEC não traz `Ementa` nem `Titulo`.

    Vazio e não `None` porque quem consome concatena e testa com `or`; um
    `None` aqui só apareceria como `TypeError` mais adiante.
    """
    artigos, _ = listar_artigos(zip_do1)
    a = _por_materia(artigos)["12345681"]
    assert a.ementa == ""
    assert a.titulo == ""
    assert a.identifica


def test_cdata_do_texto_chega_como_html(zip_do1):
    """O articulado vem em CDATA e precisa continuar sendo HTML, com as
    classes do portal — é delas que a extração de texto depende.
    """
    artigos, _ = listar_artigos(zip_do1)
    a = _por_materia(artigos)["12345678"]
    assert '<p class="identifica">' in a.texto_html
    assert '<p class="dou-paragraph">' in a.texto_html
    assert "R$ 1.234.567,89" in a.texto_html
    assert "Fundo Nacional de Saúde" in a.texto_html


def _com_membro_corrompido(bruto: bytes, alvo: str) -> bytes:
    original = zipfile.ZipFile(io.BytesIO(bruto))
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as novo:
        for nome in original.namelist():
            conteudo = b"<xml><article" if nome == alvo else original.read(nome)
            novo.writestr(nome, conteudo)
    return saida.getvalue()


def test_membro_ilegivel_vira_aviso_e_nao_derruba_os_demais(zip_do1):
    """Um XML quebrado no meio do zip não pode custar a edição inteira."""
    quebrado = _com_membro_corrompido(zip_do1, "2026090301234568.xml")
    artigos, avisos = listar_artigos(quebrado)
    assert len(artigos) == 3
    assert len(avisos) == 1
    assert avisos[0].startswith("2026090301234568.xml: XML ilegível (")
    assert "12345679" not in _por_materia(artigos)


def test_zip_invalido_levanta_valueerror():
    """Bytes que não são zip são falha de download, não edição sem matéria."""
    with pytest.raises(ValueError):
        listar_artigos(b"<html>login expirado</html>")


def test_membro_que_nao_e_xml_e_ignorado(zip_do1):
    """Zips do INLABS podem trazer manifestos; nada a avisar sobre eles."""
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as novo:
        original = zipfile.ZipFile(io.BytesIO(zip_do1))
        for nome in original.namelist():
            novo.writestr(nome, original.read(nome))
        novo.writestr("leia-me.txt", b"nao sou xml")
    artigos, avisos = listar_artigos(saida.getvalue())
    assert len(artigos) == 4
    assert avisos == []


def test_artigo_e_imutavel(zip_do1):
    from dataclasses import FrozenInstanceError

    artigo = listar_artigos(zip_do1)[0][0]
    with pytest.raises(FrozenInstanceError):
        artigo.id = "outro"
