from datetime import date, datetime, timezone

import pytest

from boletim.carga import carregar
from boletim.config import ConfigBoletim
from boletim.prefiltro import Descarte, entes_candidatos, triar, valores_brl
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


def test_retencao_forte_pode_vir_do_texto_alem_da_ementa(cfg):
    pub = _pub(
        "PORTARIA Nº 12",
        ementa="Concede férias regulamentares.",
        texto="No mesmo ato fica ampliado o teto MAC da regional em R$ 10.000,00.",
    )
    assert len(triar([pub], cfg).mantidas) == 1


def test_publicacao_sem_regra_alguma_e_mantida(cfg):
    pub = _pub("PORTARIA Nº 13", ementa="Institui grupo de trabalho sobre prontuário.")
    assert len(triar([pub], cfg).mantidas) == 1


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
