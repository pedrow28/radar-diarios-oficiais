from datetime import date, datetime, timezone

import pytest

from boletim.carga import carregar
from boletim.config import ConfigBoletim
from boletim.prefiltro import Descarte, entes_candidatos, forca, triar, valores_brl
from radar.core.modelos import Publicacao, gerar_id


def _pub(titulo: str, *, ementa: str = "", texto: str = "", fonte="inlabs", secao="1",
         tipo="Portaria") -> Publicacao:
    url = "https://exemplo/" + titulo.lower().replace(" ", "-")
    return Publicacao(
        id=gerar_id(fonte, date(2026, 9, 3), url, titulo),
        fonte=fonte,
        data_publicacao=date(2026, 9, 3),
        coletado_em=datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc),
        orgao="Ministério da Saúde",
        unidade=None,
        secao=secao,
        pagina=1,
        edicao="169",
        tipo=tipo,
        numero="1",
        titulo=titulo,
        ementa=ementa or None,
        texto=texto,
        url=url,
        origem={},
    )


@pytest.fixture
def cfg() -> ConfigBoletim:
    return ConfigBoletim()


@pytest.fixture
def dir_dados(dir_fixtures):
    return dir_fixtures / "boletim"


# ── valores_brl ─────────────────────────────────────────────────────────
def test_valores_brl_le_milhar_e_centavos():
    assert valores_brl("recurso de R$ 1.234.567,89 e R$ 200,00 no total") == (
        1234567.89,
        200.0,
    )


def test_valores_brl_aceita_sem_espaco_e_sem_separador_de_milhar():
    assert valores_brl("R$1.500,50 mais R$99,99") == (1500.5, 99.99)


def test_valores_brl_sem_valor_devolve_vazio():
    assert valores_brl("portaria sem cifra alguma") == ()


def test_valores_brl_ignora_numero_solto_sem_cifra():
    assert valores_brl("são 1.234,00 leitos habilitados") == ()


# ── entes_candidatos ────────────────────────────────────────────────────
def test_entes_candidatos_captura_municipio_e_hospital():
    texto = "Habilita leitos no Município de Manhuaçu para o Hospital César Leite, conforme anexo."
    assert entes_candidatos(texto) == ("Município de Manhuaçu", "Hospital César Leite")


def test_entes_candidatos_atravessa_conectivos_e_para_na_pontuacao():
    texto = "Repasse à Santa Casa de Misericórdia de Belo Horizonte, no valor previsto."
    assert entes_candidatos(texto) == ("Santa Casa de Misericórdia de Belo Horizonte",)


def test_entes_candidatos_deduplica_preservando_a_ordem():
    texto = "O Município de Uberaba e o Hospital Regional. O Município de Uberaba pactuou."
    assert entes_candidatos(texto) == ("Município de Uberaba", "Hospital Regional")


def test_entes_candidatos_limita_a_dez():
    nomes = "Alfa Beta Gama Delta Epsilon Zeta Eta Teta Iota Capa Lambda Mi Ni Csi".split()
    texto = " ".join(f"Município de {nome}." for nome in nomes)
    assert len(entes_candidatos(texto)) == 10


def test_entes_candidatos_ignora_marcador_seguido_de_minuscula():
    assert entes_candidatos("compete ao Município de origem informar") == ()


def test_entes_candidatos_nao_funde_dois_entes_ligados_por_e():
    texto = "Repasse ao Município de Uberaba e Hospital Regional de Barbacena."
    entes = entes_candidatos(texto)
    assert not any(" e " in ente for ente in entes)


def test_entes_candidatos_para_no_e_entre_municipios():
    assert entes_candidatos("Municípios de Manhuaçu e Ipatinga") == (
        "Municípios de Manhuaçu",
    )


def test_entes_candidatos_costura_nome_quebrado_pelo_pdf():
    """O texto do IOF-MG vem de PDF e quebra o nome no meio."""
    texto = "Repasse ao Hospital Santa Casa de Montes \nClaros, conforme anexo."
    assert entes_candidatos(texto) == ("Hospital Santa Casa de Montes Claros",)


def test_entes_candidatos_nao_engole_cabecalho_em_caixa_alta():
    assert entes_candidatos("Fundação Ezequiel Dias\nANEXO I") == (
        "Fundação Ezequiel Dias",
    )


def test_entes_candidatos_para_na_quebra_de_linha_dupla():
    texto = "Fundação Hospitalar\n\nHemominas presta contas."
    assert entes_candidatos(texto) == ("Fundação Hospitalar",)


def test_entes_candidatos_preserva_sigla_em_caixa_alta_no_meio_do_nome():
    """"Santa Casa BH" não pode sumir: bloquear toda palavra em caixa alta
    (exigindo que o segundo caractere não fosse maiúsculo) derrubava a sigla
    inteira, não só o cabeçalho de seção que a regra queria barrar."""
    texto = "Convênio com a Santa Casa BH e o Hospital Risoleta Neves."
    assert entes_candidatos(texto) == ("Santa Casa BH", "Hospital Risoleta Neves")


def test_entes_candidatos_preserva_algarismo_romano_em_caixa_alta():
    texto = "Convênio com o Hospital João XXIII para custeio."
    assert entes_candidatos(texto) == ("Hospital João XXIII",)


def test_entes_candidatos_preserva_sigla_junto_a_fundacao():
    texto = "Repasse à Fundação HEMOMINAS para custeio."
    assert entes_candidatos(texto) == ("Fundação HEMOMINAS",)


def test_entes_candidatos_ainda_bloqueia_cabecalho_de_secao_em_caixa_alta():
    """ANEXO, TABELA etc. continuam de fora mesmo com a sigla liberada."""
    assert entes_candidatos("Fundação Ezequiel Dias\nTABELA I") == (
        "Fundação Ezequiel Dias",
    )


# ── triar: uma publicação por regra ─────────────────────────────────────
def test_secao_2_do_dou_e_descartada(cfg):
    pub = _pub("PORTARIA Nº 9 QUE HABILITA LEITOS", secao="2", fonte="inlabs")
    triagem = triar([pub], cfg)
    assert triagem.mantidas == ()
    assert triagem.descartadas[0].regra == "secao_2"


def test_secao_2_de_outra_fonte_nao_e_descartada_pela_regra_1(cfg):
    pub = _pub("DELIBERAÇÃO CIB-SUS/MG Nº 9", secao="2", fonte="iofmg")
    triagem = triar([pub], cfg)
    assert len(triagem.mantidas) == 1


def test_nomeacao_e_descartada(cfg):
    pub = _pub("PORTARIA Nº 10", ementa="Nomeação de servidor para cargo em comissão.")
    triagem = triar([pub], cfg)
    assert triagem.descartadas[0].regra == "descarte"
    assert triagem.descartadas[0].id == pub.id


def test_retencao_forte_vence_o_descarte(cfg):
    pub = _pub(
        "PORTARIA Nº 11",
        ementa="Nomeação do gestor e habilitação de dez leitos de terapia intensiva.",
    )
    triagem = triar([pub], cfg)
    assert [p.id for p in triagem.mantidas] == [pub.id]
    assert triagem.descartadas == ()


def test_retencao_forte_no_corpo_nao_resgata_titulo_descartado(cfg):
    """O corpo de qualquer ato traz cifra e preâmbulo: não serve de resgate.

    Era a maior fonte de ruído da rodada real (222 das 504 mantidas da semana).
    """
    pub = _pub(
        "PORTARIA Nº 12",
        ementa="Concede férias regulamentares.",
        texto="No mesmo ato fica ampliado o teto MAC da regional em R$ 10.000,00.",
    )
    triagem = triar([pub], cfg)
    assert triagem.mantidas == ()
    assert triagem.descartadas[0].regra == "descarte"


def test_rdc_citada_no_preambulo_nao_resgata(cfg):
    pub = _pub(
        "RESOLUÇÃO-RE Nº 3.416",
        tipo="Resolução",
        texto="no uso das atribuições que lhe confere a RDC nº 585, de 2021, resolve:",
    )
    triagem = triar([pub], cfg)
    assert triagem.mantidas == ()
    assert triagem.descartadas[0].regra == "descarte"


def test_edital_citado_no_corpo_de_extrato_nao_resgata(cfg):
    pub = _pub(
        "EXTRATO DE CONTRATO Nº 594/26",
        tipo="Extrato de Contrato",
        texto="conforme condições constantes do respectivo Edital de licitação e seus Anexos.",
    )
    triagem = triar([pub], cfg)
    assert triagem.mantidas == ()
    assert triagem.descartadas[0].regra == "descarte"


def test_vocabulario_de_tabela_sus_retem_pelo_titulo(cfg):
    pub = _pub(
        "PORTARIA SAES/MS Nº 4.795",
        ementa=(
            "Inclui atributo complementar, altera procedimentos e tipo de "
            "compatibilidades na Tabela de Procedimentos, Medicamentos, Órteses, "
            "Próteses e Materiais Especiais do Sistema Único de Saúde."
        ),
    )
    triagem = triar([pub], cfg)
    assert [p.id for p in triagem.mantidas] == [pub.id]
    assert forca(pub) >= 1


def test_forca_conta_regras_distintas_e_nao_ocorrencias(cfg):
    """"altera o critério" e "altera o prazo" são a mesma regra, não duas."""
    pub = _pub("PORTARIA Nº 14", ementa="Altera o critério e altera o prazo do repasse.")
    assert forca(pub) == 2  # a regra do `altera` e a do `repasse`


def test_forca_soma_o_corpo_quando_ha_cifra_com_milhar(cfg):
    pub = _pub(
        "PORTARIA GM/MS Nº 12.134",
        ementa="Altera a Portaria que habilita estabelecimento especializado.",
        texto="O limite anual será de R$ 25.304.807,91 (vinte e cinco milhões).",
    )
    assert forca(pub) >= 2


def test_forca_ignora_cifra_sem_milhar_no_corpo(cfg):
    pub = _pub(
        "PORTARIA Nº 15",
        ementa="Institui grupo de trabalho sobre prontuário.",
        texto="Valor de Contrapartida: R$ 0,00. Valor unitário do insumo: R$ 12,00.",
    )
    assert forca(pub) == 0


def test_publicacao_sem_regra_alguma_e_mantida(cfg):
    pub = _pub("PORTARIA Nº 13", ementa="Institui grupo de trabalho sobre prontuário.")
    assert len(triar([pub], cfg).mantidas) == 1


@pytest.mark.parametrize(
    "titulo",
    [
        "EXTRATO DE DOAÇÃO Nº 3.618/2026",
        "EXTRATO DE APOSTILAMENTO Nº 4/2026",
        "EXTRATO DE COMODATO Nº 7/2026",
        "EXTRATO DE RESCISÃO Nº 2/2026",
        "EXTRATO DE CESSÃO DE USO Nº 9/2026",
        "EXTRATO DE COOPERAÇÃO TÉCNICA Nº 1/2026",
        "AVISO DE REVOGAÇÃO DE LICITAÇÃO",
        "AVISO DE DISPENSA DE LICITAÇÃO",
        "AVISO DE REABERTURA DE PRAZO",
        "AVISO DE ADIAMENTO",
        "AVISO DE RETIFICAÇÃO",
        "TERMO DE APOSTILAMENTO Nº 3/2026",
        "TERMO DE DOAÇÃO Nº 8/2026",
        "PORTARIA DE PESSOAL Nº 40",
        "PORTARIA Nº 41 DE PROGRESSÃO FUNCIONAL",
        "PORTARIA Nº 42 DE LICENÇA PRÊMIO",
        "PORTARIA Nº 43 DE LICENÇA CAPACITAÇÃO",
        "PORTARIA Nº 44 QUE CONCEDE APOSENTADORIA",
        "PORTARIA Nº 45 QUE CONCEDE PENSÃO POR MORTE",
        "RESOLUÇÃO-RE Nº 3.416",
    ],
)
def test_ruido_de_diario_e_descartado_pelo_titulo(cfg, titulo):
    pub = _pub(titulo)
    triagem = triar([pub], cfg)
    assert triagem.mantidas == ()
    assert triagem.descartadas[0].regra == "descarte"


def test_retificacao_bare_nao_e_mais_descartada(cfg):
    """`retificação` sozinha no `_DESCARTE` violava a decisão do controlador:
    uma retificação de anexo (só o título "Retificação", sem ementa) nunca
    poderia ser resgatada pelo `_FORTE`, que só olha título e ementa. Só
    `aviso de retificação` continua descartando."""
    pub = _pub("Retificação", tipo="Retificação")
    triagem = triar([pub], cfg)
    assert [p.id for p in triagem.mantidas] == [pub.id]


def test_suspensao_nao_e_descartada_pela_regra_de_pensao(cfg):
    """`pensão` sem `\\b` casava dentro de "suspensão"."""
    pub = _pub("Suspensão de convênio")
    triagem = triar([pub], cfg)
    assert [p.id for p in triagem.mantidas] == [pub.id]


def test_teto_nao_corta_publicacao_do_iofmg(cfg):
    """As deliberações CIB-SUS/MG são poucas e carregam o maior valor do dia."""
    cfg.max_itens_dia = 3
    cib = _pub(
        "DELIBERAÇÃO CIB-SUS/MG Nº 5.960",
        ementa="Aprova incorporação de recurso ao Teto MAC do município.",
        fonte="iofmg",
        tipo="DELIBERAÇÃO",
    )
    fraca_mg = _pub(
        "PORTARIA FUNED Nº 67",
        ementa="Institui grupo de trabalho sobre prontuário.",
        fonte="iofmg",
        tipo="PORTARIA",
    )
    forte_dou = _pub("PORTARIA Nº 50", ementa="Habilita leitos e amplia o teto MAC.")
    fraca_a = _pub("PORTARIA Nº 51", ementa="Institui grupo de trabalho sobre prontuário.")
    fraca_b = _pub("PORTARIA Nº 52", ementa="Institui comissão de acompanhamento.")

    triagem = triar([fraca_a, cib, forte_dou, fraca_mg, fraca_b], cfg)

    assert [p.id for p in triagem.mantidas] == [cib.id, forte_dou.id, fraca_mg.id]
    assert {d.id for d in triagem.descartadas} == {fraca_a.id, fraca_b.id}
    assert {d.regra for d in triagem.descartadas} == {"teto"}
    assert triagem.avisos == ("2 itens além do teto de 3 não foram classificados",)


def test_teto_corta_a_forca_zero_antes_da_forca_um(cfg):
    cfg.max_itens_dia = 1
    zero = _pub("PORTARIA Nº 60", ementa="Institui grupo de trabalho sobre prontuário.")
    um = _pub("PORTARIA Nº 61", ementa="Habilita leitos de retaguarda.")
    triagem = triar([zero, um], cfg)
    assert [p.id for p in triagem.mantidas] == [um.id]
    assert triagem.descartadas == (Descarte(zero.id, "teto"),)


def test_teto_menor_que_o_numero_de_protegidas_nao_corta_nenhuma(cfg):
    cfg.max_itens_dia = 1
    mg_a = _pub("DELIBERAÇÃO CIB-SUS/MG Nº 1", fonte="iofmg", tipo="DELIBERAÇÃO")
    mg_b = _pub("DELIBERAÇÃO CIB-SUS/MG Nº 2", fonte="iofmg", tipo="DELIBERAÇÃO")
    dou = _pub("PORTARIA Nº 70", ementa="Institui grupo de trabalho.")
    triagem = triar([mg_a, mg_b, dou], cfg)
    assert {p.id for p in triagem.mantidas} == {mg_a.id, mg_b.id}
    assert triagem.descartadas == (Descarte(dou.id, "teto"),)


def test_teto_corta_os_menos_fortes_e_avisa(cfg):
    cfg.max_itens_dia = 2
    fortes = _pub(
        "DELIBERAÇÃO Nº 20",
        ementa="Deliberação CIB-SUS/MG amplia o teto MAC em R$ 100,00 para custeio.",
    )
    media = _pub("PORTARIA Nº 21", ementa="Habilita leitos de retaguarda.")
    fraca = _pub("PORTARIA Nº 22", ementa="Institui grupo de trabalho sobre prontuário.")
    triagem = triar([fraca, media, fortes], cfg)
    assert [p.id for p in triagem.mantidas] == [fortes.id, media.id]
    assert triagem.descartadas == (Descarte(fraca.id, "teto"),)
    assert triagem.avisos == ("1 itens além do teto de 2 não foram classificados",)


def test_sem_teto_nao_ha_aviso(cfg):
    assert triar([_pub("PORTARIA Nº 30")], cfg).avisos == ()


# ── triar sobre a fixture completa ──────────────────────────────────────
def test_fixture_do_dia_mantem_sete_e_descarta_cinco(cfg, dir_dados):
    carga = carregar(dir_dados, date(2026, 9, 3), ["inlabs", "iofmg"])
    triagem = triar(carga.publicacoes, cfg)

    mantidos = {p.titulo for p in triagem.mantidas}
    assert len(triagem.mantidas) == 7
    assert mantidos == {
        "PORTARIA GM/MS Nº 3.412, DE 2 DE SETEMBRO DE 2026",
        "PORTARIA SAPS/MS Nº 3.418, DE 2 DE SETEMBRO DE 2026",
        "RESOLUÇÃO DE DIRETORIA COLEGIADA - RDC Nº 942, DE 1º DE SETEMBRO DE 2026",
        "EDITAL DE CHAMAMENTO PÚBLICO Nº 12/2026",
        "DELIBERAÇÃO CIB-SUS/MG Nº 4.512, DE 1º DE SETEMBRO DE 2026",
        "RESOLUÇÃO SES Nº 9.120, DE 1º DE SETEMBRO DE 2026",
        "PORTARIA PRE Nº 218, DE 1º DE SETEMBRO DE 2026",
    }
    assert len(triagem.descartadas) == 5
    assert {d.regra for d in triagem.descartadas} == {"descarte"}

    por_id = {p.id: p for p in carga.publicacoes}
    descartados = {por_id[d.id].titulo for d in triagem.descartadas}
    assert descartados == {
        "PORTARIA SE/MS Nº 1.907, DE 2 DE SETEMBRO DE 2026",
        "PORTARIA SE/MS Nº 1.908, DE 2 DE SETEMBRO DE 2026",
        "EXTRATO DE CONTRATO Nº 88/2026",
        "ATA DE REGISTRO DE PREÇOS Nº 45/2026",
        "ATO Nº 512/2026",
    }
