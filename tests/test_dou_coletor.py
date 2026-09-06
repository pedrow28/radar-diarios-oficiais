import json
import logging
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

import pytest
import requests

from radar.core.config import ConfigDOU
from radar.core.erros import FonteIndisponivel, Status
from radar.core.log import configurar_log
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
    return ConfigDOU(orgaos=["Ministério da Saúde"], delta=75, concorrencia=2)


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


def test_escopo_registra_os_orgaos(cfg, storage):
    sessao = SessaoFalsa({"buscar/dou": _html_busca([ITEM], 1), "portaria-1": HTML_PUB})
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))
    assert resultado.escopo["orgaos"] == ["Ministério da Saúde"]
    assert resultado.escopo["subunidades_extra"] == ["Casa Civil"]


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
        orgaos=cfg.orgaos, delta=cfg.delta, concorrencia=cfg.concorrencia,
        baixar_texto_integral=False,
    )
    resultado = FonteDOU(cfg_resumo, storage, sessao).coletar(date(2026, 9, 5))
    assert resultado.escopo["texto_integral"] is False


def test_publicacao_degradada_e_marcada_uma_a_uma(cfg, storage):
    """C6: a coleta vira `parcial`, mas a publicação também precisa dizer."""
    outro = {**ITEM, "urlTitle": "portaria-2", "classPK": "2", "title": "Portaria GM/MS Nº 2"}
    sessao = SessaoFalsa(
        {"buscar/dou": _html_busca([ITEM, outro], 2), "portaria-1": HTML_PUB},
        falhar={"portaria-2"},
    )
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))
    assert resultado.status == Status.PARCIAL
    por_slug = {p.url.rsplit("/", 1)[-1]: p for p in resultado.publicacoes}
    assert por_slug["portaria-1"].origem["texto_integral"] is True
    assert por_slug["portaria-2"].origem["texto_integral"] is False
    assert resultado.escopo["texto_integral"] is True, (
        "o escopo fala da coleta; a marca por publicação é que distingue as duas"
    )


# ── vários órgãos ───────────────────────────────────────────────────────────

MS = "Ministério da Saúde"
PRESIDENCIA = "Presidência da República"
FAZENDA = "Ministério da Fazenda"
PLANEJAMENTO = "Ministério do Planejamento e Orçamento"


def _item(slug: str, hierarquia: str) -> dict:
    return {**ITEM, "urlTitle": slug, "classPK": slug, "hierarchyStr": hierarquia}


class SessaoPorOrgao:
    """Busca stubada por órgão: cada `orgPrin` devolve o seu próprio jsonArray.

    A URL da busca carrega o órgão em `orgPrin`, percent-encoded; é por ele que
    a resposta é escolhida. Sem isso, um cache de bruto compartilhado entre
    órgãos passaria despercebido — cada órgão veria a lista do primeiro.
    """

    def __init__(self, por_orgao: dict[str, list[dict]], falhar: set[str] | None = None):
        self.por_orgao = por_orgao
        self.falhar = falhar or set()
        self.pedidos: list[str] = []

    def get(self, url, timeout=None):
        self.pedidos.append(url)

        class R:
            status_code = 200
            content = b""

        r = R()
        if "buscar/dou" in url:
            for orgao, itens in self.por_orgao.items():
                if f"orgPrin={quote_plus(orgao)}" not in url:
                    continue
                if orgao in self.falhar:
                    raise requests.exceptions.ConnectionError("rede caiu")
                r.content = _html_busca(itens, len(itens))
                return r
            r.content = _html_busca([], 0)
            return r
        r.content = HTML_PUB
        return r


def test_soma_as_publicacoes_dos_orgaos_sem_repetir(storage):
    """(a) Três órgãos, um ato repetido entre dois: seis itens, cinco publicações."""
    repetido = _item("portaria-repetida", f"{MS}/Gabinete do Ministro")
    sessao = SessaoPorOrgao(
        {
            MS: [
                _item("ms-1", f"{MS}/Gabinete do Ministro"),
                _item("ms-2", f"{MS}/Agência Nacional de Vigilância Sanitária"),
                repetido,
            ],
            FAZENDA: [_item("fz-1", f"{FAZENDA}/Secretaria Especial"), repetido],
            PLANEJAMENTO: [_item("pl-1", f"{PLANEJAMENTO}/Secretaria de Orçamento")],
        }
    )
    cfg = ConfigDOU(orgaos=[MS, FAZENDA, PLANEJAMENTO], delta=75, concorrencia=2)
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))

    assert resultado.status == Status.OK
    assert resultado.avisos == []
    slugs = sorted(p.url.rsplit("/", 1)[-1] for p in resultado.publicacoes)
    assert slugs == ["fz-1", "ms-1", "ms-2", "pl-1", "portaria-repetida"]
    assert resultado.escopo["orgaos"] == [MS, FAZENDA, PLANEJAMENTO]


def test_cada_orgao_tem_o_seu_proprio_bruto_em_disco(storage):
    """Um nome de arquivo só faria o 2º órgão reler a busca do 1º."""
    sessao = SessaoPorOrgao(
        {MS: [_item("ms-1", f"{MS}/Gabinete")], FAZENDA: [_item("fz-1", f"{FAZENDA}/Secretaria")]}
    )
    cfg = ConfigDOU(orgaos=[MS, FAZENDA], delta=75, concorrencia=2)
    FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))

    buscas = sorted(p.name for p in (storage.dir_raw / "2026-09-04" / "dou").glob("busca-*"))
    assert len(buscas) == 2, buscas
    assert all("p1" in nome for nome in buscas)


def test_presidencia_entra_so_pela_subunidade_configurada(storage):
    """(b) A Presidência assina o Executivo inteiro; só a Casa Civil interessa."""
    sessao = SessaoPorOrgao(
        {
            PRESIDENCIA: [
                _item("casa-civil-1", f"{PRESIDENCIA}/Casa Civil"),
                _item("secretaria-geral-1", f"{PRESIDENCIA}/Secretaria-Geral"),
            ]
        }
    )
    cfg = ConfigDOU(orgaos=[PRESIDENCIA], subunidades_extra=["Casa Civil"], concorrencia=2)
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))

    slugs = [p.url.rsplit("/", 1)[-1] for p in resultado.publicacoes]
    assert slugs == ["casa-civil-1"]


def test_todos_os_orgaos_sem_publicacao_e_vazio_sem_aviso(storage):
    """(c) Nem toda pasta publica todo dia; isso não é falha."""
    sessao = SessaoPorOrgao({MS: [], FAZENDA: [], PLANEJAMENTO: []})
    cfg = ConfigDOU(orgaos=[MS, FAZENDA, PLANEJAMENTO], concorrencia=2)
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 6))

    assert resultado.status == Status.VAZIO
    assert resultado.avisos == []
    assert resultado.publicacoes == []


def test_um_orgao_sem_publicacao_nao_vira_aviso(storage):
    """A Fazenda calada num dia em que a Saúde publicou é rotina, não avaria."""
    sessao = SessaoPorOrgao({MS: [_item("ms-1", f"{MS}/Gabinete")], FAZENDA: []})
    cfg = ConfigDOU(orgaos=[MS, FAZENDA], concorrencia=2)
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))

    assert resultado.status == Status.OK
    assert resultado.avisos == []
    assert len(resultado.publicacoes) == 1


def test_falha_de_rede_em_um_orgao_vira_parcial_nomeando_o_orgao(storage):
    """(d) O dia continua aproveitável, mas quem caiu precisa aparecer."""
    sessao = SessaoPorOrgao(
        {MS: [_item("ms-1", f"{MS}/Gabinete")], FAZENDA: []}, falhar={FAZENDA}
    )
    cfg = ConfigDOU(orgaos=[MS, FAZENDA], concorrencia=2)
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))

    assert resultado.status == Status.PARCIAL
    assert len(resultado.publicacoes) == 1
    assert any(FAZENDA in aviso for aviso in resultado.avisos), resultado.avisos


def test_falha_em_todos_os_orgaos_propaga_como_indisponivel(storage):
    """(e) Fonte fora do ar é `erro` (exit 2), não dia sem publicação."""
    sessao = SessaoPorOrgao({MS: [], FAZENDA: []}, falhar={MS, FAZENDA})
    cfg = ConfigDOU(orgaos=[MS, FAZENDA], concorrencia=2)
    with pytest.raises(FonteIndisponivel) as erro:
        FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))
    assert MS in str(erro.value) and FAZENDA in str(erro.value)


def test_encontrou_e_nada_passou_no_filtro_vira_parcial(storage):
    """Escopo que descarta tudo pode ser hierarquia renomeada na fonte.

    Reportar `vazio` calaria o filtro quebrado para sempre — é o mesmo perigo
    que o INLABS trata em "nada no escopo".
    """
    sessao = SessaoPorOrgao(
        {PRESIDENCIA: [_item("secretaria-geral-1", f"{PRESIDENCIA}/Secretaria-Geral")]}
    )
    cfg = ConfigDOU(orgaos=[PRESIDENCIA], subunidades_extra=["Casa Civil"], concorrencia=2)
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))

    assert resultado.status == Status.PARCIAL
    assert resultado.publicacoes == []
    assert resultado.avisos


def test_log_diz_quantas_publicacoes_vieram_de_cada_orgao(storage):
    """Sem isso, um órgão que emudeceu por mudança de nome passa em branco."""
    sessao = SessaoPorOrgao(
        {MS: [_item("ms-1", f"{MS}/Gabinete"), _item("ms-2", f"{MS}/Gabinete")], FAZENDA: []}
    )
    cfg = ConfigDOU(orgaos=[MS, FAZENDA], concorrencia=2)
    logger = configurar_log()
    linhas: list[str] = []

    class Coletor(logging.Handler):
        def emit(self, registro: logging.LogRecord) -> None:
            linhas.append(registro.getMessage())

    handler = Coletor(level=logging.INFO)
    logger.addHandler(handler)
    try:
        FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))
    finally:
        logger.removeHandler(handler)

    assert any(MS in linha and "2" in linha for linha in linhas), linhas
    assert any(FAZENDA in linha and "0" in linha for linha in linhas), linhas


def test_lista_de_orgaos_vazia_nao_passa_por_dia_sem_publicacao(storage):
    """Config sem órgão nenhum coletaria nada em silêncio, saindo 0."""
    cfg = ConfigDOU(orgaos=[], concorrencia=2)
    with pytest.raises(ValueError):
        FonteDOU(cfg, storage, SessaoPorOrgao({})).coletar(date(2026, 9, 4))
