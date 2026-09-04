from boletim.cli import main


def test_gerar_ainda_nao_implementado_retorna_2(capsys):
    assert main(["gerar", "--data", "2026-09-03"]) == 2
    assert "não implementado" in capsys.readouterr().out


def test_renderizar_ainda_nao_implementado_retorna_2(capsys):
    assert main(["renderizar", "--data", "2026-09-03"]) == 2
    assert "não implementado" in capsys.readouterr().out


def test_site_ainda_nao_implementado_retorna_2(capsys):
    assert main(["site", "--data", "2026-09-03"]) == 2
    assert "não implementado" in capsys.readouterr().out
