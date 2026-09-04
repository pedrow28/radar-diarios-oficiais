from datetime import date, datetime, timezone

import pytest

from radar.core.datas import TZ_BR, agora_utc, hoje, parse_data


def test_hoje_usa_fuso_de_sao_paulo_e_nao_utc(monkeypatch):
    """As 23h de 04/09 em Sao Paulo ainda sao 04/09, embora ja seja 05/09 em UTC."""
    import radar.core.datas as mod

    class RelogioFalso(datetime):
        @classmethod
        def now(cls, tz=None):
            instante = datetime(2026, 9, 5, 2, 30, tzinfo=timezone.utc)
            return instante.astimezone(tz) if tz else instante

    monkeypatch.setattr(mod, "datetime", RelogioFalso)
    assert hoje() == date(2026, 9, 4)


def test_agora_utc_tem_tzinfo():
    momento = agora_utc()
    assert momento.tzinfo is not None
    assert momento.utcoffset().total_seconds() == 0


def test_parse_data_aceita_iso():
    assert parse_data("2026-09-04") == date(2026, 9, 4)


def test_parse_data_aceita_formato_brasileiro():
    assert parse_data("04/09/2026") == date(2026, 9, 4)


def test_parse_data_rejeita_lixo():
    with pytest.raises(ValueError):
        parse_data("ontem")


def test_tz_br_e_sao_paulo():
    assert str(TZ_BR) == "America/Sao_Paulo"
