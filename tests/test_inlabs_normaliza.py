"""Artigo do INLABS → `Publicacao`, no mesmo contrato das outras fontes."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from radar.fontes.inlabs.normaliza import URL_PADRAO, normalizar
from radar.fontes.inlabs.xml import Artigo, listar_artigos

DIA = date(2026, 9, 3)
QUANDO = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)

_PADRAO = {
    "id": "1234567",
    "nome": "PORTARIA GM/MS Nº 1.234, DE 2 DE SETEMBRO DE 2026",
    "pub_name": "DO1",
    "art_type": "Portaria",
    "pub_date": "03/09/2026",
    "art_category": "Ministério da Saúde/Gabinete do Ministro",
    "number_page": "45",
    "pdf_page": "https://pdf.in.gov.br/pdf/2026/09/03/1234567.pdf",
    "edition_number": "168",
    "id_materia": "12345678",
    "identifica": "PORTARIA GM/MS Nº 1.234, DE 2 DE SETEMBRO DE 2026",
    "ementa": "Habilita leitos de UTI Adulto Tipo II no Município de Manhuaçu (MG).",
    "titulo": "PORTARIA GM/MS Nº 1.234, DE 2 DE SETEMBRO DE 2026",
    "texto_html": (
        '<p class="identifica">PORTARIA GM/MS Nº 1.234</p>'
        '<p class="ementa">Habilita leitos.</p>'
        '<p class="dou-paragraph">Art. 1º Ficam habilitados 10 leitos.</p>'
    ),
}


def artigo(**mudancas) -> Artigo:
    return Artigo(**{**_PADRAO, **mudancas})


@pytest.fixture
def artigos_da_fixture(dir_fixtures: Path) -> list[Artigo]:
    bruto = (dir_fixtures / "inlabs" / "2026-09-03-DO1.zip").read_bytes()
    return listar_artigos(bruto)[0]


def test_campos_basicos():
    pub = normalizar(artigo(), DIA, QUANDO)
    assert pub.fonte == "inlabs"
    assert pub.data_publicacao == DIA
    assert pub.coletado_em == QUANDO
    assert pub.tipo == "Portaria"
    assert pub.numero == "1.234"
    assert pub.pagina == 45
    assert pub.edicao == "168"
    assert pub.titulo == "PORTARIA GM/MS Nº 1.234, DE 2 DE SETEMBRO DE 2026"
    assert pub.url == "https://pdf.in.gov.br/pdf/2026/09/03/1234567.pdf"


def test_hierarquia_vira_orgao_e_unidade():
    pub = normalizar(artigo(), DIA, QUANDO)
    assert pub.orgao == "Ministério da Saúde"
    assert pub.unidade == "Gabinete do Ministro"


def test_hierarquia_de_um_nivel_deixa_unidade_none():
    pub = normalizar(artigo(art_category="Ministério da Saúde"), DIA, QUANDO)
    assert pub.orgao == "Ministério da Saúde"
    assert pub.unidade is None


def test_secao_vem_do_pubname():
    assert normalizar(artigo(pub_name="DO1"), DIA, QUANDO).secao == "1"
    assert normalizar(artigo(pub_name="DO2"), DIA, QUANDO).secao == "2"
    assert normalizar(artigo(pub_name="DO3"), DIA, QUANDO).secao == "3"


def test_edicao_extra_e_a_secao_da_base_e_fica_marcada():
    """`DO1E` é a edição extra da Seção 1: mesma seção, procedência diferente."""
    pub = normalizar(artigo(pub_name="DO1E"), DIA, QUANDO)
    assert pub.secao == "1"
    assert pub.origem["extra"] is True


def test_edicao_comum_nao_e_marcada_como_extra():
    assert "extra" not in normalizar(artigo(), DIA, QUANDO).origem


def test_pubname_desconhecido_nao_vira_secao_inventada():
    """Seção errada é pior que seção ausente: o agente cita a errada."""
    pub = normalizar(artigo(pub_name="DOX"), DIA, QUANDO)
    assert pub.secao is None


def test_pagina_ilegivel_vira_none():
    assert normalizar(artigo(number_page=""), DIA, QUANDO).pagina is None


def test_edicao_ausente_vira_none():
    assert normalizar(artigo(edition_number=""), DIA, QUANDO).edicao is None


def test_titulo_cai_no_name_quando_nao_ha_identifica():
    pub = normalizar(artigo(identifica="", nome="ATO SEM IDENTIFICA"), DIA, QUANDO)
    assert pub.titulo == "ATO SEM IDENTIFICA"


def test_numero_sai_do_titulo_quando_nao_ha_identifica():
    pub = normalizar(
        artigo(identifica="", titulo="PORTARIA Nº 99, DE 2 DE SETEMBRO DE 2026"),
        DIA, QUANDO,
    )
    assert pub.numero == "99"


def test_texto_vem_do_html_do_articulado():
    pub = normalizar(artigo(), DIA, QUANDO)
    assert "Art. 1º Ficam habilitados 10 leitos." in pub.texto
    assert "<p" not in pub.texto
    assert pub.origem["texto_integral"] is True


def test_ementa_do_xml_prevalece_sobre_a_extraida():
    """A `Ementa` é campo declarado pela fonte; a extraída é inferência."""
    pub = normalizar(artigo(), DIA, QUANDO)
    assert pub.ementa == "Habilita leitos de UTI Adulto Tipo II no Município de Manhuaçu (MG)."


def test_sem_ementa_no_xml_usa_o_paragrafo_de_ementa_do_articulado():
    pub = normalizar(artigo(ementa=""), DIA, QUANDO)
    assert pub.ementa == "Habilita leitos."


def test_sem_ementa_em_lugar_nenhum_fica_none():
    pub = normalizar(
        artigo(ementa="", texto_html='<p class="dou-paragraph">Só articulado.</p>'),
        DIA, QUANDO,
    )
    assert pub.ementa is None


def test_html_sem_as_classes_do_portal_ainda_produz_texto():
    """Sem o fallback, um articulado fora do padrão sairia com texto vazio."""
    pub = normalizar(
        artigo(texto_html="<p>Parágrafo   sem    classe</p><br/>segunda linha"),
        DIA, QUANDO,
    )
    assert pub.texto == "Parágrafo sem classe segunda linha"


def test_sem_pdfpage_a_url_cai_no_portal_e_fica_marcada():
    """URL inventada seria pior: o agente cita um link que não existe."""
    pub = normalizar(artigo(pdf_page=""), DIA, QUANDO)
    assert pub.url == URL_PADRAO == "https://inlabs.in.gov.br/"
    assert pub.origem["url_fallback"] is True


def test_url_presente_nao_marca_fallback():
    assert "url_fallback" not in normalizar(artigo(), DIA, QUANDO).origem


def test_origem_registra_a_procedencia():
    origem = normalizar(artigo(), DIA, QUANDO).origem
    assert origem["metodo"] == "inlabs"
    assert origem["id_materia"] == "12345678"
    assert origem["art_category"] == "Ministério da Saúde/Gabinete do Ministro"
    assert origem["pub_name"] == "DO1"


def test_id_e_estavel_entre_chamadas():
    """Reprocessar o dia precisa fazer UPSERT, não duplicar."""
    assert normalizar(artigo(), DIA, QUANDO).id == normalizar(artigo(), DIA, QUANDO).id


def test_id_muda_quando_a_publicacao_muda():
    a = normalizar(artigo(), DIA, QUANDO)
    b = normalizar(artigo(pdf_page="https://pdf.in.gov.br/pdf/2026/09/03/999.pdf"), DIA, QUANDO)
    assert a.id != b.id


# ── a ANVISA aparece nos dois formatos de hierarquia ────────────────────────


def test_anvisa_sob_o_ministerio_da_saude(artigos_da_fixture):
    """Forma da fixture: `Ministério da Saúde/Agência Nacional.../Diretoria...`."""
    rdc = next(a for a in artigos_da_fixture if a.id_materia == "12345679")
    pub = normalizar(rdc, DIA, QUANDO)
    assert pub.orgao == "Ministério da Saúde"
    assert pub.unidade == "Agência Nacional de Vigilância Sanitária"
    assert "Diretoria Colegiada" in pub.origem["art_category"]


def test_anvisa_como_orgao_de_primeiro_nivel():
    """O INLABS também publica a ANVISA como 1º nível; a hierarquia inteira
    fica em `origem`, senão o 3º nível se perde nos dois casos.
    """
    pub = normalizar(
        artigo(
            art_category="Agência Nacional de Vigilância Sanitária/Diretoria Colegiada",
            art_type="Resolução - RDC",
        ),
        DIA, QUANDO,
    )
    assert pub.orgao == "Agência Nacional de Vigilância Sanitária"
    assert pub.unidade == "Diretoria Colegiada"
    assert pub.tipo == "Resolução - RDC"
