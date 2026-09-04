import gzip
import json
from datetime import date
from pathlib import Path

import pytest

from radar.core.erros import SemEdicao
from radar.fontes.iofmg.api import caderno_principal, consultar_edicao, montar_url
from radar.fontes.iofmg.pkcs7 import desembrulhar


@pytest.fixture
def dados_03(dir_fixtures: Path) -> dict:
    bruto = json.loads((dir_fixtures / "iofmg" / "edicao-2026-09-03.meta.json").read_text("utf-8"))
    return bruto["dados"]


@pytest.fixture
def envelope(dir_fixtures: Path) -> bytes:
    return gzip.decompress((dir_fixtures / "iofmg" / "envelope-pkcs7-2026-09-03.bin.gz").read_bytes())


def test_monta_url_com_a_data():
    assert "dataPublicacao=2026-09-04" in montar_url(date(2026, 9, 4))


def test_caderno_principal_e_o_diario_do_executivo(dados_03):
    caderno = caderno_principal(dados_03, "Diário do Executivo")
    assert caderno["descricao"] == "Diário do Executivo"


def test_id_do_caderno_vem_da_resposta_nao_de_constante(dados_03, dir_fixtures: Path):
    """Regressao do bug 3: hoje 326074 esta fixo e erra em toda data."""
    id_03 = caderno_principal(dados_03, "Diário do Executivo")["id"]
    dados_02 = json.loads(
        (dir_fixtures / "iofmg" / "edicao-2026-09-02.meta.json").read_text("utf-8")
    )["dados"]
    id_02 = caderno_principal(dados_02, "Diário do Executivo")["id"]
    assert id_03 == 330896
    assert id_02 == 330892
    assert id_03 != id_02, "o id muda por edição; não pode ser constante"
    assert 326074 not in (id_03, id_02)


def test_caderno_inexistente_levanta_sem_edicao(dados_03):
    with pytest.raises(SemEdicao):
        caderno_principal(dados_03, "Caderno Que Não Existe")


def test_desembrulha_envelope_pkcs7_em_ber_indefinido(envelope):
    """O payload usa BER de comprimento indefinido (30 80), nao DER estrito."""
    assert envelope[:1] == b"\x30"
    pdf = desembrulhar(envelope)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1_000_000


def test_desembrulhar_aceita_pdf_cru_sem_envelope():
    """Robustez: se a API parar de assinar, seguimos funcionando."""
    cru = b"%PDF-1.7\n resto do arquivo"
    assert desembrulhar(cru) == cru


def test_desembrulhar_rejeita_formato_desconhecido():
    with pytest.raises(ValueError):
        desembrulhar(b"isto nao e nem PDF nem DER")


class SessaoFalsa:
    def __init__(self, corpo: bytes, status: int = 200):
        self.corpo, self.status = corpo, status

    def get(self, url, timeout=None):
        class R:
            pass

        r = R()
        r.status_code = self.status
        r.content = self.corpo
        return r


def test_consultar_edicao_devolve_dados():
    corpo = json.dumps({"dados": {"dataPublicacao": "2026-09-04T00:00:00"}}).encode()
    assert consultar_edicao(SessaoFalsa(corpo), date(2026, 9, 4))["dataPublicacao"].startswith("2026")


def test_consultar_edicao_sem_dados_levanta_sem_edicao():
    corpo = json.dumps({"dados": None, "erros": []}).encode()
    with pytest.raises(SemEdicao):
        consultar_edicao(SessaoFalsa(corpo), date(2026, 9, 6))


def test_http_401_e_bloqueio_de_acesso_nao_dia_sem_edicao():
    """A API nunca responde 401 por falta de edição; 401 é bloqueio de acesso.

    Reportá-lo como `vazio` faria um IP banido virar "domingo" todo dia.
    """
    from radar.core.erros import FonteIndisponivel

    with pytest.raises(FonteIndisponivel):
        consultar_edicao(SessaoFalsa(b"", status=401), date(2026, 9, 6))
