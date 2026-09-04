"""Login e download no INLABS. Nenhum teste aqui toca a rede."""

import io
import logging
import zipfile
from datetime import date
from pathlib import Path

import pytest

from radar.core.erros import FonteIndisponivel
from radar.fontes.inlabs.sessao import (
    HEADER_ORIGEM,
    URL_LOGIN,
    abrir_sessao,
    baixar_zip,
    montar_url_download,
)

DIA = date(2026, 9, 3)


class RespostaFalsa:
    def __init__(self, status: int, corpo: bytes = b""):
        self.status_code = status
        self.content = corpo


class SessaoFalsa:
    """Sessão com cookies controláveis, que registra o que recebeu."""

    def __init__(self, cookies=(), respostas=()):
        self.cookies = list(cookies)
        self.respostas = list(respostas)
        self.posts: list[dict] = []
        self.gets: list[dict] = []

    def post(self, url, data=None, headers=None, timeout=None):
        self.posts.append({"url": url, "data": data, "headers": headers})
        return RespostaFalsa(200, b"<html>ok</html>")

    def get(self, url, timeout=None, **kwargs):
        self.gets.append({"url": url, "headers": kwargs.get("headers")})
        return self.respostas.pop(0)


@pytest.fixture
def zip_do1(dir_fixtures: Path) -> bytes:
    return (dir_fixtures / "inlabs" / "2026-09-03-DO1.zip").read_bytes()


# ── URLs e headers verificados do serviço ───────────────────────────────────


def test_url_de_login():
    assert URL_LOGIN == "https://inlabs.in.gov.br/logar.php"


def test_url_de_download_leva_data_e_secao():
    url = montar_url_download(DIA, "DO1")
    assert url == "https://inlabs.in.gov.br/index.php?p=2026-09-03&dl=2026-09-03-DO1.zip"


def test_url_de_download_de_edicao_extra():
    assert montar_url_download(DIA, "DO1E").endswith("dl=2026-09-03-DO1E.zip")


def test_header_origem_e_o_valor_esperado_pelo_servico():
    assert HEADER_ORIGEM == {"origem": "736372697072"}


# ── login ───────────────────────────────────────────────────────────────────


def test_login_bem_sucedido_devolve_a_sessao():
    sessao = SessaoFalsa(cookies=["inlabs_session_cookie"])
    assert abrir_sessao("alguem@exemplo.org", "segredo", sessao) is sessao


def test_login_envia_as_credenciais_no_formato_do_formulario():
    sessao = SessaoFalsa(cookies=["inlabs_session_cookie"])
    abrir_sessao("alguem@exemplo.org", "segredo", sessao)
    pedido = sessao.posts[0]
    assert pedido["url"] == URL_LOGIN
    assert pedido["data"] == {"email": "alguem@exemplo.org", "password": "segredo"}
    assert pedido["headers"]["origem"] == "736372697072"
    assert pedido["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


def test_sem_o_cookie_de_sessao_o_login_foi_recusado():
    """O serviço responde 200 com a página de login quando recusa; só o
    cookie distingue entrar de não entrar.
    """
    sessao = SessaoFalsa(cookies=[])
    with pytest.raises(FonteIndisponivel) as erro:
        abrir_sessao("alguem@exemplo.org", "segredo", sessao)
    assert "login INLABS recusado (cookie de sessão ausente)" in str(erro.value)


@pytest.fixture
def linhas_de_log():
    """Escuta o logger do radar.

    `caplog` não serve aqui: o logger do radar tem `propagate = False`, então
    nada chega ao handler que o pytest instala na raiz e o teste passaria sem
    ter olhado uma linha sequer.
    """
    registros: list[str] = []

    class Coletor(logging.Handler):
        def emit(self, record):
            registros.append(record.getMessage())

    logger = logging.getLogger("radar")
    handler = Coletor(level=logging.DEBUG)
    logger.addHandler(handler)
    nivel = logger.level
    logger.setLevel(logging.DEBUG)
    yield registros
    logger.removeHandler(handler)
    logger.setLevel(nivel)


def test_a_senha_e_o_email_nunca_aparecem_no_log(linhas_de_log):
    sessao = SessaoFalsa(cookies=[])
    with pytest.raises(FonteIndisponivel):
        abrir_sessao("alguem@exemplo.org", "senha-secretissima", sessao)
    assert linhas_de_log, "o login precisa deixar rastro de que tentou"
    assert not any("senha-secretissima" in linha for linha in linhas_de_log)
    assert not any("alguem@exemplo.org" in linha for linha in linhas_de_log)


def test_sem_sessao_informada_uma_e_criada(monkeypatch):
    criada = SessaoFalsa(cookies=["inlabs_session_cookie"])
    monkeypatch.setattr("radar.fontes.inlabs.sessao.criar_sessao", lambda: criada)
    assert abrir_sessao("alguem@exemplo.org", "segredo") is criada
    assert criada.posts, "a sessão criada é a que faz o login"


# ── download ────────────────────────────────────────────────────────────────


def test_download_devolve_os_bytes_do_zip(zip_do1):
    sessao = SessaoFalsa(respostas=[RespostaFalsa(200, zip_do1)])
    bruto = baixar_zip(sessao, DIA, "DO1")
    assert bruto == zip_do1
    assert zipfile.is_zipfile(io.BytesIO(bruto))


def test_download_manda_o_header_origem(zip_do1):
    sessao = SessaoFalsa(respostas=[RespostaFalsa(200, zip_do1)])
    baixar_zip(sessao, DIA, "DO1")
    assert sessao.gets[0]["headers"] == HEADER_ORIGEM
    assert sessao.gets[0]["url"] == montar_url_download(DIA, "DO1")


def test_404_e_arquivo_inexistente_nao_erro():
    """Domingo, feriado ou seção ainda não publicada: `None`, sem exceção."""
    sessao = SessaoFalsa(respostas=[RespostaFalsa(404)])
    assert baixar_zip(sessao, date(2026, 9, 6), "DO1") is None


def test_resposta_que_nao_e_zip_e_falha_da_fonte():
    """200 com HTML é sessão expirada servindo página de login. Deixar passar
    faria o parse acusar "edição sem matérias" no lugar do bloqueio real.
    """
    sessao = SessaoFalsa(respostas=[RespostaFalsa(200, b"<html>faca login</html>")])
    with pytest.raises(FonteIndisponivel) as erro:
        baixar_zip(sessao, DIA, "DO1")
    assert "zip" in str(erro.value)


def test_erro_de_servidor_continua_sendo_erro():
    sessao = SessaoFalsa(respostas=[RespostaFalsa(403)])
    with pytest.raises(FonteIndisponivel):
        baixar_zip(sessao, DIA, "DO1")
