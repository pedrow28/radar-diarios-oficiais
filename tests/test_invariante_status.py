"""Invariante transversal do contrato de saída (C4).

`vazio` significa, para o agente que consome o JSON, "não houve edição, siga
sem alarme". Um `Resultado` que carrega aviso tem algo a relatar e portanto é
`parcial` — status `vazio` com aviso é quebra de extração disfarçada de
domingo, e o agente nunca alerta ninguém.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from radar.core.config import ConfigDOU, ConfigIOFMG
from radar.core.erros import Status
from radar.core.storage import Storage
from radar.fontes.dou.busca import ID_BLOCO_JSON
from radar.fontes.dou.coletor import FonteDOU
from radar.fontes.iofmg.coletor import FonteIOFMG

DIA = date(2026, 9, 3)


def _html_busca(itens: list[dict], total: int, palavra: str = "resultados") -> bytes:
    bloco = json.dumps({"jsonArray": itens})
    return (
        f"<html><p>{total} {palavra}</p>"
        f'<script id="{ID_BLOCO_JSON}" type="application/json">{bloco}</script></html>'
    ).encode("utf-8")


class SessaoDOU:
    def __init__(self, corpo: bytes) -> None:
        self.corpo = corpo

    def get(self, url, timeout=None):
        class R:
            status_code = 200

        r = R()
        r.content = self.corpo
        return r


class SessaoIOFMG(SessaoDOU):
    pass


@pytest.fixture
def storage(tmp_path: Path):
    s = Storage(tmp_path / "data")
    yield s
    s.fechar()


def _cfg_dou() -> ConfigDOU:
    return ConfigDOU(orgao="Ministério da Saúde", delta=75, concorrencia=1)


def _cfg_iofmg() -> ConfigIOFMG:
    return ConfigIOFMG(
        caderno="Diário do Executivo",
        secao="Secretaria de Estado de Saúde",
        tipos_publicacao=["PORTARIA", "RESOLUÇÃO"],
    )


def _edicao(secoes: list[dict]) -> bytes:
    return json.dumps(
        {
            "dados": {
                "cadernos": [
                    {"id": 1, "descricao": "Diário do Executivo", "secoes": secoes}
                ],
                "arquivoCadernoPrincipal": {"totalPaginas": 3, "arquivo": ""},
            }
        }
    ).encode("utf-8")


def _cenarios(storage: Storage, dir_fixtures: Path):
    """Um `Resultado` de cada caminho sem publicação das duas fontes."""
    # DOU: dia sem publicação — vazio legítimo.
    yield "dou/sem publicação", FonteDOU(
        _cfg_dou(), storage, SessaoDOU(_html_busca([], 0))
    ).coletar(date(2026, 9, 6))

    # DOU: layout mudado, total ilegível e nada no jsonArray da última página.
    yield "dou/total ilegível", FonteDOU(
        _cfg_dou(), storage, SessaoDOU(_html_busca([], 0, palavra="registros"))
    ).coletar(date(2026, 9, 7))

    # DOU: total informado mas nenhum item devolvido — coleta incompleta.
    yield "dou/total sem itens", FonteDOU(
        _cfg_dou(), storage, SessaoDOU(_html_busca([], 10))
    ).coletar(date(2026, 9, 8))

    # IOF-MG: dia sem edição — vazio legítimo.
    yield "iofmg/sem edição", FonteIOFMG(
        _cfg_iofmg(), storage, SessaoIOFMG(json.dumps({"dados": None}).encode())
    ).coletar(date(2026, 9, 6))

    # IOF-MG: há edição, mas o órgão alvo não está no índice.
    yield "iofmg/órgão ausente", FonteIOFMG(
        _cfg_iofmg(), storage,
        SessaoIOFMG(_edicao([{"descricao": "Governo do Estado", "paginaInicial": 1}])),
    ).coletar(date(2026, 9, 9))

    # IOF-MG: órgão localizado, PDF real, nenhum tipo configurado casa.
    dia = date(2026, 9, 10)
    storage.salvar_raw(
        dia, "iofmg", "edicao.json",
        _edicao([{"descricao": "Secretaria de Estado de Saúde", "paginaInicial": 1}]),
    )
    storage.salvar_raw(
        dia, "iofmg", "caderno.pdf",
        (dir_fixtures / "iofmg" / "caderno-2026-09-03-ses.pdf").read_bytes(),
    )
    cfg_sem_tipos = ConfigIOFMG(
        caderno="Diário do Executivo",
        secao="Secretaria de Estado de Saúde",
        tipos_publicacao=["INEXISTENTE"],
    )
    yield "iofmg/nada segmentado", FonteIOFMG(
        cfg_sem_tipos, storage, SessaoIOFMG(b"")
    ).coletar(dia)


def test_nenhum_resultado_sai_vazio_com_aviso(storage, dir_fixtures):
    for nome, resultado in _cenarios(storage, dir_fixtures):
        if resultado.avisos:
            assert resultado.status == Status.PARCIAL, (
                f"{nome}: tem aviso {resultado.avisos!r} e mesmo assim "
                f"status={resultado.status}"
            )
        if resultado.status == Status.VAZIO:
            assert resultado.avisos == [], f"{nome}: vazio não pode carregar aviso"


def test_quebra_de_extracao_do_iofmg_nao_passa_por_domingo(storage, dir_fixtures):
    """Antes: "órgão localizado mas nada segmentado" saía como `vazio`, exit 0."""
    por_nome = dict(_cenarios(storage, dir_fixtures))
    assert por_nome["iofmg/nada segmentado"].status == Status.PARCIAL
    assert por_nome["iofmg/órgão ausente"].status == Status.PARCIAL
    assert por_nome["iofmg/sem edição"].status == Status.VAZIO
    assert por_nome["iofmg/sem edição"].avisos == []


def test_layout_mudado_no_dou_nao_passa_por_dia_sem_publicacao(storage, dir_fixtures):
    por_nome = dict(_cenarios(storage, dir_fixtures))
    assert por_nome["dou/sem publicação"].status == Status.VAZIO
    assert por_nome["dou/total sem itens"].status == Status.PARCIAL


def test_status_vazio_sempre_significa_exit_zero_sem_alarme(storage, dir_fixtures):
    """`vazio` → exit 0; `parcial` → exit 1. Sem aviso mudo em exit 0."""
    from radar.core.erros import status_para_exit

    for nome, resultado in _cenarios(storage, dir_fixtures):
        exit_code = status_para_exit(resultado.status)
        assert not (exit_code == 0 and resultado.avisos), nome
