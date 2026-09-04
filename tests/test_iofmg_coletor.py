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
    assert len(resultado.publicacoes) >= 5
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
