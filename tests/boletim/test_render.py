"""O e-mail é o produto. Estes testes leem o HTML como um cliente de e-mail leria.

Não checam beleza: checam o que quebra a entrega (largura fixa fora do MSO,
imagem sem `alt`, mais de um botão) e o que quebra a marca (âmbar, gradiente,
travessão, emoji, webfont). Um boletim bonito que o Outlook estica não serve.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date

import pytest

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
}


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


@pytest.mark.parametrize("saida", ["email", "indice"])
def test_modo_escuro_repinta_o_fundo_junto_com_o_logo(saida, html, cfg):
    """O logo branco precisa de chão escuro, e não só de `display:block`.

    Achado da revisão: o cliente que honra `prefers-color-scheme` sem inverter
    nada (Apple Mail com `color-scheme: light dark`) trocava o logo navy pelo
    branco e o deixava sobre `#f5f7f9`. A troca de logo e a repintura da peça
    passam a viver na mesma media query.
    """
    peca = html if saida == "email" else render_index([_EDICAO_INDICE], cfg)
    bloco = ESCURO.search(peca)
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


def test_indice_nao_tem_botao(cfg):
    indice = render_index([_EDICAO_INDICE], cfg)
    assert 'bgcolor="#0060e0"' not in indice
    assert "#0060e0" in indice  # o link continua sendo a luz


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
    """Os três tells que o design pass tirou da peça, nas três saídas.

    O middle dot e a seta são assinatura de página gerada; o raio ficou em 0
    porque a folha é quadrada e um botão arredondado dentro dela seria o único
    canto redondo da peça.
    """
    indice = render_index([_EDICAO_INDICE], cfg)
    for saida in (html, render_web(edicao, cfg), render_md(edicao, cfg), indice):
        # Sem os espaços: o middle dot não é assinatura de página gerada só
        # quando vem espaçado.
        assert "·" not in saida
        assert "→" not in saida
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


def test_versao_completa_so_no_email_e_indice_so_na_web(edicao, cfg):
    email = render_email(edicao, cfg)
    web = render_web(edicao, cfg)
    assert "Ler a versão completa" in email
    assert "Voltar ao índice" not in email
    assert "Ler a versão completa" not in web
    assert "Voltar ao índice" in web
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
    edicoes = [
        {
            "data": date(2026, 9, 4),
            "titulo": "Boletim de 04/09",
            "url": "edicoes/2026-09-04.html",
            "contagens": {"A": 1, "B": 0, "C": 0, "D": 0},
            "parcial": False,
        },
        {
            "data": date(2026, 9, 3),
            "titulo": "Boletim de 03/09",
            "url": "edicoes/2026-09-03.html",
            "contagens": {"A": 2, "B": 1, "C": 1, "D": 2},
            "parcial": True,
        },
    ]
    html = render_index(edicoes, cfg)
    assert html.index("4 de setembro de 2026") < html.index("3 de setembro de 2026")
    assert "Coleta parcial." in html
    assert 'href="edicoes/2026-09-03.html"' in html


def test_indice_conta_as_edicoes_em_frase_e_nao_em_tira_de_pontos(cfg):
    indice = render_index([_EDICAO_INDICE], cfg)
    assert "2 atos de captação, 1 mudança de regra e 1 edital. Coleta parcial." in indice


def test_indice_usa_a_mesma_folha_e_a_mesma_serifa_do_email(cfg):
    indice = render_index([_EDICAO_INDICE], cfg)
    assert indice.count("background-color:#FFFFFF") == 1
    assert "Georgia, 'Times New Roman', serif" in indice
    assert "#dde4ee" in indice


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
