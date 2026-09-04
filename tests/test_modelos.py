from datetime import date, datetime, timezone

import pytest

from radar.core.erros import (
    ExtracaoParcial,
    FonteIndisponivel,
    SemEdicao,
    Status,
    status_para_exit,
)
from radar.core.modelos import Publicacao, Resultado, gerar_id


def _pub(**kw) -> Publicacao:
    base = dict(
        fonte="dou",
        data_publicacao=date(2026, 9, 4),
        coletado_em=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
        orgao="Ministério da Saúde",
        unidade="Gabinete do Ministro",
        secao="1",
        pagina=None,
        edicao="168",
        tipo="Portaria",
        numero="12.141",
        titulo="Portaria GM/MS Nº 12.141",
        ementa="Renova qualificação.",
        texto="Texto integral da portaria.",
        url="https://www.in.gov.br/web/dou/-/x",
        origem={"metodo": "teste"},
    )
    base.update(kw)
    base["id"] = gerar_id(base["fonte"], base["data_publicacao"], base["url"], base["titulo"])
    return Publicacao(**base)


def test_status_mapeia_para_exit_code():
    assert status_para_exit(Status.OK) == 0
    assert status_para_exit(Status.VAZIO) == 0
    assert status_para_exit(Status.PARCIAL) == 1
    assert status_para_exit(Status.ERRO) == 2


def test_id_e_estavel_e_deterministico():
    a = gerar_id("dou", date(2026, 9, 4), "https://x/1", "Portaria 1")
    b = gerar_id("dou", date(2026, 9, 4), "https://x/1", "Portaria 1")
    assert a == b and len(a) == 16


def test_id_muda_quando_a_url_muda():
    a = gerar_id("dou", date(2026, 9, 4), "https://x/1", "Portaria 1")
    b = gerar_id("dou", date(2026, 9, 4), "https://x/2", "Portaria 1")
    assert a != b


def test_publicacao_e_imutavel():
    pub = _pub()
    with pytest.raises(Exception):
        pub.titulo = "outro"


def test_resultado_serializa_para_dict_com_contrato_da_spec():
    pub = _pub()
    r = Resultado(
        fonte="dou",
        data_publicacao=date(2026, 9, 4),
        coletado_em=datetime(2026, 9, 4, 12, 7, 41, tzinfo=timezone.utc),
        status=Status.OK,
        escopo={"orgao": "Ministério da Saúde"},
        publicacoes=[pub],
        avisos=[],
    )
    d = r.para_dict()
    assert d["schema_versao"] == "1.0"
    assert d["fonte"] == "dou"
    assert d["data_publicacao"] == "2026-09-04"
    assert d["coletado_em"] == "2026-09-04T12:07:41Z"
    assert d["status"] == "ok"
    assert d["total"] == 1
    assert d["avisos"] == []
    assert d["publicacoes"][0]["texto"] == "Texto integral da portaria."
    assert d["publicacoes"][0]["data_publicacao"] == "2026-09-04"


def test_resultado_total_acompanha_a_lista():
    r = Resultado(
        fonte="dou",
        data_publicacao=date(2026, 9, 4),
        coletado_em=datetime(2026, 9, 4, tzinfo=timezone.utc),
        status=Status.VAZIO,
        escopo={},
        publicacoes=[],
        avisos=["sem edição"],
    )
    assert r.para_dict()["total"] == 0


def test_extracao_parcial_carrega_avisos():
    exc = ExtracaoParcial("paginação travou", avisos=["página 3 repetida"])
    assert exc.avisos == ["página 3 repetida"]
    assert isinstance(exc, Exception)


def test_hierarquia_de_erros():
    from radar.core.erros import ErroRadar

    assert issubclass(SemEdicao, ErroRadar)
    assert issubclass(FonteIndisponivel, ErroRadar)
    assert issubclass(ExtracaoParcial, ErroRadar)
