from datetime import date, datetime, timezone

import pytest

from radar.core.erros import Status
from radar.core.modelos import Publicacao, Resultado, gerar_id
from radar.notificacao.email import enviar, montar_html


def _pub(titulo="Portaria 1", url="https://in.gov.br/x", unidade=None) -> Publicacao:
    d = date(2026, 9, 4)
    return Publicacao(
        id=gerar_id("dou", d, url, titulo), fonte="dou", data_publicacao=d,
        coletado_em=datetime(2026, 9, 4, tzinfo=timezone.utc), orgao="Ministério da Saúde",
        unidade=unidade, secao="1", pagina=None, edicao="168", tipo="Portaria", numero="1",
        titulo=titulo, ementa="Faz algo.", texto="Art. 1º ...", url=url, origem={},
    )


def _resultado(publicacoes) -> Resultado:
    return Resultado(
        fonte="dou", data_publicacao=date(2026, 9, 4),
        coletado_em=datetime(2026, 9, 4, tzinfo=timezone.utc), status=Status.OK,
        escopo={"orgao": "Ministério da Saúde"}, publicacoes=publicacoes, avisos=[],
    )


def test_html_lista_as_publicacoes():
    html = montar_html([_resultado([_pub()])])
    assert "Portaria 1" in html
    assert "Ministério da Saúde" in html


def test_orgao_aparece_uma_vez_so_e_nao_por_publicacao():
    """Repetir o orgao em cada item vira ruido: sao 118 num dia de DOU."""
    html = montar_html([_resultado([
        _pub(titulo="A", url="https://x/a"),
        _pub(titulo="B", url="https://x/b"),
    ])])
    assert html.count("Ministério da Saúde") == 1


def test_unidade_aparece_quando_existe():
    """`unidade` varia dentro da coleta (Gabinete do Ministro, ANVISA) e informa."""
    html = montar_html([_resultado([_pub(titulo="A", url="https://x/a", unidade="ANVISA")])])
    assert "ANVISA" in html


def test_titulo_com_html_e_escapado():
    html = montar_html([_resultado([_pub(titulo='Portaria <script>alert(1)</script>')])])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_url_e_escapada_no_href():
    """Bug 10: pub['url'] vem raspado da web e era interpolado cru no href."""
    html = montar_html([_resultado([_pub(url='https://x/a" onmouseover="mal()')])])
    assert 'onmouseover="mal()"' not in html
    assert "&quot;" in html or "%22" in html


def test_avisos_aparecem_no_html():
    r = _resultado([_pub()])
    r.avisos = ["paginação travou"]
    assert "paginação travou" in montar_html([r])


def test_status_vazio_gera_html_sem_estourar():
    r = _resultado([])
    r.status = Status.VAZIO
    assert "sem publicações" in montar_html([r]).lower()


def test_enviar_sem_destinatario_devolve_false():
    assert enviar("<p>x</p>", "assunto", {"habilitado": True, "destinatarios": []}) is False


def test_enviar_desabilitado_devolve_false():
    assert enviar("<p>x</p>", "assunto", {"habilitado": False, "destinatarios": ["a@b.c"]}) is False


def test_enviar_usa_smtp_do_ambiente(monkeypatch):
    enviadas = {}

    class SMTPFalso:
        def __init__(self, host, port, timeout=None):
            enviadas["host"], enviadas["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            enviadas["tls"] = True

        def login(self, u, p):
            enviadas["user"] = u

        def sendmail(self, de, para, msg):
            enviadas["para"] = para

    monkeypatch.setattr("smtplib.SMTP", SMTPFalso)
    monkeypatch.setenv("RADAR_SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setenv("RADAR_SMTP_PORT", "587")
    monkeypatch.setenv("RADAR_SMTP_USER", "u@exemplo.com")
    monkeypatch.setenv("RADAR_SMTP_PASSWORD", "segredo")
    monkeypatch.setenv("RADAR_EMAIL_FROM", "u@exemplo.com")

    assert enviar("<p>x</p>", "assunto", {"habilitado": True, "destinatarios": ["a@b.c"]}) is True
    assert enviadas["host"] == "smtp.exemplo.com"
    assert enviadas["para"] == ["a@b.c"]


def test_falha_de_envio_devolve_false_sem_propagar(monkeypatch):
    def explode(*a, **k):
        raise OSError("smtp fora do ar")

    monkeypatch.setattr("smtplib.SMTP", explode)
    monkeypatch.setenv("RADAR_SMTP_HOST", "smtp.exemplo.com")
    assert enviar("<p>x</p>", "a", {"habilitado": True, "destinatarios": ["a@b.c"]}) is False
