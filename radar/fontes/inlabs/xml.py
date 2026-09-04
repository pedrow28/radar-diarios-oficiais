"""Lê o zip de uma seção do INLABS: um XML por matéria publicada.

O zip é o artefato bruto do dia. Um membro ilegível vira aviso e a edição
segue: perder a edição inteira por causa de um XML quebrado transformaria um
defeito de uma matéria em silêncio sobre todas as outras.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass

# Atributo do `<article>` → campo do `Artigo`.
_ATRIBUTOS = {
    "id": "id",
    "nome": "name",
    "pub_name": "pubName",
    "art_type": "artType",
    "pub_date": "pubDate",
    "art_category": "artCategory",
    "number_page": "numberPage",
    "pdf_page": "pdfPage",
    "edition_number": "editionNumber",
    "id_materia": "idMateria",
}

# Filho de `<body>` → campo do `Artigo`. O conteúdo vem em CDATA; no caso do
# `Texto` isso é HTML e precisa continuar sendo, porque a extração de texto
# depende das classes de parágrafo do portal.
_FILHOS = {
    "identifica": "Identifica",
    "ementa": "Ementa",
    "titulo": "Titulo",
    "texto_html": "Texto",
}


@dataclass(frozen=True)
class Artigo:
    """Uma matéria como o INLABS a publica. Campo ausente é `""`, nunca `None`.

    Tudo string: aqui só se lê o XML. Converter página em inteiro ou seção em
    número é decisão de normalização, e fazê-la neste ponto esconderia o que a
    fonte de fato informou.
    """

    id: str
    nome: str
    pub_name: str
    art_type: str
    pub_date: str
    art_category: str
    number_page: str
    pdf_page: str
    edition_number: str
    id_materia: str
    identifica: str
    ementa: str
    titulo: str
    texto_html: str


def _artigo_de(conteudo: bytes) -> Artigo:
    raiz = ET.fromstring(conteudo)
    article = raiz if raiz.tag == "article" else raiz.find("article")
    if article is None:
        raise ET.ParseError("sem elemento <article>")

    campos = {campo: (article.get(attr) or "").strip() for campo, attr in _ATRIBUTOS.items()}
    body = article.find("body")
    for campo, tag in _FILHOS.items():
        achado = body.find(tag) if body is not None else None
        texto = achado.text if achado is not None and achado.text else ""
        # Só o articulado é HTML; nele o strip não pode encostar no conteúdo.
        campos[campo] = texto if campo == "texto_html" else texto.strip()
    return Artigo(**campos)


def listar_artigos(zip_bytes: bytes) -> tuple[list[Artigo], list[str]]:
    """Devolve os artigos do zip e os avisos dos membros que não puderam ser lidos.

    `ValueError` quando os bytes não são um zip: isso é falha de download
    (sessão expirada, página de erro no lugar do arquivo), não uma edição sem
    matérias, e confundir as duas seria relatar bloqueio como domingo.
    """
    try:
        arquivo = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"conteúdo não é um zip do INLABS: {exc}") from exc

    artigos: list[Artigo] = []
    avisos: list[str] = []
    # Ordem alfabética: a do zip depende de como o servidor o montou, e um
    # resultado que muda de ordem entre execuções é diff falso no JSON.
    for nome in sorted(arquivo.namelist()):
        if not nome.lower().endswith(".xml"):
            continue
        try:
            artigos.append(_artigo_de(arquivo.read(nome)))
        except (ET.ParseError, zipfile.BadZipFile, ValueError) as exc:
            avisos.append(f"{nome}: XML ilegível ({exc})")
    return artigos, avisos
