import gzip
import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import pytest

from radar.core.config import ConfigIOFMG
from radar.core.erros import Status
from radar.core.storage import Storage
from radar.fontes.iofmg.coletor import FonteIOFMG
from radar.fontes.iofmg.normaliza import normalizar, url_pagina
from radar.fontes.iofmg.segmenta import Bruto

QUANDO = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
DIA = date(2026, 9, 3)
BRUTO = Bruto(
    tipo="RESOLUÇÃO",
    numero="11.606",
    titulo="RESOLUÇÃO SES Nº 11.606, 02 DE SETEMBRO DE 2026.",
    texto="O Secretário de Estado de Saúde resolve aprovar o repasse.",
    pagina=16,
)


def test_url_da_pagina_usa_o_id_do_caderno_da_edicao():
    url = url_pagina(DIA, 330896, 16)
    assert "330896" in unquote(url)
    assert "326074" not in url


def test_sem_id_de_caderno_nao_emite_link():
    """Link errado e pior que link ausente: o agente cita e ninguem percebe."""
    assert url_pagina(DIA, None, 16) is None


def test_normaliza_preenche_procedencia():
    pub = normalizar(BRUTO, DIA, QUANDO, 330896, "Secretaria de Estado de Saúde")
    assert pub.fonte == "iofmg"
    assert pub.orgao == "Secretaria de Estado de Saúde"
    assert pub.tipo == "RESOLUÇÃO"
    assert pub.numero == "11.606"
    assert pub.pagina == 16
    assert pub.texto.startswith("O Secretário")


def test_secao_e_none_no_iofmg():
    """IOF-MG nao tem o conceito de Secao 1/2/3 do DOU."""
    assert normalizar(BRUTO, DIA, QUANDO, 330896, "SES").secao is None


def test_url_ausente_nao_quebra_normalizacao():
    pub = normalizar(BRUTO, DIA, QUANDO, None, "SES")
    assert pub.url == ""
    assert pub.id


class SessaoFalsa:
    def __init__(self, corpo: bytes):
        self.corpo = corpo
        self.pedidos: list[str] = []

    def get(self, url, timeout=None):
        self.pedidos.append(url)

        class R:
            status_code = 200

        r = R()
        r.content = self.corpo
        return r


@pytest.fixture
def resposta_api(dir_fixtures: Path) -> bytes:
    """Reconstroi a resposta real: metadados + envelope PKCS#7 em base64."""
    import base64

    meta = json.loads((dir_fixtures / "iofmg" / "edicao-2026-09-03.meta.json").read_text("utf-8"))
    envelope = gzip.decompress(
        (dir_fixtures / "iofmg" / "envelope-pkcs7-2026-09-03.bin.gz").read_bytes()
    )
    meta["dados"]["arquivoCadernoPrincipal"]["arquivo"] = base64.b64encode(envelope).decode()
    return json.dumps(meta).encode("utf-8")


@pytest.fixture
def storage(tmp_path: Path):
    s = Storage(tmp_path / "data")
    yield s
    s.fechar()


@pytest.fixture
def cfg() -> ConfigIOFMG:
    return ConfigIOFMG(
        caderno="Diário do Executivo",
        secao="Secretaria de Estado de Saúde",
        tipos_publicacao=["PORTARIA", "RESOLUÇÃO", "DELIBERAÇÃO", "ATO", "EXTRATO", "EDITAL"],
    )


def test_coleta_edicao_real_ponta_a_ponta(cfg, storage, resposta_api):
    resultado = FonteIOFMG(cfg, storage, SessaoFalsa(resposta_api)).coletar(DIA)
    assert resultado.status == Status.OK
    # Medido na edição real: 4 atos da SES. Eram 5 enquanto a citação em caixa
    # mista "Resolução SES nº 8.994/2023..." virava publicação inexistente.
    assert len(resultado.publicacoes) == 4
    assert all(p.texto.strip() for p in resultado.publicacoes)
    assert all(p.fonte == "iofmg" for p in resultado.publicacoes)


def test_links_apontam_para_a_edicao_correta(cfg, storage, resposta_api):
    resultado = FonteIOFMG(cfg, storage, SessaoFalsa(resposta_api)).coletar(DIA)
    for pub in resultado.publicacoes:
        assert "330896" in unquote(pub.url)


def test_dia_sem_edicao_vira_status_vazio(cfg, storage):
    sessao = SessaoFalsa(json.dumps({"dados": None}).encode())
    resultado = FonteIOFMG(cfg, storage, sessao).coletar(date(2026, 9, 6))
    assert resultado.status == Status.VAZIO
    assert resultado.publicacoes == []


def test_reprocessamento_reusa_o_pdf_em_cache(cfg, storage, resposta_api):
    sessao = SessaoFalsa(resposta_api)
    fonte = FonteIOFMG(cfg, storage, sessao)
    fonte.coletar(DIA)
    pedidos = len(sessao.pedidos)
    fonte.coletar(DIA)
    assert len(sessao.pedidos) == pedidos


def test_escopo_registra_secao_e_caderno(cfg, storage, resposta_api):
    resultado = FonteIOFMG(cfg, storage, SessaoFalsa(resposta_api)).coletar(DIA)
    assert resultado.escopo["secao"] == "Secretaria de Estado de Saúde"
    assert resultado.escopo["caderno"] == "Diário do Executivo"


# ── C2: a primeira página do intervalo também é fronteira ───────────────────


class SessaoProibida:
    """Qualquer requisição aqui é bug: este teste roda inteiro do cache."""

    def get(self, url, timeout=None):  # pragma: no cover - só existe para falhar
        raise AssertionError(f"o teste não pode ir à rede: {url}")


def _semear_02(storage: Storage, dir_fixtures: Path, dia: date) -> None:
    """Põe a edição de 02/09 no cache bruto, com o índice recortado nas 3 páginas."""
    meta = {
        "dados": {
            "cadernos": [
                {
                    "id": 330892,
                    "descricao": "Diário do Executivo",
                    "secoes": [
                        {"descricao": "Instituto de Previdência dos Servidores", "paginaInicial": 1},
                        {"descricao": "Secretaria de Estado de Saúde", "paginaInicial": 1},
                        {"descricao": "Secretaria de Estado de Educação", "paginaInicial": 3},
                    ],
                }
            ],
            "arquivoCadernoPrincipal": {"totalPaginas": 3, "arquivo": ""},
        }
    }
    storage.salvar_raw(dia, "iofmg", "edicao.json", json.dumps(meta).encode("utf-8"))
    storage.salvar_raw(
        dia, "iofmg", "caderno.pdf",
        (dir_fixtures / "iofmg" / "caderno-2026-09-02-ses.pdf").read_bytes(),
    )


def test_ato_do_orgao_anterior_nao_entra_com_procedencia_falsa(cfg, storage, dir_fixtures):
    """`PORTARIA Nº 35` é do IPSEMG e vinha rotulada como da Secretaria de Saúde."""
    dia = date(2026, 9, 2)
    _semear_02(storage, dir_fixtures, dia)
    resultado = FonteIOFMG(cfg, storage, SessaoProibida()).coletar(dia)

    assert resultado.status == Status.OK
    titulos = [p.titulo for p in resultado.publicacoes]
    assert not any(t.startswith("PORTARIA Nº 35") for t in titulos), titulos
    # Medido: 16 segmentos antes das correções, 13 depois (C1 tirou 2, C2 tirou 1).
    assert len(resultado.publicacoes) == 13, titulos
    assert all(p.orgao == "Secretaria de Estado de Saúde" for p in resultado.publicacoes)
