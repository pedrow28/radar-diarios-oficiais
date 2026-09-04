import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from radar.core.erros import Status
from radar.core.modelos import Publicacao, Resultado, gerar_id
from radar.core.storage import Storage


def _pub(titulo="Portaria 1", url="https://x/1", texto="teto MAC ampliado") -> Publicacao:
    d = date(2026, 9, 4)
    return Publicacao(
        id=gerar_id("dou", d, url, titulo),
        fonte="dou",
        data_publicacao=d,
        coletado_em=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
        orgao="Ministério da Saúde",
        unidade=None,
        secao="1",
        pagina=None,
        edicao="168",
        tipo="Portaria",
        numero="1",
        titulo=titulo,
        ementa=None,
        texto=texto,
        url=url,
        origem={},
    )


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    s = Storage(tmp_path / "data")
    yield s
    s.fechar()


def test_salva_e_le_bruto(storage: Storage):
    caminho = storage.salvar_raw(date(2026, 9, 4), "dou", "busca-p1.html", b"<html>")
    assert caminho.exists()
    assert storage.ler_raw(date(2026, 9, 4), "dou", "busca-p1.html") == b"<html>"


def test_ler_bruto_inexistente_devolve_none(storage: Storage):
    assert storage.ler_raw(date(2026, 9, 4), "dou", "nao-existe.html") is None


def test_salva_json_normalizado_no_caminho_da_spec(storage: Storage):
    r = Resultado(
        fonte="dou",
        data_publicacao=date(2026, 9, 4),
        coletado_em=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
        status=Status.OK,
        escopo={"orgao": "Ministério da Saúde"},
        publicacoes=[_pub()],
    )
    caminho = storage.salvar_normalizado(r)
    assert caminho.name == "dou.json"
    assert caminho.parent.name == "2026-09-04"
    conteudo = json.loads(caminho.read_text(encoding="utf-8"))
    assert conteudo["total"] == 1
    assert conteudo["status"] == "ok"


def test_gravar_duas_vezes_nao_duplica(storage: Storage):
    """Idempotencia: reexecutar o mesmo dia converge, nao acumula."""
    assert storage.gravar([_pub()]) == 1
    assert storage.gravar([_pub()]) == 1
    assert len(storage.consultar("teto")) == 1


def test_gravar_atualiza_texto_em_reprocessamento(storage: Storage):
    storage.gravar([_pub(texto="texto antigo")])
    storage.gravar([_pub(texto="texto novo e melhor")])
    achados = storage.consultar("melhor")
    assert len(achados) == 1
    assert achados[0]["texto"] == "texto novo e melhor"


def test_consulta_fts_encontra_por_termo(storage: Storage):
    storage.gravar([_pub(titulo="A", url="https://x/a", texto="repasse de custeio")])
    storage.gravar([_pub(titulo="B", url="https://x/b", texto="nomeacao de servidor")])
    assert len(storage.consultar("custeio")) == 1
    assert len(storage.consultar("nomeacao")) == 1


def test_consulta_filtra_por_data_inicial(storage: Storage):
    storage.gravar([_pub()])
    assert storage.consultar("teto", desde=date(2026, 9, 1)) != []
    assert storage.consultar("teto", desde=date(2026, 10, 1)) == []


def test_consulta_sem_resultado_devolve_lista_vazia(storage: Storage):
    assert storage.consultar("inexistente") == []


# ── K4: retenção de `raw/` (spec §8.1) ──────────────────────────────────────


def _semear_dia(storage, dia, conteudo=b"x"):
    storage.salvar_raw(dia, "dou", "busca-p1.html", conteudo)
    storage.salvar_raw(dia, "iofmg", "caderno.pdf", conteudo)


def test_limpar_raw_remove_so_o_que_passou_da_retencao(tmp_path):
    from datetime import timedelta

    from radar.core.datas import hoje

    s = Storage(tmp_path / "data")
    try:
        agora = hoje()
        velho = agora - timedelta(days=31)
        limite = agora - timedelta(days=30)
        recente = agora - timedelta(days=2)
        for dia in (velho, limite, recente, agora):
            _semear_dia(s, dia)

        assert s.limpar_raw_antigos(30) == 1
        assert not (s.dir_raw / velho.isoformat()).exists()
        for dia in (limite, recente, agora):
            assert (s.dir_raw / dia.isoformat()).exists(), dia
    finally:
        s.fechar()


def test_limpar_raw_remove_o_diretorio_inteiro_do_dia(tmp_path):
    from datetime import timedelta

    from radar.core.datas import hoje

    s = Storage(tmp_path / "data")
    try:
        velho = hoje() - timedelta(days=90)
        _semear_dia(s, velho, b"conteudo grande")
        assert s.limpar_raw_antigos(30) == 1
        assert list(s.dir_raw.iterdir()) == []
    finally:
        s.fechar()


def test_limpar_raw_ignora_o_que_nao_e_dia(tmp_path):
    """Nada dentro de `raw/` que este código não criou é nosso para apagar."""
    s = Storage(tmp_path / "data")
    try:
        s.dir_raw.mkdir(parents=True, exist_ok=True)
        (s.dir_raw / "anotacoes-do-operador").mkdir()
        (s.dir_raw / "leia-me.txt").write_text("nao apague", encoding="utf-8")
        assert s.limpar_raw_antigos(1) == 0
        assert (s.dir_raw / "anotacoes-do-operador").exists()
        assert (s.dir_raw / "leia-me.txt").exists()
    finally:
        s.fechar()


def test_limpar_raw_com_retencao_zero_nao_apaga_nada(tmp_path):
    from datetime import timedelta

    from radar.core.datas import hoje

    s = Storage(tmp_path / "data")
    try:
        _semear_dia(s, hoje() - timedelta(days=365))
        assert s.limpar_raw_antigos(0) == 0
        assert s.limpar_raw_antigos(-5) == 0
        assert list(s.dir_raw.iterdir())
    finally:
        s.fechar()


def test_limpar_raw_sem_diretorio_devolve_zero(tmp_path):
    s = Storage(tmp_path / "data")
    try:
        assert not s.dir_raw.exists()
        assert s.limpar_raw_antigos(30) == 0
    finally:
        s.fechar()
