"""O e-mail é o produto. Estes testes leem o HTML como um cliente de e-mail leria.

Não checam beleza: checam o que quebra a entrega (largura fixa fora do MSO,
imagem sem `alt`, mais de um botão) e o que quebra a marca (âmbar, gradiente,
travessão, emoji, webfont). Um boletim bonito que o Outlook estica não serve.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from boletim import render
from boletim.config import ConfigBoletim, ConfigCTA
from boletim.edicao import ROTULOS
from boletim.render import (
    brl,
    data_br,
    data_extenso,
    meta_orgao,
    meta_origem,
    render_email,
    render_index,
    render_md,
    render_web,
    resumo_edicao,
    sem_travessao,
    telefone_legivel,
    titulo_ato,
    url_segura,
)
from tests.fixtures.boletim.edicao_exemplo import edicao_exemplo

MSO = re.compile(r"<!--\[if [^\]]*\]>.*?<!\[endif\]-->", re.DOTALL)
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF]")
WHATSAPP = "wa.me/5531984483183"
# O bloco de repintura do modo escuro. Ele é o único lugar da peça onde o ciano
# e o navy de fundo podem aparecer, e por isso sai do HTML antes das checagens
# de paleta do sistema claro.
ESCURO = re.compile(
    r"@media \(prefers-color-scheme: dark\) \{.*?^\}$",
    re.DOTALL | re.MULTILINE,
)
FILETE = "border-top:1px solid #dde4ee"
# O rótulo de seção é a única coisa em caixa alta na peça.
ROTULO_DE_SECAO = "text-transform:uppercase"

_EDICAO_INDICE = {
    "data": date(2026, 9, 3),
    "titulo": "Boletim de 03/09",
    "url": "edicoes/2026-09-03.html",
    "contagens": {"A": 2, "B": 1, "C": 1, "D": 2},
    "parcial": True,
    "valor_dia": 29334567.89,
    "total_relevante": 4,
}

# Duas edições, a mais recente sem cifra declarada: é o caso que a coluna do
# dinheiro precisa aguentar sem escrever `R$ 0,00` em cima de um dia real.
_DUAS_EDICOES = [
    {
        "data": date(2026, 9, 4),
        "titulo": "Boletim de 04/09",
        "url": "edicoes/2026-09-04.html",
        "contagens": {"A": 1, "B": 0, "C": 0, "D": 0},
        "parcial": False,
        "valor_dia": None,
        "total_relevante": 1,
    },
    _EDICAO_INDICE,
]


@pytest.fixture
def cfg() -> ConfigBoletim:
    return ConfigBoletim()


@pytest.fixture
def edicao():
    return edicao_exemplo()


@pytest.fixture
def html(edicao, cfg) -> str:
    return render_email(edicao, cfg)


# ── filtros ─────────────────────────────────────────────────────────────
def test_brl_formata_no_padrao_brasileiro():
    assert brl(1234567.89) == "R$ 1.234.567,89"
    assert brl(28100000.0) == "R$ 28.100.000,00"


def test_data_br_e_data_extenso():
    assert data_br(date(2026, 9, 3)) == "03/09/2026"
    assert data_extenso(date(2026, 9, 3)) == "3 de setembro de 2026"
    assert data_extenso(date(2026, 12, 31)) == "31 de dezembro de 2026"


def test_sem_travessao_troca_os_dois_tracos_longos():
    assert sem_travessao("teto — MAC – ampliado") == "teto - MAC - ampliado"


def test_telefone_legivel_formata_o_numero_br():
    assert telefone_legivel("5531984483183") == "(31) 98448-3183"
    # Número fora do formato esperado sai como está: inventar máscara é pior.
    assert telefone_legivel("123") == "123"


@pytest.mark.parametrize(
    "bruto, esperado",
    [
        (
            "DELIBERAÇÃO CIB-SUS/MG Nº 4.512, DE 1º DE SETEMBRO DE 2026",
            "Deliberação CIB-SUS/MG nº 4.512",
        ),
        (
            "PORTARIA GM/MS Nº 3.412, DE 2 DE SETEMBRO DE 2026",
            "Portaria GM/MS nº 3.412",
        ),
        (
            "EDITAL DE CHAMAMENTO PÚBLICO Nº 12/2026",
            "Edital de chamamento público nº 12/2026",
        ),
        (
            "RESOLUÇÃO DE DIRETORIA COLEGIADA - RDC Nº 942, DE 1º DE SETEMBRO DE 2026",
            "Resolução de diretoria colegiada - RDC nº 942",
        ),
        (
            # Já em formato de sentença: só a data sai, o resto passa direto.
            "Portaria GM/MS nº 500, de 10 de janeiro de 2026",
            "Portaria GM/MS nº 500",
        ),
        (
            "PORTARIA CONJUNTA SAES/SGTES/MS Nº 5, DE 3 DE SETEMBRO DE 2026",
            "Portaria conjunta SAES/SGTES/MS nº 5",
        ),
        (
            # "ATO" não é sigla de nenhum órgão: é a palavra comum "ato".
            "ATO DO PRESIDENTE",
            "Ato do presidente",
        ),
        (
            # "AVISO" e "PAUTA" também não estão na lista fechada de siglas.
            "AVISO DE PAUTA",
            "Aviso de pauta",
        ),
        (
            "PORTARIA FHEMIG Nº 218",
            "Portaria FHEMIG nº 218",
        ),
        (
            "Portaria nº 10, de 1º de setembro de 2026",
            "Portaria nº 10",
        ),
        (
            "RESOLUÇÃO SES/MG Nº 9.101",
            "Resolução SES/MG nº 9.101",
        ),
    ],
)
def test_titulo_ato_sentenca_com_sigla_preservada_e_data_removida(bruto, esperado):
    assert titulo_ato(bruto) == esperado


@pytest.mark.parametrize(
    "bruto",
    ["AVISO", "PAUTA", "NOTA", "CARGO", "AUTOS"],
)
def test_titulo_ato_nao_preserva_palavra_comum_curta_so_por_ser_maiuscula(bruto):
    """Achado da rodada 2: o limite de tamanho não bastava para distinguir
    sigla de palavra comum curta - só a lista fechada `SIGLAS` decide."""
    assert titulo_ato(bruto) == bruto.capitalize()


def test_meta_orgao_junta_orgao_e_unidade_sem_middle_dot(edicao):
    # Antes a meta era uma tira de "A · B · C · D". Agora a primeira linha diz
    # só quem publicou, que é o que o gestor reconhece.
    federal = edicao.secoes["B"][0]
    assert meta_orgao(federal) == (
        "Ministério da Saúde, Secretaria de Atenção Primária à Saúde"
    )


def test_meta_orgao_omite_a_unidade_quando_ela_falta(edicao):
    sem_unidade = replace(edicao.secoes["B"][0], unidade=None)
    assert meta_orgao(sem_unidade) == "Ministério da Saúde"


def test_meta_origem_cita_diario_edicao_secao_pagina_e_data(edicao):
    federal = edicao.secoes["B"][0]
    assert meta_origem(federal) == "DOU nº 169, seção 1, página 44, de 03/09/2026"


def test_meta_origem_no_estadual_nao_repete_a_data_como_numero_de_edicao(edicao):
    # No IOF-MG o campo `edicao` é a própria data ("2026-09-03"); citá-la como
    # "nº 2026-09-03" seria ruído, e a data já fecha a linha.
    estadual = edicao.secoes["A"][0]
    assert estadual.fonte == "iofmg"
    assert meta_origem(estadual) == (
        "Diário Oficial de Minas Gerais, página 12, de 03/09/2026"
    )


def test_meta_origem_troca_travessao_vindo_do_diario(edicao):
    # Minor do ledger: a citação passava sem `sem_travessao`, e o campo `secao`
    # chega do diário, que copia travessão de PDF.
    com_travessao = replace(edicao.secoes["B"][0], secao="1 — suplemento")
    assert "—" not in meta_origem(com_travessao)
    assert "seção 1 - suplemento" in meta_origem(com_travessao)


@pytest.mark.parametrize(
    "contagens, parcial, esperado",
    [
        ({"A": 2, "B": 1, "C": 1}, False, "2 atos de captação, 1 mudança de regra e 1 edital."),
        # O índice antigo imprimia "1 editais": o plural agora acompanha o número.
        ({"A": 1, "B": 0, "C": 1}, False, "1 ato de captação e 1 edital."),
        ({"A": 0, "B": 0, "C": 3}, False, "3 editais."),
        ({"A": 0, "B": 0, "C": 0}, False, "Sem publicações relevantes."),
        ({"A": 2, "B": 0, "C": 0}, True, "2 atos de captação. Coleta parcial."),
    ],
)
def test_resumo_edicao_conta_em_frase_com_plural_correto(contagens, parcial, esperado):
    assert resumo_edicao(contagens, parcial) == esperado


# ── entregabilidade ─────────────────────────────────────────────────────
def test_head_declara_viewport_e_esquema_de_cor(html):
    assert 'name="viewport"' in html
    assert 'content="width=device-width, initial-scale=1"' in html
    assert 'name="color-scheme" content="light dark"' in html
    assert 'name="supported-color-schemes" content="light dark"' in html


def test_largura_e_fluida_com_teto_de_600px(html):
    assert "max-width:600px" in html
    # `width="600"` só é aceitável dentro do comentário condicional do Outlook;
    # fora dele, trava a coluna e estoura a tela de 375px.
    assert 'width="600"' not in MSO.sub("", html)


def test_media_query_mobile_presente(html):
    assert "@media only screen and (max-width:480px)" in html


def test_swap_de_logo_no_modo_escuro(html):
    assert "@media (prefers-color-scheme: dark)" in html
    assert ".logo-claro" in html and ".logo-escuro" in html


def test_modo_escuro_repinta_o_fundo_junto_com_o_logo(html):
    """O logo branco precisa de chão escuro, e não só de `display:block`.

    Achado da revisão: o cliente que honra `prefers-color-scheme` sem inverter
    nada (Apple Mail com `color-scheme: light dark`) trocava o logo navy pelo
    branco e o deixava sobre `#f5f7f9`. A troca de logo e a repintura da peça
    passam a viver na mesma media query.

    Vale só para o e-mail. O site não tem modo claro para repintar: ele nasce
    escuro, que é o padrão do sistema.
    """
    bloco = ESCURO.search(html)
    assert bloco is not None
    regras = bloco.group().replace(" ", "")
    assert ".logo-escuro{display:block!important;}" in regras
    # Tokens escuros do DESIGN.md: navy de fundo, branco só em título, ink no
    # corpo, ciano como luz - o azul elétrico dá 3.60:1 sobre navy e reprova.
    assert ".fundo{background-color:#00051f!important;}" in regras
    assert ".titulo{color:#FFFFFF!important;}" in regras
    assert ".corpo{color:#c7d2e8!important;}" in regras
    assert ".muted{color:#8b95b5!important;}" in regras
    assert ".link{color:#40D7FF!important;}" in regras
    assert "background-color:#050a25!important" in regras
    assert "border-color:#1a2246!important" in regras


@pytest.mark.parametrize(
    "classe", ["fundo", "folha", "titulo", "corpo", "muted", "filete", "link"]
)
def test_cada_classe_da_repintura_tem_dono_no_html(classe, html):
    """Estilo é inline nesta peça: sem a classe no elemento, a media query
    escura não tem em que pegar."""
    # Token inteiro: `titulo-edicao` não é `titulo`.
    assert re.search(rf'class="(?:[^"]*\s)?{classe}(?:\s[^"]*)?"', html) is not None


def test_toda_imagem_tem_alt(html):
    imagens = re.findall(r"<img\b[^>]*>", html)
    assert imagens
    assert all("alt=" in img for img in imagens)


# ── conversão ───────────────────────────────────────────────────────────
def test_existe_um_unico_botao_e_ele_leva_ao_whatsapp(html, edicao, cfg):
    ocorrencias = [m.start() for m in re.finditer(r'bgcolor="#0060e0"', html)]
    assert len(ocorrencias) == 1
    bloco = html[ocorrencias[0] : ocorrencias[0] + 600]
    assert f'<a href="{cfg.cta.url(edicao.data)}"' in bloco
    assert cfg.cta.texto_botao in bloco


def test_rotulo_padrao_do_botao_cabe_em_uma_linha_a_375px(html):
    """Achado da revisão: "Falar com a Thauma sobre IA para o SUS" tem 38
    caracteres e, a 17px/600 com 24px de recuo, pede ~350px numa tela que
    oferece 295. O rótulo passa a nomear o destino em 30 caracteres e o botão
    desce para 16px, que é o corpo mínimo do DESIGN.md."""
    assert len(ConfigCTA().texto_botao) <= 32
    assert ConfigCTA().texto_botao == "Falar com a Thauma no WhatsApp"
    inicio = html.index('bgcolor="#0060e0"')
    assert "font-size:16px" in html[inicio : inicio + 600]


def test_rodape_repete_o_whatsapp_em_link_e_por_extenso(html):
    assert html.count(WHATSAPP) >= 2
    assert "(31) 98448-3183" in html


def test_indice_do_site_repete_o_botao_com_o_mesmo_destino(cfg):
    """O índice antigo era uma folha clara sem chamada. O site é uma landing, e
    o DESIGN.md manda um botão por tela: ele reaparece na última dobra, mas com
    o mesmo destino - dois destinos concorrentes é o mesmo erro que duas luzes.
    """
    indice = render_index([_EDICAO_INDICE], cfg)
    destinos = set(re.findall(r'<a class="botao"[^>]*href="([^"]+)"', indice))
    assert len(destinos) == 1
    assert indice.count('class="botao"') == 2
    assert WHATSAPP in destinos.pop()


# ── identidade ──────────────────────────────────────────────────────────
def test_nada_de_ambar_ciano_gradiente_travessao_ou_emoji(html):
    assert "#FFB347" not in html
    # O ciano é a luz do sistema escuro e só pode carregar texto lá dentro: no
    # claro ele dá 1.58:1. Fora da media query escura, continua proibido.
    assert "color:#40D7FF" not in ESCURO.sub("", html).replace(" ", "")
    assert "linear-gradient" not in html
    assert "—" not in html and "–" not in html
    assert EMOJI.search(html) is None


def test_sem_middle_dot_seta_ou_raio_generico(html, cfg, edicao):
    """Os três tells que o design pass tirou da peça.

    O middle dot e a seta são assinatura de página gerada, e valem para as
    quatro saídas. O raio 0 é regra só do e-mail e do markdown: a folha do
    e-mail é quadrada e um botão arredondado dentro dela seria o único canto
    redondo da peça. O site tem card e cápsula, que o DESIGN.md especifica com
    canto de 14 a 18px e raio 999px.
    """
    indice = render_index([_EDICAO_INDICE], cfg)
    for saida in (html, render_web(edicao, cfg), render_md(edicao, cfg), indice):
        # Sem os espaços: o middle dot não é assinatura de página gerada só
        # quando vem espaçado.
        assert "·" not in saida
        assert "→" not in saida
    for saida in (html, render_md(edicao, cfg)):
        assert "border-radius" not in saida


def test_no_maximo_quatro_rotulos_em_caixa_alta(html):
    """Um rótulo por seção real (A, B, C, D) e nenhum decorativo.

    O DESIGN.md autoriza o rótulo caixa alta; os dois skills o tratam como
    tell quando ele abre toda seção. O teto de 4 é o acordo: a estrutura fala
    por tipo, espaço e filete, e o rótulo só nomeia divisão de verdade.
    """
    assert html.count("text-transform:uppercase") <= 4


def test_a_edicao_inteira_cabe_em_uma_folha_branca(html):
    """Uma superfície, não uma pilha de cartões iguais.

    A hierarquia vem do tipo e do respiro, como manda o DESIGN.md; o cartão
    repetido era o que fazia a peça parecer um digest de SaaS.
    """
    assert html.count("background-color:#FFFFFF") == 1


def test_o_valor_sai_em_georgia_navy_alinhado_a_direita(html):
    """A coluna do dinheiro: a única coisa alinhada à direita na peça."""
    celulas = re.findall(r"<td[^>]*>R\$ [\d.,]+</td>", html)
    assert len(celulas) == 2
    for celula in celulas:
        assert "text-align:right" in celula
        assert "Georgia" in celula
        assert "color:#00051f" in celula
        # O valor não é a luz: a luz é o botão.
        assert "#0060e0" not in celula


def test_o_pe_do_ato_le_como_uma_linha_so(html, edicao):
    """Achado da revisão: 22px ao lado de 15px lia como dois objetos soltos.

    O pé do ato é um rodapé, não um par de elementos: link a 16px, valor a
    20px e os dois pendurados na mesma linha de base.
    """
    pes = re.findall(r"<tr>\s*<td align=\"left\" valign=\"bottom\".*?</tr>", html, re.DOTALL)
    assert len(pes) == sum(len(edicao.secoes[cat]) for cat in ("A", "B", "C"))
    for pe in pes:
        assert "font-size:16px" in pe
        assert pe.count('valign="bottom"') == (2 if "R$" in pe else 1)
        if "R$" in pe:
            assert "font-size:20px" in pe
    assert "font-size:22px" not in html


def _quebras(html: str) -> list[tuple[int, bool]]:
    """Cada filete da peça como `(altura do espaçador acima, abre seção?)`."""
    saida = []
    for achado in re.finditer(re.escape(FILETE), html):
        acima = re.findall(r'height="(\d+)"', html[: achado.start()])
        abaixo = html[achado.end() : achado.end() + 400]
        saida.append((int(acima[-1]), ROTULO_DE_SECAO in abaixo))
    return saida


def test_quebra_de_secao_pesa_mais_que_quebra_entre_itens(html):
    """Achado da revisão: as duas quebras eram o mesmo `32/filete/32`, então
    a seção nova lia como mais um ato. Antes de um rótulo de seção o respiro
    de cima sobe para 48px; entre itens continua em 32."""
    quebras = _quebras(html)
    de_secao = [altura for altura, abre in quebras if abre]
    de_item = [altura for altura, abre in quebras if not abre]
    assert len(de_secao) == 3  # A, B e C
    assert set(de_secao) == {48}
    assert de_item and 48 not in de_item


def test_por_que_importa_nao_e_mais_um_rotulo_em_caixa_alta(html):
    assert "Por que importa." in html


def test_nenhuma_webfont(html):
    assert "@font-face" not in html
    # `\bInter\b`: "Intergestores" é nome de comissão, não a fonte proibida.
    assert re.search(r"\bInter\b", html) is None
    assert "Georgia, 'Times New Roman', serif" in html


# ── conteúdo ────────────────────────────────────────────────────────────
def test_todos_os_rotulos_aparecem_quando_ha_itens(html):
    for rotulo in ROTULOS.values():
        assert rotulo in html


def test_secao_vazia_nao_deixa_rotulo_orfao(edicao, cfg):
    sem_c = replace(edicao, secoes={**edicao.secoes, "C": ()})
    html = render_email(sem_c, cfg)
    assert ROTULOS["C"] not in html
    assert ROTULOS["A"] in html


def test_rotulo_de_secao_nao_traz_contagem(html, edicao, cfg):
    """Achado da revisão: "Captação de recursos (2)" conta o que o leitor já
    vê logo abaixo, e o parêntese com número é tell de página gerada. A
    contagem em frase continua onde ela informa de fato: no índice."""
    for saida in (html, render_web(edicao, cfg), render_md(edicao, cfg)):
        for chave, rotulo in ROTULOS.items():
            assert rotulo in saida
            assert f'{rotulo} ({len(edicao.secoes[chave])})' not in saida
    assert "2 atos de captação" in render_index([_EDICAO_INDICE], cfg)


def test_valor_sai_formatado_em_reais(html):
    assert "R$ 1.234.567,89" in html


def test_versao_completa_so_no_email_e_volta_ao_indice_so_no_site(edicao, cfg):
    """O e-mail convida a abrir o site; o site já é o site e leva ao arquivo.

    O alvo mudou de "Voltar ao índice" para "Todas as edições" quando a página
    saiu do template do e-mail: quem chega pelo Google não voltou de lugar
    nenhum, e o link nomeia o destino em vez de descrever um movimento.
    """
    email = render_email(edicao, cfg)
    web = render_web(edicao, cfg)
    assert "Ler a versão completa" in email
    assert "Todas as edições" not in email
    assert "Ler a versão completa" not in web
    assert f'<a class="link" href="{cfg.site_url}">Todas as edições</a>' in web
    assert f"{cfg.site_url}/edicoes/2026-09-03.html" in email


def test_faixa_de_coleta_parcial_traz_o_aviso_da_fonte(html, edicao):
    assert edicao.parcial
    assert "Coleta parcial nesta data" in html
    assert "página 31 do caderno não pôde ser extraída" in html


def test_rodape_nomeia_as_fontes_de_forma_legivel(html):
    assert "DOU via INLABS" in html
    assert "Diário Oficial de Minas Gerais" in html


def test_conteudo_do_diario_sai_escapado(edicao, cfg):
    primeiro = edicao.secoes["A"][0]
    hostil = replace(primeiro, titulo="<script>alert('xss')</script> Portaria")
    perigosa = replace(edicao, secoes={**edicao.secoes, "A": (hostil,)})
    html = render_email(perigosa, cfg)
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" in html


# ── markdown e índice ───────────────────────────────────────────────────
def test_markdown_tem_as_secoes_e_o_link_do_whatsapp(edicao, cfg):
    md = render_md(edicao, cfg)
    assert md.startswith(f"# {edicao.titulo}")
    assert "## Em 30 segundos" in md
    assert f'## {ROTULOS["A"]}' in md
    assert "## Fale com a Thauma" in md
    assert WHATSAPP in md
    assert "R$ 1.234.567,89" in md
    # Markdown não passa por autoescape: o `<` do diário não pode virar `&lt;`.
    assert "&lt;" not in md


def test_indice_lista_as_edicoes_da_mais_recente_para_a_mais_antiga(cfg):
    html = render_index(_DUAS_EDICOES, cfg)
    assert html.index("4 de setembro de 2026") < html.index("3 de setembro de 2026")
    assert "Coleta parcial." in html
    assert 'href="edicoes/2026-09-03.html"' in html


def test_indice_conta_as_edicoes_em_frase_e_nao_em_tira_de_pontos(cfg):
    indice = render_index([_EDICAO_INDICE], cfg)
    assert "2 atos de captação, 1 mudança de regra e 1 edital. Coleta parcial." in indice


def test_indice_saiu_do_sub_sistema_de_e_mail(cfg):
    """O veredito do Pedro sobre o site anterior foi de forma, não de conteúdo:
    a página era o e-mail servido no navegador. Nada da tabela de 600px, do
    estilo inline e da folha branca sobrevive."""
    indice = render_index([_EDICAO_INDICE], cfg)
    assert "background-color:#FFFFFF" not in indice
    assert "<table" not in indice
    assert "bgcolor" not in indice
    assert 'width="600"' not in indice
    assert "#f5f7f9" not in indice


# ── o site: sistema escuro ──────────────────────────────────────────────
#
# O site tem folha externa, então o HTML não carrega estilo nenhum e o CSS não
# sabe qual página está pintando. As duas metades são conferidas em separado: o
# markup responde pela contagem de portadores por dobra, o CSS responde pelo
# inventário do ciano e do gradiente.
CIANO = "#40D7FF"
# Um bloco folha de CSS: `seletor { declarações }`. Como `[^{}]` não atravessa
# chave, a expressão só casa com o bloco mais interno, e regra dentro de
# `@media` sai com o seletor dela, não com o da media query.
REGRA_CSS = re.compile(r"([^{}]+)\{([^{}]*)\}")
COMENTARIO_CSS = re.compile(r"/\*.*?\*/", re.DOTALL)

# Onde o sistema autoriza gastar a luz. Quatro lugares, e o anel de foco é
# estado de interface, não portador.
SELETORES_COM_LUZ = {":root", ".botao", ".capsula-ponto", ".filete-luz", ":focus-visible"}
# Gradiente decorativo é proibido. Os três que existem têm função: o overlay do
# pipeline de imagem, o filete que nasce e morre transparente, e o baixo-relevo
# do numeral fantasma.
SELETORES_COM_GRADIENTE = {
    ".filete",
    ".filete-luz",
    ".hero-foto + .hero-overlay",
    ".numeral",
    ".numeral::after",
}


@pytest.fixture
def css() -> str:
    return (
        Path(render.__file__).parent / "assets" / "site.css"
    ).read_text(encoding="utf-8")


@pytest.fixture
def indice(cfg) -> str:
    return render_index(_DUAS_EDICOES, cfg)


@pytest.fixture
def pagina(edicao, cfg) -> str:
    return render_web(edicao, cfg)


def _regras(css: str) -> list[tuple[str, str]]:
    limpo = COMENTARIO_CSS.sub("", css)
    return [
        (seletor.strip(), corpo)
        for seletor, corpo in REGRA_CSS.findall(limpo)
        if seletor.strip()
    ]


def _luzes_por_dobra(html: str) -> dict[str, int]:
    """Quantos `data-luz` cada dobra declara. A dobra vai até a próxima dobra."""
    marcas = [(m.group(1), m.start()) for m in re.finditer(r'data-dobra="(\d)"', html)]
    assert marcas, "a página não marcou nenhuma dobra"
    limites = [*[p for _, p in marcas[1:]], len(html)]
    return {
        numero: html.count("data-luz", inicio, fim)
        for (numero, inicio), fim in zip(marcas, limites)
    }


def test_nenhuma_dobra_carrega_duas_luzes(indice, pagina):
    """A regra mais dura do DESIGN.md numa página que rola: composição = dobra.

    Quando dois elementos disputam a luz, nenhum dos dois é a luz.
    """
    for html in (indice, pagina):
        assert max(_luzes_por_dobra(html).values()) <= 1


def test_o_portador_de_cada_dobra_e_o_declarado_no_plano(indice, pagina):
    """No índice as três dobras pedem ação ou estado, e as três têm portador.

    Na edição o miolo não tem nenhum, de propósito: são 46 atos num dia real, e
    um ponto de luz por ato seriam 46 luzes, que é o mesmo que nenhuma.
    """
    assert _luzes_por_dobra(indice) == {"1": 1, "2": 1, "3": 1}
    assert _luzes_por_dobra(pagina) == {"1": 1, "2": 0, "3": 1}


def test_a_luz_do_indice_e_botao_capsula_botao(indice):
    portadores = re.findall(r'<(\w+) class="([^"]+)"[^>]*data-luz', indice)
    assert [(tag, classe) for tag, classe in portadores] == [
        ("a", "botao"),
        ("span", "capsula"),
        ("a", "botao"),
    ]


def test_a_luz_da_edicao_e_filete_e_botao(pagina):
    portadores = re.findall(r'<(\w+) class="([^"]+)"[^>]*data-luz', pagina)
    assert portadores == [("span", "filete filete-luz"), ("a", "botao")]


def test_o_html_do_site_nao_carrega_cor_nenhuma(indice, pagina):
    """Estilo mora na folha externa. Ciano solto no markup é vazamento."""
    for html in (indice, pagina):
        assert CIANO not in html
        assert "style=" not in html
        assert "<style" not in html


def test_o_css_gasta_a_luz_em_quatro_lugares_e_declara_o_hex_uma_vez(css):
    assert css.count(CIANO) == 1  # só na definição de `--luz`
    gastam = {
        seletor
        for seletor, corpo in _regras(css)
        if "var(--luz" in corpo or CIANO in corpo
    }
    assert gastam == SELETORES_COM_LUZ


def test_o_ciano_nunca_carrega_texto_corrido(css):
    for seletor, corpo in _regras(css):
        for declaracao in corpo.split(";"):
            propriedade, _, valor = declaracao.partition(":")
            if propriedade.strip() == "color":
                assert "--luz" not in valor and CIANO not in valor, seletor


def test_gradiente_so_no_overlay_no_filete_e_no_numeral(css):
    com_gradiente = {
        seletor for seletor, corpo in _regras(css) if "gradient" in corpo
    }
    assert com_gradiente == SELETORES_COM_GRADIENTE
    # Gradiente radial e cônico não existem no sistema.
    assert "radial-gradient" not in css and "conic-gradient" not in css


def test_a_fraunces_entra_com_os_eixos_da_marca(css, indice, pagina):
    """A armadilha documentada: os defaults do arquivo variável não são os da
    marca. Sem fixar os eixos, o título sai no corte de display e com a
    excentricidade do WONK ligada."""
    assert '"opsz" 40' in css and '"SOFT" 0' in css and '"WONK" 0' in css
    for html in (indice, pagina):
        assert "family=Fraunces:SOFT,WONK,opsz,wght@0,0,9..144,400..600" in html
        assert "family=Plus+Jakarta+Sans:wght@300;500;700" in html
        assert "display=swap" in html
    assert "Georgia" in css  # a pilha de fallback enquanto a webfont não chega


def test_grao_vinheta_de_ruido_sobre_a_pagina(css):
    """A profundidade do sistema é o grão e o filete, não a caixa."""
    assert "feTurbulence" in css
    assert "mix-blend-mode: overlay" in css
    assert "opacity: .03" in css
    assert "box-shadow" not in css.replace("box-shadow: 0 0 10px rgba(var(--luz-rgb), .60)", "")


def test_uma_revelacao_so_e_ela_respeita_reduced_motion(css):
    assert css.count("@keyframes") == 1
    assert "@media (prefers-reduced-motion: reduce)" in css
    reduzido = css[css.index("@media (prefers-reduced-motion: reduce)") :]
    assert "animation: none" in reduzido


def test_foco_visivel_ao_teclado_com_segundo_canal(css):
    assert "outline: none" not in css
    assert ":focus-visible" in css
    assert "outline-offset: 2px" in css


def test_toda_imagem_do_site_tem_alt(indice, pagina):
    for html in (indice, pagina):
        imagens = re.findall(r"<img\b[^>]*>", html)
        assert imagens
        assert all("alt=" in img for img in imagens)


def test_paginas_do_site_sem_travessao_emoji_ou_largura_de_email(indice, pagina):
    for html in (indice, pagina):
        assert "—" not in html and "–" not in html
        assert EMOJI.search(html) is None
        assert 'width="600"' not in html
        assert "<table" not in html


def test_o_indice_traz_o_valor_do_dia_e_cala_quando_nao_ha_cifra(indice):
    """A coluna do dinheiro no índice: uma escala acima da edição.

    Dia sem cifra declarada fica sem número. Zero e "não declarado" são coisas
    diferentes, e `R$ 0,00` em cima de um dia real seria a segunda.
    """
    valores = re.findall(r'<span class="valor">([^<]+)</span>', indice)
    assert valores == ["R$ 29.334.567,89"]


def test_a_edicao_tem_a_coluna_do_dinheiro_em_todos_os_atos_com_valor(pagina, edicao):
    com_valor = [
        item
        for cat in ("A", "B", "C")
        for item in edicao.secoes[cat]
        if item.valor_brl
    ]
    valores = re.findall(r'<p class="valor">([^<]+)</p>', pagina)
    assert len(valores) == len(com_valor) == 2
    assert "R$ 1.234.567,89" in valores


def test_o_valor_e_a_unica_coisa_alinhada_a_direita(css):
    a_direita = {
        seletor
        for seletor, corpo in _regras(css)
        if "text-align: right" in corpo
    }
    assert a_direita == {".valor"}


def test_a_caixa_alta_so_abre_secao_de_verdade(indice, pagina):
    """O rótulo em caixa alta é do DESIGN.md e os dois skills o tratam como tell
    quando ele abre toda seção. O acordo: no índice ele nomeia a seção do
    arquivo e a marca; na edição, as quatro categorias do boletim, que são a
    taxonomia que o leitor usa para varrer a página."""
    assert indice.count('class="rotulo"') == 2
    assert pagina.count('class="rotulo"') == 1 + len(ROTULOS)
    # A data do card não virou rótulo: seis datas em caixa alta empilhadas são
    # exatamente o cromo de template que o design pass tirou da peça.
    assert '<span class="meta data">' in indice


def test_conteudo_do_diario_sai_escapado_tambem_no_site(edicao, cfg):
    primeiro = edicao.secoes["A"][0]
    hostil = replace(primeiro, titulo="<script>alert('xss')</script> Portaria")
    perigosa = replace(edicao, secoes={**edicao.secoes, "A": (hostil,)})
    html = render_web(perigosa, cfg)
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" in html


def test_titulo_hostil_no_indice_tambem_sai_escapado(cfg):
    entrada = {**_EDICAO_INDICE, "titulo": "<script>alert('xss')</script>"}
    html = render_index([entrada], cfg)
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" in html


def test_o_numeral_fantasma_e_decoracao_e_sai_da_leitura(pagina):
    """Ele repete a data que já está em texto uma linha abaixo. Escala, não
    informação: quem lê por leitor de tela não precisa ouvir "05.09" duas
    vezes."""
    assert '<span class="numeral" data-numeral="03.09" aria-hidden="true">' in pagina
    assert "3 de setembro de 2026" in pagina


def test_link_do_miolo_e_ink_com_sublinhado_nao_ciano(css):
    regras = dict(_regras(css))
    assert "color: var(--ink)" in regras[".link"]
    assert "text-decoration: underline" in regras[".link"]
    assert "var(--luz" not in regras[".link"] and "var(--luz" not in regras[".link:hover"]


# ── esquema de URL ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "url",
    [
        "https://www.in.gov.br/web/dou/-/portaria-1",
        "http://www.iof.mg.gov.br/edicao",
        "  https://www.in.gov.br/espacos  ",
        "HTTPS://WWW.IN.GOV.BR/MAIUSCULA",
    ],
)
def test_url_segura_deixa_passar_http_e_https(url):
    assert url_segura(url) == url.strip()


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "//exemplo.test/protocolo-relativo",
        "",
    ],
)
def test_url_segura_recusa_o_resto(url):
    assert url_segura(url) == ""


def _com_url(edicao, url: str):
    """A mesma edição com um único item em A, carregando a URL de teste."""
    primeiro = edicao.secoes["A"][0]
    return replace(
        edicao, secoes={**edicao.secoes, "A": (replace(primeiro, url=url),)}
    )


def test_url_hostil_do_diario_nao_vira_href_no_email(edicao, cfg):
    """`item.url` vem do diário e a peça vai para e-mail e página pública.

    O autoescape do Jinja impede a fuga do atributo, mas não impede um
    `javascript:` de virar href legítimo. A defesa é a lista de esquemas.
    """
    html = render_email(_com_url(edicao, "javascript:alert(1)"), cfg)
    assert "javascript:" not in html
    assert 'href=""' not in html


def test_url_de_dados_nao_vira_href_no_email(edicao, cfg):
    html = render_email(_com_url(edicao, "data:text/html,<h1>x</h1>"), cfg)
    assert "data:text/html" not in html


def test_url_https_continua_virando_href(edicao, cfg):
    html = render_email(_com_url(edicao, "https://exemplo.test/ato"), cfg)
    assert 'href="https://exemplo.test/ato"' in html


def test_lista_de_outros_atos_perde_o_link_mas_mantem_o_titulo(edicao, cfg):
    """Em D o link envolve o próprio título: sem href, o título fica de pé."""
    primeiro = edicao.secoes["D"][0]
    hostil = replace(
        edicao,
        secoes={**edicao.secoes, "D": (replace(primeiro, url="javascript:alert(1)"),)},
    )
    html = render_email(hostil, cfg)
    assert "javascript:" not in html
    assert titulo_ato(sem_travessao(primeiro.titulo)) in html


def test_markdown_nao_publica_link_com_esquema_hostil(edicao, cfg):
    md = render_md(_com_url(edicao, "javascript:alert(1)"), cfg)
    assert "javascript:" not in md
    assert "[Ver publicação]()" not in md


def test_markdown_escapa_parentese_e_espaco_da_url(edicao, cfg):
    """`)` ou espaço vindos do diário fechariam o link markdown no meio."""
    md = render_md(_com_url(edicao, "https://exemplo.test/ato (2026)"), cfg)
    assert "[Ver publicação](https://exemplo.test/ato%20%282026%29)" in md
