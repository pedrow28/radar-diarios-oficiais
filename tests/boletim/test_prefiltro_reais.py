"""Regressões do prefiltro contra publicações reais da rodada 31/08–04/09/2026.

Os oito casos do fixture `reais/publicacoes.json` são os que a verificação da
semana (`semana-report.md`, seções 5.2 a 5.7) apontou como errados: ruído que
sobrevivia por um termo forte no corpo, e um ato relevante que saía com força
zero. Cada teste cita o `id` real, para que uma regressão futura seja rastreável
até o Diário que a produziu.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from boletim.carga import carregar
from boletim.config import ConfigBoletim
from boletim.prefiltro import _DESCARTE, _alvo, forca, triar
from radar.core.modelos import Publicacao, publicacao_de_dict

_RAIZ = Path(__file__).resolve().parents[2]
_SEMANA = _RAIZ / ".superpowers/sdd/seguinte-constru-mos-esse-projeto-snazzy-hejlsberg/semana"
_DIAS_REAIS = ("2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04")

# Teto observado na rodada real; o agregado precisa dele para valer alguma coisa.
_TETO_REAL = 120


_FIXTURE_REAIS = (
    Path(__file__).resolve().parents[1] / "fixtures" / "boletim" / "reais" / "publicacoes.json"
)


@pytest.fixture(scope="module")
def reais() -> dict[str, Publicacao]:
    bruto = json.loads(_FIXTURE_REAIS.read_text(encoding="utf-8"))
    return {
        p["id"]: publicacao_de_dict(p, date.fromisoformat(p["data_publicacao"]))
        for p in bruto["publicacoes"]
    }


@pytest.fixture
def cfg() -> ConfigBoletim:
    return ConfigBoletim()


def _veredito(pub: Publicacao, cfg: ConfigBoletim) -> str:
    triagem = triar([pub], cfg)
    return "mantida" if triagem.mantidas else triagem.descartadas[0].regra


# ── o que precisa passar ────────────────────────────────────────────────
def test_portaria_da_tabela_sus_deixa_de_sair_com_forca_zero(reais, cfg):
    """`2badc4fb9af2a751`: o único ato relevante perdido no teto de 31/08."""
    pub = reais["2badc4fb9af2a751"]
    assert _veredito(pub, cfg) == "mantida"
    assert forca(pub) >= 1


def test_deliberacao_cib_de_teto_mac_e_forte_e_do_iofmg(reais, cfg):
    """`349443f3076ab55a`: R$ 28,1 mi de Teto MAC para Manhuaçu."""
    pub = reais["349443f3076ab55a"]
    assert pub.fonte == "iofmg"
    assert _veredito(pub, cfg) == "mantida"
    assert forca(pub) >= 2


def test_deliberacao_do_iofmg_sobrevive_ao_teto(reais, cfg):
    """Protegida do corte mesmo com o teto no menor valor possível."""
    cfg.max_itens_dia = 1
    cib = reais["349443f3076ab55a"]
    ruido = reais["5c87ec9922084fcd"]
    forte = reais["9681323633188e26"]
    triagem = triar([ruido, forte, cib], cfg)
    assert cib.id in {p.id for p in triagem.mantidas}


def test_rdc_que_altera_regra_e_mantida_pelo_titulo(reais, cfg):
    """`8f89654ecee2aac7`: habilitação e credenciamento estão na ementa."""
    pub = reais["8f89654ecee2aac7"]
    assert _veredito(pub, cfg) == "mantida"
    assert forca(pub) >= 1


def test_habilitacao_com_cifra_real_soma_titulo_e_corpo(reais, cfg):
    """`9681323633188e26`: `habilita` na ementa e R$ 25.304.807,91 no corpo."""
    pub = reais["9681323633188e26"]
    assert _veredito(pub, cfg) == "mantida"
    assert forca(pub) >= 2


def test_retificacao_de_anexo_sem_ementa_e_mantida(reais, cfg):
    """`f7077106b63989be`: retificação do Anexo XIV de uma portaria de
    habilitação, 01/09. Título e tipo são literalmente "Retificação", sem
    ementa — o `_FORTE` nunca teria como resgatar esse item (R1 só olha
    título e ementa). A regra `retificação` sozinha no `_DESCARTE` violava a
    decisão do controlador ao descartar atos assim sem chance de resgate."""
    pub = reais["f7077106b63989be"]
    assert _veredito(pub, cfg) == "mantida"


# ── o que precisa cair ──────────────────────────────────────────────────
@pytest.mark.parametrize(
    "id_real",
    [
        pytest.param("8c8731bbce27cf8c", id="resolucao-re-com-rdc-no-preambulo"),
        pytest.param("5c87ec9922084fcd", id="extrato-de-doacao"),
        pytest.param("c9fc835cc7da4e0e", id="extrato-de-contrato-com-edital-no-corpo"),
        pytest.param("dcd548f2f702c56a", id="extrato-de-termo-aditivo-com-cifra"),
    ],
)
def test_ruido_real_nao_e_mais_resgatado_pelo_corpo(reais, cfg, id_real):
    assert _veredito(reais[id_real], cfg) == "descarte"


# ── agregado sobre os cinco dias reais ──────────────────────────────────
def _dias_disponiveis() -> list[date]:
    if not (_SEMANA / "normalized").is_dir():
        return []
    return [
        date.fromisoformat(d)
        for d in _DIAS_REAIS
        if (_SEMANA / "normalized" / d).is_dir()
    ]


def test_semana_real_manda_menos_de_dez_por_cento_de_ruido_ao_llm(cfg):
    """O ruído resgatado pelo corpo era 44% das mantidas da semana."""
    dias = _dias_disponiveis()
    if not dias:
        pytest.skip("dados da rodada real não estão neste checkout")

    cfg.max_itens_dia = _TETO_REAL
    for data in dias:
        carga = carregar(_SEMANA, data, ["dou", "iofmg"])
        triagem = triar(carga.publicacoes, cfg)
        ruido = [p for p in triagem.mantidas if _DESCARTE.search(_alvo(p))]
        proporcao = len(ruido) / max(len(triagem.mantidas), 1)
        assert proporcao < 0.10, f"{data}: {len(ruido)}/{len(triagem.mantidas)} de ruído"


def test_semana_real_nunca_estoura_o_teto_em_silencio(cfg):
    dias = _dias_disponiveis()
    if not dias:
        pytest.skip("dados da rodada real não estão neste checkout")

    cfg.max_itens_dia = _TETO_REAL
    for data in dias:
        carga = carregar(_SEMANA, data, ["dou", "iofmg"])
        triagem = triar(carga.publicacoes, cfg)
        if len(triagem.mantidas) <= _TETO_REAL:
            continue
        # Passar do teto só é aceitável por causa das protegidas do IOF-MG, e
        # nunca em silêncio.
        assert triagem.avisos, data
        do_dou = [p for p in triagem.mantidas if p.fonte != "iofmg"]
        assert len(do_dou) <= _TETO_REAL, data
