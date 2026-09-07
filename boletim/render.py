"""Renderização da edição: e-mail HTML, página do site, markdown e índice.

O e-mail é o único artefato do projeto que um humano lê sem intermediário, e o
meio é hostil: Outlook não entende `max-width`, Gmail reescreve cor, metade da
base bloqueia imagem. Por isso a estrutura vive nos templates (tabela, coluna
única, estilo inline) e aqui ficam só o ambiente Jinja, os filtros de formato e
o contexto - o que muda quando o mesmo template vira e-mail ou página.

Autoescape ligado para HTML e desligado para markdown: o texto que chega vem do
diário oficial e do LLM, e nenhum dos dois é confiável o bastante para entrar
cru numa página. Nada de `|safe` nos templates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from datetime import date
from typing import Any, Literal, Sequence

from jinja2 import Environment, PackageLoader, StrictUndefined

from boletim.config import ConfigBoletim
from boletim.edicao import ROTULOS, Edicao, FonteResumo, Item, sem_travessao
from radar.core.datas import hoje

Modo = Literal["email", "web"]

MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)

# O leitor não reconhece "inlabs": reconhece o diário de onde o ato saiu.
NOMES_FONTE = {
    "inlabs": "DOU via INLABS",
    "iofmg": "Diário Oficial de Minas Gerais",
    "dou": "DOU",
}

# Na citação de um ato o leitor precisa do nome do diário, não do coletor:
# "DOU nº 169, seção 1" e não "DOU via INLABS nº 169, seção 1".
DIARIOS = {
    "inlabs": "DOU",
    "dou": "DOU",
    "iofmg": "Diário Oficial de Minas Gerais",
}

# Contagem do índice em frase, com singular e plural. A versão anterior era
# uma tira de middle dots que ainda imprimia "1 editais".
NOMES_CONTAGEM = {
    "A": ("ato de captação", "atos de captação"),
    "B": ("mudança de regra", "mudanças de regra"),
    "C": ("edital", "editais"),
}
SEM_RELEVANTES_CURTO = "Sem publicações relevantes"

SEM_CONTEUDO = ("ausente", "vazio")
MAX_AVISOS = 3

# Lista fechada de esquemas que podem virar href. Ver `url_segura`.
ESQUEMAS_SEGUROS = ("https://", "http://")
# O que quebraria o destino de um link markdown, que fecha no primeiro `)`.
_ESCAPE_MARKDOWN = {" ": "%20", "(": "%28", ")": "%29", "<": "%3C", ">": "%3E"}

_TELEFONE_BR = re.compile(r"^55(\d{2})(\d{5})(\d{4})$")
_EDICAO_NUMERO = re.compile(r"^\d+$")


def brl(valor: float) -> str:
    """`1234567.89` em `"R$ 1.234.567,89"`, sem depender de locale."""
    inteiro, centavos = f"{valor:.2f}".split(".")
    grupos = f"{int(inteiro):,}".replace(",", ".")
    return f"R$ {grupos},{centavos}"


def data_br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def data_extenso(d: date) -> str:
    """`"3 de setembro de 2026"`. Sem locale: a VPS não tem pt_BR instalado."""
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def telefone_legivel(numero: str) -> str:
    """`"5531984483183"` em `"(31) 98448-3183"`; outro formato sai como veio.

    O número por extenso existe para o leitor que prefere digitar a clicar, e
    uma máscara inventada em cima de um número fora do padrão seria pior que
    nenhuma.
    """
    achado = _TELEFONE_BR.match(numero)
    if not achado:
        return numero
    ddd, prefixo, sufixo = achado.groups()
    return f"({ddd}) {prefixo}-{sufixo}"


def url_segura(url: str) -> str:
    """A URL do ato, ou `""` quando o esquema não é `http`/`https`.

    `item.url` vem do diário - `pdfPage` do XML do INLABS, URL montada no
    IOF-MG - e termina em href de página pública e de e-mail. O autoescape do
    Jinja impede a fuga do atributo, mas não impede um `javascript:` ou um
    `data:` de virar link legítimo. A lista de esquemas é fechada de propósito:
    `mailto:`, `file:` e `//` relativo a protocolo também não têm o que fazer
    num link de publicação.

    Devolver vazio, e não uma URL de reserva, é deliberado: o template mostra o
    ato sem link, e ninguém é levado a lugar nenhum sem saber para onde.
    """
    limpa = (url or "").strip()
    return limpa if limpa.lower().startswith(ESQUEMAS_SEGUROS) else ""


def url_markdown(url: str) -> str:
    """A mesma URL, pronta para o destino de um link markdown.

    O markdown fecha o destino no primeiro `)` e não sobrevive a espaço no
    meio; um dos dois vindo do diário partiria o link e jogaria o resto da URL
    no texto. Percent-encoding resolve sem tocar no que já é válido.
    """
    return "".join(_ESCAPE_MARKDOWN.get(letra, letra) for letra in url_segura(url))


def nome_fonte(nome: str) -> str:
    return NOMES_FONTE.get(nome, nome)


def meta_orgao(item: Item) -> str:
    """Primeira linha da meta: quem publicou o ato.

    A linha de meta era uma tira única de campos unidos por middle dot, que é
    assinatura de página gerada e, pior, dava o mesmo peso a "Ministério da
    Saúde" e a "p. 41". Agora são duas linhas com hierarquia: quem publicou
    primeiro, porque é o que o gestor reconhece, e onde saiu depois.
    """
    return ", ".join(parte for parte in (item.orgao, item.unidade) if parte)


def meta_origem(item: Item) -> str:
    """Segunda linha da meta: onde o ato saiu, em forma de citação.

    O número da edição só entra quando é número: no IOF-MG o campo guarda a
    própria data, e "nº 2026-09-03" seria ruído em cima da data que já fecha
    a linha. O tipo e o número do ato não aparecem aqui porque `titulo_ato`
    já os carrega no título.
    """
    diario = DIARIOS.get(item.fonte, item.fonte)
    if item.edicao and _EDICAO_NUMERO.match(item.edicao):
        diario = f"{diario} nº {item.edicao}"
    partes = [diario]
    if item.secao:
        partes.append(f"seção {item.secao}")
    if item.pagina:
        partes.append(f"página {item.pagina}")
    # `secao` e `pagina` chegam do diário, que copia travessão de PDF.
    return sem_travessao(f"{', '.join(partes)}, de {data_br(item.data_publicacao)}")


def resumo_edicao(contagens: dict[str, int], parcial: bool = False) -> str:
    """O que a edição trouxe, em uma frase, para a entrada do índice."""
    partes = [
        f"{contagens.get(cat, 0)} {singular if contagens.get(cat, 0) == 1 else plural}"
        for cat, (singular, plural) in NOMES_CONTAGEM.items()
        if contagens.get(cat, 0)
    ]
    if not partes:
        frase = SEM_RELEVANTES_CURTO
    elif len(partes) == 1:
        frase = partes[0]
    else:
        frase = f"{', '.join(partes[:-1])} e {partes[-1]}"
    return f"{frase}. Coleta parcial." if parcial else f"{frase}."


def fontes_publicadas(fontes: Sequence[FonteResumo]) -> list[FonteResumo]:
    """As fontes que entraram na edição, excluindo as que não coletaram nada.

    Única dona da regra de "sem conteúdo": e-mail e markdown citavam a mesma
    lista de status como literal repetido, e um dos dois ficaria desatualizado
    no dia em que um terceiro status se juntasse a `ausente`/`vazio`.
    """
    return [fonte for fonte in fontes if fonte.status not in SEM_CONTEUDO]


def avisos_fontes(fontes: Sequence[FonteResumo], limite: int = MAX_AVISOS) -> str:
    """Os primeiros avisos das fontes, para a faixa de coleta parcial.

    Limitado porque a faixa é uma ressalva, não um relatório: dez avisos em
    cima do título empurram a notícia para fora da primeira tela.
    """
    avisos = [aviso for fonte in fontes for aviso in fonte.avisos]
    return "; ".join(avisos[:limite])


_DATA_FINAL = re.compile(
    r",?\s+DE\s+\d{1,2}[ºo°]?\s+DE\s+[A-ZÇÃÉ]+\s+DE\s+\d{4}\s*$",
    re.IGNORECASE,
)
_NUMERO_ORDINAL = re.compile(r"^N[º°O]\.?$", re.IGNORECASE)
_PONTUACAO_FINAL = ",;:."
_GRUPO_SIGLA = re.compile(r"^[A-Z0-9]+$")
_NAO_LETRA = re.compile(r"[/\-.0-9]")

# Lista fechada de siglas de órgão/instrumento que sobrevivem ao sentence
# case. Nenhuma heurística de tamanho: uma palavra comum e curta em
# maiúscula ("ATO", "AVISO", "PAUTA", "NOTA", "CARGO", "AUTOS" - achado da
# rodada 2) não vira sigla só por ter poucas letras. Ordenada para facilitar
# conferir se uma sigla nova já está aqui.
SIGLAS = frozenset(
    "AGU ANS ANVISA CC CES CGU CIB CIT CMS CNES CNPJ CNS CONASEMS CONASS CPF "
    "DOU FHEMIG FNS GAB GM INSS IOF LDO LOA MAC MEC MG MS PNAB PPA PR PRE "
    "RDC RE SAES SAMU SAPS SCTIE SE SECEX SES SGTES SIGTAP SUS SVSA TCU UBS "
    "UPA UTI VISA".split()
)


def _eh_sigla(palavra: str) -> bool:
    """Uma sigla sobrevive ao sentence case; uma palavra comum, não.

    Duas formas de ser sigla: (a) o token junta grupos com "/" ou "-" que são
    só letras maiúsculas e dígitos - "GM/MS", "CIB-SUS/MG",
    "SAES/SGTES/MS" - o token inteiro é o órgão abreviado, mesmo que uma
    parte isolada ("SUS") também esteja em `SIGLAS`; ou (b) o token, sem
    "/", "-", "." e dígitos, está na lista fechada `SIGLAS`. Fora isso, é
    palavra comum e desce para minúscula - não importa o tamanho.
    """
    nucleo = palavra.rstrip(_PONTUACAO_FINAL)
    if not nucleo:
        return False
    if "/" in nucleo or "-" in nucleo:
        grupos = re.split(r"[/\-]", nucleo)
        return all(grupo and _GRUPO_SIGLA.match(grupo) for grupo in grupos)
    return _NAO_LETRA.sub("", nucleo) in SIGLAS


def titulo_ato(titulo: str) -> str:
    """Título do ato em formato de sentença, sem a data que já está na linha de meta.

    O diário publica o identificador do ato em maiúscula inteira e gruda a
    data no fim: "PORTARIA GM/MS Nº 3.412, DE 2 DE SETEMBRO DE 2026". O
    DESIGN pede título em formato de sentença, e a data sai porque já aparece
    na linha de meta do item - repeti-la no título é ruído, não reforço.
    """
    sem_data = _DATA_FINAL.sub("", titulo).strip()
    palavras = sem_data.split()
    resultado: list[str] = []
    for indice, palavra in enumerate(palavras):
        proxima = palavras[indice + 1] if indice + 1 < len(palavras) else ""
        if _NUMERO_ORDINAL.match(palavra) and proxima[:1].isdigit():
            resultado.append("nº")
        elif _eh_sigla(palavra):
            resultado.append(palavra)
        else:
            resultado.append(palavra.lower())
    texto = " ".join(resultado)
    return texto[:1].upper() + texto[1:] if texto else texto


def criar_ambiente() -> Environment:
    """Ambiente Jinja do pacote, com autoescape só onde a saída é HTML."""
    ambiente = Environment(
        loader=PackageLoader("boletim", "templates"),
        autoescape=lambda nome: nome is not None and nome.endswith(".html.j2"),
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
    )
    ambiente.filters["brl"] = brl
    ambiente.filters["data_br"] = data_br
    ambiente.filters["data_extenso"] = data_extenso
    ambiente.filters["sem_travessao"] = sem_travessao
    ambiente.filters["url_segura"] = url_segura
    ambiente.filters["url_markdown"] = url_markdown
    ambiente.filters["nome_fonte"] = nome_fonte
    ambiente.filters["avisos_fontes"] = avisos_fontes
    ambiente.filters["fontes_publicadas"] = fontes_publicadas
    ambiente.filters["titulo_ato"] = titulo_ato
    ambiente.filters["meta_orgao"] = meta_orgao
    ambiente.filters["meta_origem"] = meta_origem
    ambiente.filters["resumo_edicao"] = resumo_edicao
    return ambiente


@dataclass(frozen=True)
class ContextoRender:
    """Tudo que o template precisa e não sabe calcular sozinho."""

    edicao: Edicao
    site_url: str
    url_edicao: str
    url_logo_navy: str
    url_logo_branco: str
    cta_url: str
    cta_texto: str
    cta_whatsapp_legivel: str
    rotulos: dict[str, str]
    modo: Modo

    @classmethod
    def montar(cls, edicao: Edicao, cfg: ConfigBoletim, modo: Modo) -> ContextoRender:
        site_url = cfg.site_url.rstrip("/")
        return cls(
            edicao=edicao,
            site_url=site_url,
            url_edicao=f"{site_url}/edicoes/{edicao.data.isoformat()}.html",
            url_logo_navy=f"{site_url}/assets/logo-navy.png",
            url_logo_branco=f"{site_url}/assets/logo-branco.png",
            cta_url=cfg.cta.url(edicao.data),
            cta_texto=cfg.cta.texto_botao,
            cta_whatsapp_legivel=telefone_legivel(cfg.cta.whatsapp),
            rotulos=ROTULOS,
            modo=modo,
        )

    def como_dict(self) -> dict[str, Any]:
        return {campo.name: getattr(self, campo.name) for campo in fields(self)}


def _render(template: str, edicao: Edicao, cfg: ConfigBoletim, modo: Modo) -> str:
    contexto = ContextoRender.montar(edicao, cfg, modo)
    return criar_ambiente().get_template(template).render(**contexto.como_dict())


def render_email(edicao: Edicao, cfg: ConfigBoletim) -> str:
    """O e-mail que sai para a lista."""
    return _render("email.html.j2", edicao, cfg, "email")


def render_web(edicao: Edicao, cfg: ConfigBoletim) -> str:
    """A mesma edição como página do site: sem o convite a abrir o site."""
    return _render("email.html.j2", edicao, cfg, "web")


def render_md(edicao: Edicao, cfg: ConfigBoletim) -> str:
    """Markdown da edição, para arquivo e para leitura por agente."""
    return _render("edicao.md.j2", edicao, cfg, "web")


def render_index(edicoes: list[dict[str, Any]], cfg: ConfigBoletim) -> str:
    """Índice do site. Cada dict traz `data, titulo, url, contagens, parcial`."""
    site_url = cfg.site_url.rstrip("/")
    # A mensagem do WhatsApp cita uma data; no índice, a da edição mais recente.
    # Assim o índice regerado hoje sobre um arquivo antigo não muda de conteúdo.
    data_cta = edicoes[0]["data"] if edicoes else hoje()
    return criar_ambiente().get_template("index.html.j2").render(
        edicoes=edicoes,
        site_url=site_url,
        url_logo_navy=f"{site_url}/assets/logo-navy.png",
        url_logo_branco=f"{site_url}/assets/logo-branco.png",
        cta_url=cfg.cta.url(data_cta),
        cta_whatsapp_legivel=telefone_legivel(cfg.cta.whatsapp),
    )
