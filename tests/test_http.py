import pytest
import requests

from radar.core.erros import FonteIndisponivel, SemEdicao
from radar.core.http import criar_sessao, obter_bytes, obter_texto


class RespostaFalsa:
    def __init__(self, status: int, corpo: bytes = b"ok"):
        self.status_code = status
        self.content = corpo


class SessaoFalsa:
    """Devolve as respostas programadas, uma por chamada, contando tentativas."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = 0

    def get(self, url, timeout=None):
        self.chamadas += 1
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_sucesso_devolve_bytes():
    s = SessaoFalsa([RespostaFalsa(200, b"conteudo")])
    assert obter_bytes(s, "https://x", espera_base=0) == b"conteudo"
    assert s.chamadas == 1


def test_erro_permanente_nao_e_retentado():
    """404 nunca vira sucesso; retentar so desperdica tempo."""
    s = SessaoFalsa([RespostaFalsa(404)])
    with pytest.raises(FonteIndisponivel):
        obter_bytes(s, "https://x", tentativas=3, espera_base=0)
    assert s.chamadas == 1


def test_401_e_erro_permanente_nao_dia_sem_edicao():
    """Validado contra a API real: num dia sem edição ela responde HTTP 200 com
    `{"dados": null, "erros": []}` — nunca 401. Logo o único 401 possível é
    bloqueio de acesso (WAF, IP banido), e traduzi-lo em "domingo, siga sem
    alarme" calaria a coleta todo dia, para sempre.
    """
    s = SessaoFalsa([RespostaFalsa(401)])
    with pytest.raises(FonteIndisponivel):
        obter_bytes(s, "https://x", espera_base=0)
    assert s.chamadas == 1, "erro permanente não é retentado"


def test_dia_sem_edicao_continua_sendo_o_corpo_da_resposta():
    """Quem detecta o dia sem edição é `api.dados_de`, pelo `dados` nulo."""
    import json
    from datetime import date

    from radar.fontes.iofmg.api import dados_de

    with pytest.raises(SemEdicao):
        dados_de(json.dumps({"dados": None, "erros": []}).encode(), date(2026, 9, 6))


def test_erro_transitorio_e_retentado_ate_o_limite():
    s = SessaoFalsa([RespostaFalsa(503), RespostaFalsa(503), RespostaFalsa(503)])
    with pytest.raises(FonteIndisponivel):
        obter_bytes(s, "https://x", tentativas=3, espera_base=0)
    assert s.chamadas == 3


def test_erro_transitorio_que_se_resolve():
    s = SessaoFalsa([RespostaFalsa(500), RespostaFalsa(200, b"agora vai")])
    assert obter_bytes(s, "https://x", tentativas=3, espera_base=0) == b"agora vai"
    assert s.chamadas == 2


def test_429_e_tratado_como_transitorio():
    s = SessaoFalsa([RespostaFalsa(429), RespostaFalsa(200, b"ok")])
    assert obter_bytes(s, "https://x", tentativas=3, espera_base=0) == b"ok"


def test_timeout_de_rede_e_retentado():
    s = SessaoFalsa([requests.exceptions.Timeout(), RespostaFalsa(200, b"ok")])
    assert obter_bytes(s, "https://x", tentativas=3, espera_base=0) == b"ok"


def test_obter_texto_respeita_o_encoding_pedido_e_ignora_o_declarado():
    """A busca do DOU declara UTF-8 mas e ISO-8859-1."""
    corpo = "Ministério da Saúde".encode("iso-8859-1")
    s = SessaoFalsa([RespostaFalsa(200, corpo)])
    assert obter_texto(s, "https://x", encoding="iso-8859-1", espera_base=0) == "Ministério da Saúde"


def test_sessao_tem_user_agent():
    sessao = criar_sessao()
    assert "Mozilla" in sessao.headers["User-Agent"]
