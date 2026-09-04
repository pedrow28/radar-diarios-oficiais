from pathlib import Path

import radar


def test_pacote_importavel():
    assert radar.__version__


def test_fixtures_presentes(dir_fixtures: Path):
    assert (dir_fixtures / "dou" / "busca-ms-2026-09-03-p1.html").exists()
    assert (dir_fixtures / "dou" / "busca-ms-2026-09-03-p2.html").exists()
    assert (dir_fixtures / "dou" / "pub-portaria-gm-ms-12141.html").exists()
    assert (dir_fixtures / "iofmg" / "edicao-2026-09-03.meta.json").exists()
    assert (dir_fixtures / "iofmg" / "caderno-2026-09-03-ses.pdf").exists()
    assert (dir_fixtures / "iofmg" / "envelope-pkcs7-2026-09-03.bin.gz").exists()
