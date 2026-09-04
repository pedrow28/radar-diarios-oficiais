import json
from datetime import date
from pathlib import Path

import pytest
import requests

from radar.core.config import ConfigDOU
from radar.core.erros import FonteIndisponivel, Status
from radar.core.storage import Storage
from radar.fontes.dou.busca import ID_BLOCO_JSON
from radar.fontes.dou.coletor import FonteDOU


def _html_busca(itens: list[dict], total: int) -> bytes:
    bloco = json.dumps({"jsonArray": itens})
    return (
        f"<html><p>{total} resultados</p>"
        f'<script id="{ID_BLOCO_JSON}" type="application/json">{bloco}</script></html>'
    ).encode("iso-8859-1")


ITEM = {
    "pubName": "DO1",
    "artType": "Portaria",
    "hierarchyStr": "Ministério da Saúde/Gabinete do Ministro",
    "urlTitle": "portaria-1",
    "title": "Portaria GM/MS Nº 1, DE 3 DE setembro DE 2026",
    "content": "resumo truncado ...",
    "editionNumber": "168",
    "numberPage": "10",
    "classPK": "1",
}

HTML_PUB = (
    '<html><div class="texto-dou">'
    '<p class="identifica">Portaria GM/MS Nº 1</p>'
    '<p class="ementa">Faz algo relevante.</p>'
    '<p class="dou-paragraph">Art. 1º Fica estabelecido o repasse de R$ 100.000,00.</p>'
    "</div></html>"
).encode("utf-8")


class SessaoFalsa:
    def __init__(self, por_url: dict, falhar: set[str] | None = None):
        self.por_url = por_url
        self.falhar = falhar or set()
        self.pedidos: list[str] = []

    def get(self, url, timeout=None):
        self.pedidos.append(url)
        if any(f in url for f in self.falhar):
            # requests.exceptions.ConnectionError, não a builtin: só a primeira é
            # RequestException, que é o que `obter_bytes` converte em FonteIndisponivel.
            raise requests.exceptions.ConnectionError("rede caiu")

        class R:
            status_code = 200
            content = b""

        r = R()
        for chave, corpo in self.por_url.items():
            if chave in url:
                r.content = corpo
                return r
        r.status_code = 404
        return r


@pytest.fixture
def storage(tmp_path: Path):
    s = Storage(tmp_path / "data")
    yield s
    s.fechar()


@pytest.fixture
def cfg() -> ConfigDOU:
    return ConfigDOU(orgao="Ministério da Saúde", delta=75, concorrencia=2)


def test_coleta_completa_com_texto_integral(cfg, storage):
    sessao = SessaoFalsa({"buscar/dou": _html_busca([ITEM], 1), "portaria-1": HTML_PUB})
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))
    assert resultado.status == Status.OK
    assert len(resultado.publicacoes) == 1
    assert "100.000,00" in resultado.publicacoes[0].texto
    assert resultado.avisos == []


def test_dia_sem_publicacoes_e_vazio_nao_erro(cfg, storage):
    sessao = SessaoFalsa({"buscar/dou": _html_busca([], 0)})
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 6))
    assert resultado.status == Status.VAZIO
    assert resultado.publicacoes == []


def test_falha_no_texto_integral_vira_parcial_nao_erro(cfg, storage):
    sessao = SessaoFalsa({"buscar/dou": _html_busca([ITEM], 1)}, falhar={"portaria-1"})
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))
    assert resultado.status == Status.PARCIAL
    assert len(resultado.publicacoes) == 1
    assert resultado.avisos


def test_falha_na_listagem_propaga_como_indisponivel(cfg, storage):
    sessao = SessaoFalsa({}, falhar={"buscar/dou"})
    with pytest.raises(FonteIndisponivel):
        FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))


def test_salva_bruto_e_reusa_no_reprocessamento(cfg, storage):
    sessao = SessaoFalsa({"buscar/dou": _html_busca([ITEM], 1), "portaria-1": HTML_PUB})
    fonte = FonteDOU(cfg, storage, sessao)
    fonte.coletar(date(2026, 9, 4))
    pedidos_primeira = len(sessao.pedidos)
    fonte.coletar(date(2026, 9, 4))
    assert len(sessao.pedidos) == pedidos_primeira, "deveria reusar o cache raw"


def test_forcar_ignora_o_cache(cfg, storage):
    sessao = SessaoFalsa({"buscar/dou": _html_busca([ITEM], 1), "portaria-1": HTML_PUB})
    fonte = FonteDOU(cfg, storage, sessao)
    fonte.coletar(date(2026, 9, 4))
    pedidos = len(sessao.pedidos)
    fonte.coletar(date(2026, 9, 4), forcar=True)
    assert len(sessao.pedidos) > pedidos


def test_escopo_registra_o_orgao(cfg, storage):
    sessao = SessaoFalsa({"buscar/dou": _html_busca([ITEM], 1), "portaria-1": HTML_PUB})
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))
    assert resultado.escopo["orgao"] == "Ministério da Saúde"


def test_texto_vazio_da_pagina_vira_parcial_com_aviso(cfg, storage):
    """Estrutura da pagina mudada devolve vazio sem estourar.

    Isso nao pode passar por coleta completa: o agente consumidor leria o
    resumo truncado achando que e o inteiro teor.
    """
    sessao = SessaoFalsa({
        "buscar/dou": _html_busca([ITEM], 1),
        "portaria-1": b"<html><body>estrutura mudou, sem texto-dou</body></html>",
    })
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))
    assert resultado.status == Status.PARCIAL
    assert any("vazio" in a.lower() for a in resultado.avisos)


def test_escopo_registra_se_o_texto_integral_foi_buscado(cfg, storage):
    """So lendo o JSON o consumidor precisa saber se `texto` e inteiro teor."""
    sessao = SessaoFalsa({"buscar/dou": _html_busca([ITEM], 1), "portaria-1": HTML_PUB})
    assert FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4)).escopo["texto_integral"] is True

    cfg_resumo = ConfigDOU(
        orgao=cfg.orgao, delta=cfg.delta, concorrencia=cfg.concorrencia,
        baixar_texto_integral=False,
    )
    resultado = FonteDOU(cfg_resumo, storage, sessao).coletar(date(2026, 9, 5))
    assert resultado.escopo["texto_integral"] is False
