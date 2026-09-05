import dataclasses
import json
from datetime import date, datetime, timezone

import pytest

from boletim.carga import carregar
from boletim.classifica import classificar, item_de_resposta
from boletim.config import ConfigBoletim
from boletim.llm import LLMFalso, LLMIndisponivel
from boletim.prefiltro import triar
from radar.core.modelos import Publicacao, gerar_id


def _pub(n: int) -> Publicacao:
    url = f"https://exemplo/{n}"
    titulo = f"PORTARIA Nº {n}"
    return Publicacao(
        id=gerar_id("inlabs", date(2026, 9, 3), url, titulo),
        fonte="inlabs",
        data_publicacao=date(2026, 9, 3),
        coletado_em=datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc),
        orgao="Ministério da Saúde",
        unidade=None,
        secao="1",
        pagina=n,
        edicao="169",
        tipo="Portaria",
        numero=str(n),
        titulo=titulo,
        ementa=f"Ementa da portaria {n}.",
        texto=f"Texto da portaria {n}.",
        url=url,
        origem={},
    )


def _resposta(pub: Publicacao, **kw) -> dict:
    base = {
        "id": pub.id,
        "categoria": "A",
        "relevancia": 3,
        "resumo": f"resumo de {pub.titulo}",
        "por_que_importa": "importa muito",
        "valor_brl": 1000.0,
        "entes": ["Município de Manhuaçu"],
        "tags": ["habilitação"],
    }
    base.update(kw)
    return base


def _lote(*respostas: dict) -> dict:
    return {"itens": list(respostas)}


@pytest.fixture
def cfg() -> ConfigBoletim:
    config = ConfigBoletim()
    config.lote = 12
    config.tentativas_llm = 2
    return config


# ── item_de_resposta ────────────────────────────────────────────────────
def test_item_de_resposta_junta_publicacao_e_juizo_do_llm():
    pub = _pub(1)
    item = item_de_resposta(pub, _resposta(pub, categoria="B", relevancia=2))
    assert item.id == pub.id
    assert item.titulo == pub.titulo
    assert item.orgao == pub.orgao
    assert item.url == pub.url
    assert item.data_publicacao == pub.data_publicacao
    assert item.categoria == "B"
    assert item.relevancia == 2
    assert item.entes == ("Município de Manhuaçu",)
    assert item.tags == ("habilitação",)
    assert item.fallback is False


# ── caminho feliz ───────────────────────────────────────────────────────
def test_lote_unico_classifica_os_sete_itens_da_fixture(cfg, dir_fixtures):
    carga = carregar(dir_fixtures / "boletim", date(2026, 9, 3), ["inlabs", "iofmg"])
    mantidas = triar(carga.publicacoes, cfg).mantidas
    lote1 = json.loads(
        (dir_fixtures / "boletim" / "llm" / "lote1.json").read_text(encoding="utf-8")
    )
    llm = LLMFalso({"lote-0": lote1})

    itens, avisos = classificar(mantidas, llm, cfg)

    assert len(itens) == 7
    assert avisos == []
    assert len(llm.chamadas) == 1
    assert llm.chamadas[0][0] == "lote-0"
    assert [i.categoria for i in itens] == ["A", "B", "B", "C", "A", "B", "D"]
    assert not any(i.fallback for i in itens)


def test_itens_saem_na_ordem_das_publicacoes_mantidas(cfg):
    pubs = [_pub(1), _pub(2), _pub(3)]
    llm = LLMFalso(
        {"lote-0": _lote(_resposta(pubs[2]), _resposta(pubs[0]), _resposta(pubs[1]))}
    )
    itens, _ = classificar(pubs, llm, cfg)
    assert [i.id for i in itens] == [p.id for p in pubs]


def test_lotes_respeitam_o_tamanho_configurado(cfg):
    cfg.lote = 2
    pubs = [_pub(n) for n in range(1, 5)]
    llm = LLMFalso(
        {
            "lote-0": _lote(_resposta(pubs[0]), _resposta(pubs[1])),
            "lote-1": _lote(_resposta(pubs[2]), _resposta(pubs[3])),
        }
    )
    itens, avisos = classificar(pubs, llm, cfg)
    assert len(itens) == 4
    assert avisos == []
    assert [c[0] for c in llm.chamadas] == ["lote-0", "lote-1"]


# ── tentativas, bisseção e fallback ─────────────────────────────────────
def test_resposta_invalida_na_primeira_tentativa_e_valida_na_segunda(cfg):
    pubs = [_pub(1)]
    llm = LLMFalso(
        {"lote-0": [{"itens": [{"id": pubs[0].id, "categoria": "Z"}]}, _lote(_resposta(pubs[0]))]}
    )
    itens, avisos = classificar(pubs, llm, cfg)
    assert len(itens) == 1
    assert itens[0].fallback is False
    assert len(llm.chamadas) == 2
    assert any("inválida" in a for a in avisos)


def test_lote_incompleto_e_reprocessado_por_bisseccao(cfg):
    pubs = [_pub(n) for n in range(1, 5)]
    metade = _lote(_resposta(pubs[0]), _resposta(pubs[1]))
    llm = LLMFalso(
        {
            "lote-0": [
                metade,
                metade,
                _lote(_resposta(pubs[2])),
                _lote(_resposta(pubs[3])),
            ]
        }
    )
    itens, avisos = classificar(pubs, llm, cfg)

    assert [i.id for i in itens] == [p.id for p in pubs]
    assert not any(i.fallback for i in itens)
    assert len(llm.chamadas) == 4
    # A bisseção só reenvia o que faltou: os dois últimos vão sozinhos.
    assert pubs[0].id not in llm.chamadas[2][2]
    assert pubs[2].id in llm.chamadas[2][2]


def test_item_unico_restante_recebe_retentativa_solo(cfg):
    pubs = [_pub(1), _pub(2), _pub(3)]
    parcial = _lote(_resposta(pubs[0]), _resposta(pubs[1]))
    llm = LLMFalso({"lote-0": [parcial, parcial, _lote(_resposta(pubs[2]))]})

    itens, avisos = classificar(pubs, llm, cfg)

    assert [i.id for i in itens] == [p.id for p in pubs]
    assert not any(i.fallback for i in itens)
    assert len(llm.chamadas) == 3
    # A terceira chamada é a retentativa solo do único item que sobrou.
    assert pubs[0].id not in llm.chamadas[2][2]
    assert pubs[2].id in llm.chamadas[2][2]


def test_item_que_o_llm_nunca_devolve_vira_fallback_d(cfg):
    pubs = [_pub(1), _pub(2)]
    llm = LLMFalso({"lote-0": _lote(_resposta(pubs[0]))})
    itens, avisos = classificar(pubs, llm, cfg)

    assert len(itens) == 2
    orfao = itens[1]
    assert orfao.categoria == "D"
    assert orfao.relevancia == 1
    assert orfao.resumo == "Ementa da portaria 2."
    assert orfao.fallback is True
    assert "1 itens sem classificação por LLM (fallback D)" in avisos


def test_fallback_usa_o_titulo_quando_nao_ha_ementa(cfg):
    pub = _pub(1)
    sem_ementa = dataclasses.replace(pub, ementa=None)
    llm = LLMFalso({"lote-0": _lote()})
    itens, _ = classificar([sem_ementa], llm, cfg)
    assert itens[0].resumo == sem_ementa.titulo


def test_id_estranho_na_resposta_e_ignorado_com_aviso(cfg):
    pubs = [_pub(1)]
    intruso = dict(_resposta(pubs[0]), id="idqueninguempediu")
    llm = LLMFalso({"lote-0": _lote(_resposta(pubs[0]), intruso)})
    itens, avisos = classificar(pubs, llm, cfg)

    assert len(itens) == 1
    assert itens[0].id == pubs[0].id
    assert any("idqueninguempediu" in a for a in avisos)


# ── LLM fora do ar ──────────────────────────────────────────────────────
def test_llm_indisponivel_na_primeira_chamada_de_todas_propaga(cfg):
    with pytest.raises(LLMIndisponivel):
        classificar([_pub(1)], LLMFalso({}), cfg)


def test_llm_que_cai_depois_do_primeiro_lote_vira_fallback(cfg):
    cfg.lote = 1
    pubs = [_pub(1), _pub(2)]
    llm = LLMFalso({"lote-0": _lote(_resposta(pubs[0]))})
    itens, avisos = classificar(pubs, llm, cfg)

    assert len(itens) == 2
    assert itens[0].fallback is False
    assert itens[1].fallback is True
    assert "1 itens sem classificação por LLM (fallback D)" in avisos


def test_sem_publicacoes_nao_chama_o_llm(cfg):
    llm = LLMFalso({})
    assert classificar([], llm, cfg) == ([], [])
    assert llm.chamadas == []
