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

from boletim.config import ConfigBoletim
from boletim.edicao import ROTULOS
from boletim.render import (
    brl,
    data_br,
    data_extenso,
    render_email,
    render_index,
    render_md,
    render_web,
    sem_travessao,
    telefone_legivel,
    titulo_ato,
)
from tests.fixtures.boletim.edicao_exemplo import edicao_exemplo

MSO = re.compile(r"<!--\[if [^\]]*\]>.*?<!\[endif\]-->", re.DOTALL)
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF]")
WHATSAPP = "wa.me/5531984483183"


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


def test_rodape_repete_o_whatsapp_em_link_e_por_extenso(html):
    assert html.count(WHATSAPP) >= 2
    assert "(31) 98448-3183" in html


def test_indice_nao_tem_botao(cfg):
    indice = render_index(
        [
            {
                "data": date(2026, 9, 3),
                "titulo": "Boletim de 03/09",
                "url": "edicoes/2026-09-03.html",
                "contagens": {"A": 2, "B": 1, "C": 1, "D": 2},
                "parcial": True,
            }
        ],
        cfg,
    )
    assert 'bgcolor="#0060e0"' not in indice
    assert "#0060e0" in indice  # o link continua sendo a luz


# ── identidade ──────────────────────────────────────────────────────────
def test_nada_de_ambar_ciano_gradiente_travessao_ou_emoji(html):
    assert "#FFB347" not in html
    assert "color:#40D7FF" not in html.replace(" ", "")
    assert "linear-gradient" not in html
    assert "—" not in html and "–" not in html
    assert EMOJI.search(html) is None


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


def test_contagem_acompanha_o_rotulo(html, edicao):
    assert f'{ROTULOS["A"]} ({len(edicao.secoes["A"])})' in html


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
    assert "coleta parcial" in html
    assert 'href="edicoes/2026-09-03.html"' in html
