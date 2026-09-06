"""Gera as fixtures do `boletim`: JSONs normalizados e respostas de LLM.

Sintéticas de propósito: o boletim lê a saída do `radar`, e a saída real traz
nome de pessoa e texto integral de diário. Aqui o conteúdo é fictício e só
grande o bastante para exercitar carga, prefiltro, prompts e classificação.

Os ids não são escritos à mão: saem de `gerar_id`, o mesmo que o `radar` usa.
Por isso as fixtures de resposta do LLM também nascem daqui — elas precisam
citar exatamente os ids das publicações mantidas.

Uso: `python tests/fixtures/boletim/gerar_fixtures.py`
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from radar.core.modelos import SCHEMA_VERSAO, gerar_id

BASE = Path(__file__).parent
COLETADO_EM = "2026-09-03T09:00:00Z"
DATA = date(2026, 9, 3)
DATA_VAZIA = date(2026, 9, 6)


def _pub(
    *,
    fonte: str,
    orgao: str,
    unidade: str | None,
    secao: str | None,
    pagina: int | None,
    edicao: str | None,
    tipo: str | None,
    numero: str | None,
    titulo: str,
    ementa: str | None,
    texto: str,
    url: str,
    origem: dict,
) -> dict:
    return {
        "id": gerar_id(fonte, DATA, url, titulo),
        "fonte": fonte,
        "data_publicacao": DATA.isoformat(),
        "coletado_em": COLETADO_EM,
        "orgao": orgao,
        "unidade": unidade,
        "secao": secao,
        "pagina": pagina,
        "edicao": edicao,
        "tipo": tipo,
        "numero": numero,
        "titulo": titulo,
        "ementa": ementa,
        "texto": texto,
        "url": url,
        "origem": origem,
    }


def _inlabs(**kw) -> dict:
    numero = kw.pop("numero")
    pagina = kw.pop("pagina")
    return _pub(
        fonte="inlabs",
        secao=kw.pop("secao", "1"),
        pagina=pagina,
        edicao="169",
        numero=numero,
        origem={
            "metodo": "inlabs",
            "id_materia": f"9000{pagina}",
            "art_category": kw.pop("categoria"),
            "pub_name": "DO1",
            "texto_integral": True,
        },
        **kw,
    )


def _iofmg(**kw) -> dict:
    pagina = kw.pop("pagina")
    return _pub(
        fonte="iofmg",
        secao=None,
        pagina=pagina,
        edicao="2026-09-03",
        origem={"metodo": "iofmg", "caderno": "Executivo", "pagina_pdf": pagina},
        **kw,
    )


# ── INLABS: 8 publicações, 4 mantidas e 4 descartadas ───────────────────
PUBS_INLABS = [
    _inlabs(
        orgao="Ministério da Saúde",
        unidade="Gabinete do Ministro",
        categoria="Ministério da Saúde/Gabinete do Ministro",
        pagina=41,
        tipo="Portaria",
        numero="3.412",
        titulo="PORTARIA GM/MS Nº 3.412, DE 2 DE SETEMBRO DE 2026",
        ementa=(
            "Habilita leitos de unidade de terapia intensiva adulto tipo II no "
            "Município de Manhuaçu e destina R$ 1.234.567,89 ao respectivo fundo "
            "municipal de saúde."
        ),
        texto=(
            "O Ministro de Estado da Saúde resolve habilitar dez leitos de unidade de "
            "terapia intensiva adulto tipo II sob gestão do Município de Manhuaçu, "
            "com efeitos a partir da competência setembro de 2026. Fica destinado o "
            "montante anual de R$ 1.234.567,89, na modalidade fundo a fundo, ao custeio "
            "dos leitos ora habilitados. Os recursos correrão à conta do orçamento do "
            "Fundo Nacional de Saúde e serão transferidos em parcelas mensais, "
            "condicionados ao registro dos leitos no cadastro nacional."
        ),
        url="https://pdf.in.gov.br/pdf/2026/09/03/90041.pdf",
    ),
    _inlabs(
        orgao="Ministério da Saúde",
        unidade="Secretaria de Atenção Primária à Saúde",
        categoria="Ministério da Saúde/Secretaria de Atenção Primária à Saúde",
        pagina=44,
        tipo="Portaria",
        numero="3.418",
        titulo="PORTARIA SAPS/MS Nº 3.418, DE 2 DE SETEMBRO DE 2026",
        ementa=(
            "Altera o critério de cálculo do piso da atenção primária para os "
            "municípios com menos de trinta mil habitantes."
        ),
        texto=(
            "A Secretaria de Atenção Primária à Saúde resolve alterar o critério de "
            "cálculo do componente de capitação ponderada que compõe o piso da atenção "
            "primária. Passa a ser considerada a população estimada mais recente "
            "divulgada pelo instituto oficial de estatística, e não mais a do censo "
            "anterior. A nova regra vale para os municípios com menos de trinta mil "
            "habitantes e produz efeitos a partir da competência outubro de 2026."
        ),
        url="https://pdf.in.gov.br/pdf/2026/09/03/90044.pdf",
    ),
    _inlabs(
        orgao="Ministério da Saúde",
        unidade="Agência Nacional de Vigilância Sanitária",
        categoria="Ministério da Saúde/Agência Nacional de Vigilância Sanitária/"
        "Diretoria Colegiada",
        pagina=58,
        tipo="Resolução",
        numero="942",
        titulo="RESOLUÇÃO DE DIRETORIA COLEGIADA - RDC Nº 942, DE 1º DE SETEMBRO DE 2026",
        ementa=(
            "Dispõe sobre os requisitos sanitários mínimos para o funcionamento dos "
            "serviços de terapia renal substitutiva."
        ),
        texto=(
            "A Diretoria Colegiada da Agência Nacional de Vigilância Sanitária adota a "
            "presente resolução, que estabelece os requisitos sanitários mínimos para o "
            "funcionamento dos serviços de terapia renal substitutiva. Os serviços já em "
            "atividade têm o prazo de dezoito meses para se adequar às exigências de "
            "tratamento da água e de registro de intercorrências. A fiscalização cabe "
            "aos órgãos de vigilância sanitária estaduais e municipais."
        ),
        url="https://pdf.in.gov.br/pdf/2026/09/03/90058.pdf",
    ),
    _inlabs(
        orgao="Ministério da Saúde",
        unidade="Secretaria de Atenção Especializada à Saúde",
        categoria="Ministério da Saúde/Secretaria de Atenção Especializada à Saúde",
        pagina=63,
        tipo="Edital",
        numero="12",
        titulo="EDITAL DE CHAMAMENTO PÚBLICO Nº 12/2026",
        ementa=(
            "Torna público o chamamento para seleção de hospitais filantrópicos "
            "interessados em aderir ao programa de fortalecimento da média "
            "complexidade."
        ),
        texto=(
            "A Secretaria de Atenção Especializada à Saúde torna público o chamamento "
            "para seleção de hospitais filantrópicos e Santa Casa de Misericórdia "
            "interessados em aderir ao programa de fortalecimento da média "
            "complexidade. As propostas serão recebidas por meio de sistema eletrônico "
            "durante trinta dias corridos contados da publicação. Serão priorizadas as "
            "instituições situadas em regiões de saúde com vazio assistencial "
            "reconhecido pela comissão intergestores bipartite."
        ),
        url="https://pdf.in.gov.br/pdf/2026/09/03/90063.pdf",
    ),
    _inlabs(
        orgao="Ministério da Saúde",
        unidade="Secretaria-Executiva",
        categoria="Ministério da Saúde/Secretaria-Executiva",
        pagina=70,
        tipo="Portaria",
        numero="1.907",
        titulo="PORTARIA SE/MS Nº 1.907, DE 2 DE SETEMBRO DE 2026",
        ementa=(
            "Nomeação de servidor para o cargo em comissão de assistente técnico "
            "do departamento de gestão interna."
        ),
        texto=(
            "O Secretário-Executivo, no uso de suas atribuições, resolve nomear o "
            "servidor ocupante da matrícula de número trinta e um mil para exercer o "
            "cargo em comissão de assistente técnico do departamento de gestão interna. "
            "A nomeação produz efeitos a contar da data de publicação e não implica "
            "alteração da lotação de origem."
        ),
        url="https://pdf.in.gov.br/pdf/2026/09/03/90070.pdf",
    ),
    _inlabs(
        orgao="Ministério da Saúde",
        unidade="Secretaria-Executiva",
        categoria="Ministério da Saúde/Secretaria-Executiva",
        pagina=71,
        tipo="Portaria",
        numero="1.908",
        titulo="PORTARIA SE/MS Nº 1.908, DE 2 DE SETEMBRO DE 2026",
        ementa=(
            "Exonera, a pedido, ocupante de cargo em comissão do departamento de "
            "logística."
        ),
        texto=(
            "O Secretário-Executivo resolve exonerar, a pedido, a ocupante do cargo em "
            "comissão de chefe de divisão do departamento de logística, com efeitos a "
            "contar de 1º de setembro de 2026. O cargo fica vago até novo provimento, e "
            "as atribuições passam interinamente ao substituto legal já indicado no "
            "regimento interno da unidade."
        ),
        url="https://pdf.in.gov.br/pdf/2026/09/03/90071.pdf",
    ),
    _inlabs(
        orgao="Ministério da Saúde",
        unidade="Departamento de Logística em Saúde",
        categoria="Ministério da Saúde/Departamento de Logística em Saúde",
        pagina=88,
        tipo="Extrato",
        numero="88",
        titulo="EXTRATO DE CONTRATO Nº 88/2026",
        ementa=(
            "Contratante: departamento de logística em saúde. Objeto: fornecimento de "
            "licenças de software de escritório. Vigência: doze meses."
        ),
        texto=(
            "Espécie: contrato administrativo. Objeto: fornecimento de licenças de "
            "software de escritório para as unidades administrativas do departamento. "
            "Vigência: doze meses, contados da assinatura, prorrogável na forma da lei. "
            "Valor: conforme a cláusula quinta do instrumento. Fundamento legal: lei de "
            "licitações e contratos administrativos. Signatários: o diretor do "
            "departamento e o representante legal da contratada."
        ),
        url="https://pdf.in.gov.br/pdf/2026/09/03/90088.pdf",
    ),
    _inlabs(
        orgao="Ministério da Saúde",
        unidade="Departamento de Logística em Saúde",
        categoria="Ministério da Saúde/Departamento de Logística em Saúde",
        pagina=89,
        tipo="Ata",
        numero="45",
        titulo="ATA DE REGISTRO DE PREÇOS Nº 45/2026",
        ementa=(
            "Registro de preços para aquisição de material de expediente, com validade "
            "de doze meses."
        ),
        texto=(
            "Fica registrado o preço para eventual aquisição de material de expediente "
            "destinado às unidades administrativas, com validade de doze meses contados "
            "da publicação. O registro não obriga a administração a contratar, sendo "
            "facultada a realização de procedimento próprio para a mesma finalidade. Os "
            "quantitativos estimados constam do anexo único, disponível no sistema "
            "eletrônico oficial."
        ),
        url="https://pdf.in.gov.br/pdf/2026/09/03/90089.pdf",
    ),
]

# ── IOF-MG: 4 publicações, 3 mantidas e 1 descartada ────────────────────
PUBS_IOFMG = [
    _iofmg(
        orgao="Secretaria de Estado de Saúde",
        unidade="Comissão Intergestores Bipartite",
        pagina=12,
        tipo="Deliberação",
        numero="4.512",
        titulo="DELIBERAÇÃO CIB-SUS/MG Nº 4.512, DE 1º DE SETEMBRO DE 2026",
        ementa=(
            "Amplia em R$ 28.100.000,00 o teto MAC do Hospital César Leite, em "
            "Manhuaçu, para custeio da média e alta complexidade."
        ),
        texto=(
            "A Comissão Intergestores Bipartite do SUS de Minas Gerais delibera pela "
            "ampliação de R$ 28.100.000,00 no teto MAC destinado ao Hospital César "
            "Leite, referência regional em oncologia e em cirurgia de alta "
            "complexidade. O incremento tem caráter permanente e será repassado fundo a "
            "fundo, em parcelas mensais, ao Município de Manhuaçu, gestor pleno da "
            "assistência. A programação assistencial da região deverá ser revista em "
            "até noventa dias."
        ),
        url="https://www.jornalminasgerais.mg.gov.br/edicao/2026-09-03/p12",
    ),
    _iofmg(
        orgao="Secretaria de Estado de Saúde",
        unidade="Gabinete",
        pagina=13,
        tipo="Resolução",
        numero="9.120",
        titulo="RESOLUÇÃO SES Nº 9.120, DE 1º DE SETEMBRO DE 2026",
        ementa=(
            "Altera o prazo de envio da prestação de contas dos incentivos estaduais da "
            "atenção primária pelos municípios."
        ),
        texto=(
            "A Secretária de Estado de Saúde resolve alterar o prazo de envio da "
            "prestação de contas dos incentivos estaduais da atenção primária, que "
            "passa do décimo para o vigésimo dia útil do mês subsequente ao trimestre "
            "encerrado. A mudança atende pedido dos gestores municipais e vale já para "
            "o terceiro trimestre de 2026. Permanecem inalterados os documentos "
            "exigidos e a forma de envio pelo sistema estadual."
        ),
        url="https://www.jornalminasgerais.mg.gov.br/edicao/2026-09-03/p13",
    ),
    _iofmg(
        orgao="Secretaria de Estado de Saúde",
        unidade="Superintendência Regional de Saúde",
        pagina=19,
        tipo="Ato",
        numero="512",
        titulo="ATO Nº 512/2026",
        ementa=(
            "Concede férias regulamentares a servidores da superintendência regional de "
            "saúde, referentes ao exercício de 2026."
        ),
        texto=(
            "O superintendente regional de saúde concede férias regulamentares aos "
            "servidores relacionados no anexo, referentes ao exercício de 2026, a serem "
            "usufruídas no período indicado para cada matrícula. As chefias imediatas "
            "ficam responsáveis por organizar a escala de forma a não interromper o "
            "atendimento nas unidades da regional."
        ),
        url="https://www.jornalminasgerais.mg.gov.br/edicao/2026-09-03/p19",
    ),
    _iofmg(
        orgao="Fundação Hospitalar do Estado de Minas Gerais",
        unidade="Presidência",
        pagina=27,
        tipo="Portaria",
        numero="218",
        titulo="PORTARIA PRE Nº 218, DE 1º DE SETEMBRO DE 2026",
        ementa=(
            "Institui grupo de trabalho para revisar o fluxo do prontuário eletrônico "
            "nas unidades assistenciais da Fundação."
        ),
        texto=(
            "A presidência da Fundação Hospitalar do Estado de Minas Gerais institui "
            "grupo de trabalho com a finalidade de revisar o fluxo do prontuário "
            "eletrônico nas unidades assistenciais, com foco na integração entre "
            "ambulatório e internação. O grupo terá noventa dias para apresentar "
            "relatório com proposta de padronização e cronograma de implantação, e "
            "reunir-se-á quinzenalmente."
        ),
        url="https://www.jornalminasgerais.mg.gov.br/edicao/2026-09-03/p27",
    ),
]


# ── respostas de LLM, nos ids que o prefiltro mantém ────────────────────
def _id(titulo: str) -> str:
    """Id da publicação da fixture pelo título, para não repetir hash à mão."""
    for pub in (*PUBS_INLABS, *PUBS_IOFMG):
        if pub["titulo"].startswith(titulo):
            return pub["id"]
    raise KeyError(titulo)


def lote1() -> dict:
    """Classificação dos 7 itens que sobrevivem ao prefiltro no dia 03/09."""
    return {
        "itens": [
            {
                "id": _id("PORTARIA GM/MS Nº 3.412"),
                "categoria": "A",
                "relevancia": 3,
                "resumo": (
                    "Portaria GM/MS nº 3.412, de 2 de setembro de 2026, habilita dez "
                    "leitos de UTI adulto tipo II em Manhuaçu."
                ),
                "por_que_importa": (
                    "Abre R$ 1.234.567,89 por ano de custeio fundo a fundo para o "
                    "município."
                ),
                "valor_brl": 1234567.89,
                "entes": ["Município de Manhuaçu"],
                "tags": ["habilitação", "uti", "custeio"],
            },
            {
                "id": _id("PORTARIA SAPS/MS Nº 3.418"),
                "categoria": "B",
                "relevancia": 2,
                "resumo": (
                    "Portaria SAPS/MS nº 3.418, de 2 de setembro de 2026, muda o "
                    "critério de cálculo do piso da atenção primária."
                ),
                "por_que_importa": (
                    "Municípios com menos de 30 mil habitantes recalculam a receita "
                    "da atenção primária a partir de outubro."
                ),
                "valor_brl": None,
                "entes": [],
                "tags": ["atenção primária", "piso"],
            },
            {
                "id": _id("RESOLUÇÃO DE DIRETORIA COLEGIADA - RDC Nº 942"),
                "categoria": "B",
                "relevancia": 2,
                "resumo": (
                    "RDC nº 942, de 1º de setembro de 2026, fixa requisitos "
                    "sanitários para serviços de terapia renal substitutiva."
                ),
                "por_que_importa": (
                    "Serviços de diálise já em operação têm 18 meses para se adequar."
                ),
                "valor_brl": None,
                "entes": [],
                "tags": ["anvisa", "diálise"],
            },
            {
                "id": _id("EDITAL DE CHAMAMENTO PÚBLICO Nº 12/2026"),
                "categoria": "C",
                "relevancia": 2,
                "resumo": (
                    "Edital de chamamento público nº 12/2026 seleciona hospitais "
                    "filantrópicos para o programa de média complexidade."
                ),
                "por_que_importa": (
                    "Prazo de 30 dias para inscrever a instituição, com prioridade "
                    "para regiões com vazio assistencial."
                ),
                "valor_brl": None,
                "entes": ["Santa Casa de Misericórdia"],
                "tags": ["chamamento", "filantrópicos"],
            },
            {
                "id": _id("DELIBERAÇÃO CIB-SUS/MG Nº 4.512"),
                "categoria": "A",
                "relevancia": 3,
                "resumo": (
                    "Deliberação CIB-SUS/MG nº 4.512, de 1º de setembro de 2026, "
                    "amplia o teto MAC do Hospital César Leite."
                ),
                "por_que_importa": (
                    "São R$ 28.100.000,00 permanentes de média e alta complexidade "
                    "para a regional de Manhuaçu."
                ),
                "valor_brl": 28100000.0,
                "entes": ["Hospital César Leite", "Município de Manhuaçu"],
                "tags": ["teto mac", "cib", "oncologia"],
            },
            {
                "id": _id("RESOLUÇÃO SES Nº 9.120"),
                "categoria": "B",
                "relevancia": 3,
                "resumo": (
                    "Resolução SES nº 9.120, de 1º de setembro de 2026, adia o prazo "
                    "de prestação de contas dos incentivos estaduais."
                ),
                "por_que_importa": (
                    "O envio passa do 10º para o 20º dia útil, já no terceiro "
                    "trimestre de 2026."
                ),
                "valor_brl": None,
                "entes": [],
                "tags": ["prestação de contas", "minas gerais"],
            },
            {
                "id": _id("PORTARIA PRE Nº 218"),
                "categoria": "D",
                "relevancia": 1,
                "resumo": (
                    "Portaria PRE nº 218, de 1º de setembro de 2026, institui grupo "
                    "de trabalho sobre prontuário eletrônico na Fhemig."
                ),
                "por_que_importa": None,
                "valor_brl": None,
                "entes": ["Fundação Hospitalar"],
                "tags": ["fhemig", "prontuário"],
            },
        ]
    }


def editorial() -> dict:
    return {
        "titulo": "3 habilitações e 1 teto MAC ampliado em MG",
        "em_30_segundos": [
            "O Ministério da Saúde habilitou 10 leitos de UTI adulto em Manhuaçu, "
            "com R$ 1.234.567,89 de custeio anual.",
            "A CIB-SUS/MG ampliou em R$ 28.100.000,00 o teto MAC do Hospital "
            "César Leite.",
            "A portaria SAPS/MS nº 3.418 mudou o critério do piso da atenção "
            "primária para municípios de até 30 mil habitantes.",
            "O edital de chamamento nº 12/2026 abre 30 dias de inscrição para "
            "hospitais filantrópicos.",
        ],
        "intro": (
            "O dia trouxe 2 atos que movimentam recurso direto para Minas Gerais e "
            "3 que mudam regra de financiamento. Vale conferir prazo de adesão e "
            "competência de início em cada um."
        ),
    }


def _normalizado(
    fonte: str, data: date, status: str, escopo: dict, avisos: list[str], pubs: list[dict]
) -> dict:
    return {
        "schema_versao": SCHEMA_VERSAO,
        "fonte": fonte,
        "data_publicacao": data.isoformat(),
        "coletado_em": COLETADO_EM,
        "status": status,
        "escopo": escopo,
        "total": len(pubs),
        "avisos": avisos,
        "publicacoes": pubs,
    }


def _escrever(caminho: Path, conteudo: dict) -> None:
    # `newline` explícito: `tests/fixtures/**` é `-text` no .gitattributes, então
    # o CRLF que o Windows colocaria aqui seria versionado, e gerar a fixture de
    # novo no Linux mudaria o arquivo inteiro.
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(conteudo, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def gerar() -> None:
    dia = BASE / "normalized" / DATA.isoformat()
    _escrever(
        dia / "inlabs.json",
        _normalizado(
            "inlabs",
            DATA,
            "ok",
            {"secoes": ["DO1"], "orgaos": ["Ministério da Saúde"]},
            [],
            PUBS_INLABS,
        ),
    )
    _escrever(
        dia / "iofmg.json",
        _normalizado(
            "iofmg",
            DATA,
            "parcial",
            {"cadernos": ["Executivo"]},
            ["página 31 do caderno não pôde ser extraída"],
            PUBS_IOFMG,
        ),
    )
    _escrever(
        BASE / "normalized" / DATA_VAZIA.isoformat() / "iofmg.json",
        _normalizado("iofmg", DATA_VAZIA, "vazio", {"cadernos": ["Executivo"]}, [], []),
    )
    _escrever(BASE / "llm" / "lote1.json", lote1())
    _escrever(BASE / "llm" / "editorial.json", editorial())


if __name__ == "__main__":
    gerar()
    print(f"fixtures gravadas em {BASE}")
