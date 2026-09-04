"""Gera a fixture sintética `2026-09-03-DO1.zip`, no formato do INLABS.

Sintética de propósito: o zip real do INLABS exige login e traz dados de
pessoas. Aqui os nomes são fictícios e o conteúdo é só o suficiente para
exercitar o parse, a normalização e o filtro de escopo.

Uso: `python tests/fixtures/inlabs/gerar_fixture.py`
"""

from __future__ import annotations

import zipfile
from pathlib import Path

DESTINO = Path(__file__).parent / "2026-09-03-DO1.zip"

# Data fixa no ZipInfo: sem ela o zip muda a cada geração e o diff do
# arquivo binário versionado vira ruído.
_QUANDO = (2026, 9, 3, 6, 0, 0)


def _artigo(
    *,
    id_artigo: str,
    nome: str,
    art_type: str,
    art_category: str,
    number_page: str,
    id_materia: str,
    identifica: str,
    ementa: str | None,
    titulo: str | None,
    texto_html: str,
) -> str:
    corpo = [f"<Identifica><![CDATA[{identifica}]]></Identifica>"]
    corpo.append("<Data><![CDATA[03/09/2026]]></Data>")
    if ementa is not None:
        corpo.append(f"<Ementa><![CDATA[{ementa}]]></Ementa>")
    if titulo is not None:
        corpo.append(f"<Titulo><![CDATA[{titulo}]]></Titulo>")
    corpo.append("<SubTitulo/>")
    corpo.append(f"<Texto><![CDATA[{texto_html}]]></Texto>")
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<xml>"
        f'<article id="{id_artigo}" name="{nome}" idOficio="{id_artigo}" '
        f'pubName="DO1" artType="{art_type}" pubDate="03/09/2026" '
        f'artClass="00001:00001" artCategory="{art_category}" artSize="1234" '
        f'artNotes="" numberPage="{number_page}" '
        f'pdfPage="https://pdf.in.gov.br/pdf/2026/09/03/{id_artigo}.pdf" '
        'editionNumber="168" highlightType="" highlightPriority="" highlight="" '
        f'highlightimage="" highlightimagename="" idMateria="{id_materia}">'
        f"<body>{''.join(corpo)}</body>"
        "</article>"
        "</xml>"
    )


HABILITACAO = _artigo(
    id_artigo="1234567",
    nome="PORTARIA GM/MS Nº 1.234, DE 2 DE SETEMBRO DE 2026",
    art_type="Portaria",
    art_category="Ministério da Saúde/Gabinete do Ministro",
    number_page="45",
    id_materia="12345678",
    identifica="PORTARIA GM/MS Nº 1.234, DE 2 DE SETEMBRO DE 2026",
    ementa=(
        "Habilita leitos de Unidade de Terapia Intensiva Adulto Tipo II no "
        "Município de Manhuaçu (MG)."
    ),
    titulo="PORTARIA GM/MS Nº 1.234, DE 2 DE SETEMBRO DE 2026",
    texto_html=(
        '<p class="identifica">PORTARIA GM/MS Nº 1.234, DE 2 DE SETEMBRO DE 2026</p>'
        '<p class="ementa">Habilita leitos de Unidade de Terapia Intensiva Adulto '
        "Tipo II no Município de Manhuaçu (MG).</p>"
        '<p class="dou-paragraph">O MINISTRO DE ESTADO DA SAÚDE, no uso das '
        "atribuições que lhe conferem os incisos I e II do parágrafo único do art. "
        "87 da Constituição, resolve:</p>"
        '<p class="dou-paragraph">Art. 1º Ficam habilitados 10 (dez) leitos de '
        "Unidade de Terapia Intensiva Adulto Tipo II no Município de Manhuaçu "
        "(MG).</p>"
        '<p class="dou-paragraph">Art. 2º O impacto financeiro anual desta '
        "Portaria é de R$ 1.234.567,89 (um milhão, duzentos e trinta e quatro mil, "
        "quinhentos e sessenta e sete reais e oitenta e nove centavos), onerando o "
        "Fundo Nacional de Saúde.</p>"
        '<p class="assina">MINISTRO DE ESTADO DA SAÚDE</p>'
    ),
)

RDC = _artigo(
    id_artigo="1234568",
    nome="RESOLUÇÃO - RDC Nº 987, DE 1º DE SETEMBRO DE 2026",
    art_type="Resolução - RDC",
    art_category=(
        "Ministério da Saúde/Agência Nacional de Vigilância Sanitária/"
        "Diretoria Colegiada"
    ),
    number_page="52",
    id_materia="12345679",
    identifica="RESOLUÇÃO - RDC Nº 987, DE 1º DE SETEMBRO DE 2026",
    ementa=(
        "Dispõe sobre a rotulagem de medicamentos isentos de prescrição e dá "
        "outras providências."
    ),
    titulo="RESOLUÇÃO - RDC Nº 987, DE 1º DE SETEMBRO DE 2026",
    texto_html=(
        '<p class="identifica">RESOLUÇÃO - RDC Nº 987, DE 1º DE SETEMBRO DE 2026</p>'
        '<p class="ementa">Dispõe sobre a rotulagem de medicamentos isentos de '
        "prescrição e dá outras providências.</p>"
        '<p class="dou-paragraph">A Diretoria Colegiada da Agência Nacional de '
        "Vigilância Sanitária, no exercício das competências que lhe conferem o "
        "art. 15 da Lei nº 9.782, de 26 de janeiro de 1999, resolve:</p>"
        '<p class="dou-paragraph">Art. 1º Esta Resolução estabelece os requisitos '
        "mínimos de rotulagem.</p>"
        '<p class="assina">DIRETOR-PRESIDENTE</p>'
    ),
)

NOMEACAO = _artigo(
    id_artigo="1234569",
    nome="PORTARIA Nº 456, DE 2 DE SETEMBRO DE 2026",
    art_type="Portaria",
    art_category="Ministério da Saúde/Secretaria-Executiva",
    number_page="60",
    id_materia="12345680",
    identifica="PORTARIA Nº 456, DE 2 DE SETEMBRO DE 2026",
    ementa=None,
    titulo="PORTARIA Nº 456, DE 2 DE SETEMBRO DE 2026",
    texto_html=(
        '<p class="identifica">PORTARIA Nº 456, DE 2 DE SETEMBRO DE 2026</p>'
        '<p class="dou-paragraph">O SECRETÁRIO-EXECUTIVO DO MINISTÉRIO DA SAÚDE, '
        "no uso de suas atribuições, resolve:</p>"
        '<p class="dou-paragraph">Nomear FULANA DE TAL PEREIRA para exercer o '
        "cargo de Coordenadora-Geral de Planejamento.</p>"
        '<p class="assina">SECRETÁRIO-EXECUTIVO</p>'
    ),
)

FORA_DE_ESCOPO = _artigo(
    id_artigo="1234570",
    nome="PORTARIA MEC Nº 77, DE 2 DE SETEMBRO DE 2026",
    art_type="Portaria",
    art_category="Ministério da Educação/Gabinete do Ministro",
    number_page="70",
    id_materia="12345681",
    identifica="PORTARIA MEC Nº 77, DE 2 DE SETEMBRO DE 2026",
    ementa=None,
    titulo=None,
    texto_html=(
        '<p class="identifica">PORTARIA MEC Nº 77, DE 2 DE SETEMBRO DE 2026</p>'
        '<p class="dou-paragraph">O MINISTRO DE ESTADO DA EDUCAÇÃO resolve '
        "credenciar a instituição de ensino superior.</p>"
        '<p class="assina">MINISTRO DE ESTADO DA EDUCAÇÃO</p>'
    ),
)

MEMBROS = {
    "2026090301234567.xml": HABILITACAO,
    "2026090301234568.xml": RDC,
    "2026090301234569.xml": NOMEACAO,
    "2026090301234570.xml": FORA_DE_ESCOPO,
}


def gerar(destino: Path = DESTINO) -> Path:
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zip_saida:
        for nome, conteudo in MEMBROS.items():
            info = zipfile.ZipInfo(nome, date_time=_QUANDO)
            info.compress_type = zipfile.ZIP_DEFLATED
            zip_saida.writestr(info, conteudo.encode("utf-8"))
    return destino


if __name__ == "__main__":
    print(gerar())
