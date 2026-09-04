"""Coleta do INLABS: zip por seção → artigos → escopo → publicações."""

import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from radar.core.config import ConfigINLABS
from radar.core.erros import FonteIndisponivel, Status
from radar.core.storage import Storage
from radar.fontes.inlabs.coletor import FonteINLABS, em_escopo
from radar.fontes.inlabs.xml import Artigo

DIA = date(2026, 9, 3)
DOMINGO = date(2026, 9, 6)


class RespostaFalsa:
    def __init__(self, status: int, corpo: bytes = b""):
        self.status_code = status
        self.content = corpo


class SessaoFalsa:
    """Autentica sempre; devolve a resposta programada para cada seção."""

    def __init__(self, por_secao: dict[str, RespostaFalsa]):
        self.por_secao = por_secao
        self.cookies = ["inlabs_session_cookie"]
        self.posts = 0
        self.gets: list[str] = []

    def post(self, url, data=None, headers=None, timeout=None):
        self.posts += 1
        return RespostaFalsa(200)

    def get(self, url, timeout=None, **kwargs):
        self.gets.append(url)
        for secao, resposta in self.por_secao.items():
            if url.endswith(f"-{secao}.zip"):
                return resposta
        return RespostaFalsa(404)


class SessaoProibida:
    """Qualquer requisição aqui é bug: o teste roda inteiro do cache."""

    cookies: list[str] = []

    def post(self, *args, **kwargs):  # pragma: no cover - só existe para falhar
        raise AssertionError("o teste não pode fazer login")

    def get(self, *args, **kwargs):  # pragma: no cover - só existe para falhar
        raise AssertionError("o teste não pode ir à rede")


@pytest.fixture
def storage(tmp_path: Path):
    s = Storage(tmp_path / "data")
    yield s
    s.fechar()


@pytest.fixture
def zip_do1(dir_fixtures: Path) -> bytes:
    return (dir_fixtures / "inlabs" / "2026-09-03-DO1.zip").read_bytes()


@pytest.fixture
def cfg() -> ConfigINLABS:
    return ConfigINLABS()


@pytest.fixture
def credenciais(monkeypatch):
    monkeypatch.setenv("INLABS_EMAIL", "alguem@exemplo.org")
    monkeypatch.setenv("INLABS_SENHA", "segredo")


def _semear(storage: Storage, data: date, secao: str, bruto: bytes) -> None:
    storage.salvar_raw(data, "inlabs", f"{data.isoformat()}-{secao}.zip", bruto)


def _artigo(**mudancas) -> Artigo:
    padrao = {
        "id": "1", "nome": "ATO", "pub_name": "DO1", "art_type": "Portaria",
        "pub_date": "03/09/2026", "art_category": "Ministério da Saúde/Gabinete do Ministro",
        "number_page": "1", "pdf_page": "https://pdf.in.gov.br/x.pdf",
        "edition_number": "168", "id_materia": "1", "identifica": "ATO",
        "ementa": "", "titulo": "ATO", "texto_html": '<p class="dou-paragraph">Texto.</p>',
    }
    return Artigo(**{**padrao, **mudancas})


def _zip_com(*artigos: tuple[str, str]) -> bytes:
    """Monta um zip a partir de pares (idMateria, artCategory)."""
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for i, (id_materia, categoria) in enumerate(artigos):
            z.writestr(
                f"{i}.xml",
                (
                    '<?xml version="1.0" encoding="utf-8"?><xml>'
                    f'<article id="{i}" name="ATO {i}" pubName="DO1" artType="Portaria" '
                    f'pubDate="03/09/2026" artCategory="{categoria}" numberPage="1" '
                    f'pdfPage="https://pdf.in.gov.br/{i}.pdf" editionNumber="168" '
                    f'idMateria="{id_materia}"><body>'
                    f"<Identifica><![CDATA[ATO Nº {i}]]></Identifica>"
                    '<Texto><![CDATA[<p class="dou-paragraph">Texto do ato.</p>]]></Texto>'
                    "</body></article></xml>"
                ).encode("utf-8"),
            )
    return saida.getvalue()


# ── escopo ──────────────────────────────────────────────────────────────────


def test_orgao_configurado_no_primeiro_nivel_entra(cfg):
    assert em_escopo(_artigo(art_category="Ministério da Saúde/Gabinete do Ministro"), cfg)


def test_orgao_de_fora_nao_entra(cfg):
    assert not em_escopo(_artigo(art_category="Ministério da Educação/Gabinete do Ministro"), cfg)


def test_anvisa_entra_aninhada_sob_o_ministerio_da_saude(cfg):
    """O INLABS publica a ANVISA ora como 1º nível, ora sob o Ministério."""
    artigo = _artigo(
        art_category=(
            "Ministério da Saúde/Agência Nacional de Vigilância Sanitária/Diretoria Colegiada"
        )
    )
    assert em_escopo(artigo, cfg)


def test_anvisa_entra_como_orgao_de_primeiro_nivel(cfg):
    artigo = _artigo(art_category="Agência Nacional de Vigilância Sanitária/Diretoria Colegiada")
    assert em_escopo(artigo, cfg)


def test_anvisa_fora_da_config_nao_entra_por_aninhamento():
    cfg = ConfigINLABS(orgaos=["Ministério da Fazenda"])
    artigo = _artigo(
        art_category="Ministério da Saúde/Agência Nacional de Vigilância Sanitária"
    )
    assert not em_escopo(artigo, cfg)


def test_presidencia_exige_a_subunidade_configurada(cfg):
    """A Presidência publica o diário inteiro do Executivo; sem o recorte de
    subunidade, `orgaos` deixaria de recortar coisa alguma.
    """
    assert em_escopo(_artigo(art_category="Presidência da República/Casa Civil"), cfg)
    assert not em_escopo(
        _artigo(art_category="Presidência da República/Secretaria de Comunicação Social"), cfg
    )
    assert not em_escopo(_artigo(art_category="Presidência da República"), cfg)


# ── coleta ──────────────────────────────────────────────────────────────────


def test_edicao_real_da_fixture_rende_as_publicacoes_do_escopo(cfg, storage, zip_do1):
    """3 dos 4 artigos: o ato do MEC está fora dos órgãos configurados."""
    _semear(storage, DIA, "DO1", zip_do1)
    resultado = FonteINLABS(cfg, storage, SessaoProibida()).coletar(DIA)

    assert resultado.status == Status.OK
    assert resultado.avisos == []
    assert len(resultado.publicacoes) == 3
    assert all(p.fonte == "inlabs" for p in resultado.publicacoes)
    assert all(p.secao == "1" for p in resultado.publicacoes)
    assert all(p.texto.strip() for p in resultado.publicacoes)
    assert not any("Educação" in p.orgao for p in resultado.publicacoes)


def test_escopo_registra_secoes_e_orgaos(cfg, storage, zip_do1):
    _semear(storage, DIA, "DO1", zip_do1)
    resultado = FonteINLABS(cfg, storage, SessaoProibida()).coletar(DIA)
    assert resultado.escopo["secoes"] == cfg.secoes
    assert resultado.escopo["orgaos"] == cfg.orgaos


def test_nenhuma_secao_com_arquivo_e_dia_sem_edicao(cfg, storage, credenciais):
    """Domingo: `vazio` e — invariante do contrato — sem nenhum aviso."""
    sessao = SessaoFalsa({})
    resultado = FonteINLABS(cfg, storage, sessao).coletar(DOMINGO)
    assert resultado.status == Status.VAZIO
    assert resultado.avisos == []
    assert resultado.publicacoes == []


def test_secao_faltando_entre_varias_vira_aviso_e_a_coleta_segue(storage, zip_do1, credenciais):
    """DO2 não sair não pode custar o que a DO1 trouxe."""
    cfg = ConfigINLABS(secoes=["DO1", "DO2"])
    sessao = SessaoFalsa({"DO1": RespostaFalsa(200, zip_do1)})
    resultado = FonteINLABS(cfg, storage, sessao).coletar(DIA)

    assert resultado.status == Status.PARCIAL
    assert "seção DO2 sem arquivo" in resultado.avisos
    assert len(resultado.publicacoes) == 3


def test_zip_sem_nenhum_orgao_do_escopo_e_parcial(storage, zip_do1):
    """Edição publicada e nada do escopo é quebra em potencial do filtro, não
    domingo: `parcial`, para o agente processar e alertar.
    """
    cfg = ConfigINLABS(orgaos=["Ministério do Turismo"])
    _semear(storage, DIA, "DO1", zip_do1)
    resultado = FonteINLABS(cfg, storage, SessaoProibida()).coletar(DIA)

    assert resultado.status == Status.PARCIAL
    assert resultado.publicacoes == []
    assert any(
        a.startswith("nenhum artigo dos órgãos configurados na(s) seção(ões)")
        for a in resultado.avisos
    ), resultado.avisos
    assert any("DO1" in a for a in resultado.avisos)


def test_aviso_de_xml_ilegivel_chega_ao_resultado(cfg, storage, zip_do1):
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as novo:
        original = zipfile.ZipFile(io.BytesIO(zip_do1))
        for nome in original.namelist():
            novo.writestr(nome, b"<xml><article" if nome.endswith("70.xml") else original.read(nome))
    _semear(storage, DIA, "DO1", saida.getvalue())

    resultado = FonteINLABS(cfg, storage, SessaoProibida()).coletar(DIA)
    assert resultado.status == Status.PARCIAL
    assert any("XML ilegível" in a for a in resultado.avisos), resultado.avisos
    assert len(resultado.publicacoes) == 3


def test_materia_repetida_entre_secoes_entra_uma_vez_so(storage, credenciais):
    """A mesma matéria sai na DO1 e na DO1E; contá-la duas vezes inflaria o dia."""
    cfg = ConfigINLABS(secoes=["DO1", "DO1E"])
    bruto = _zip_com(("777", "Ministério da Saúde/Gabinete do Ministro"))
    sessao = SessaoFalsa({
        "DO1": RespostaFalsa(200, bruto),
        "DO1E": RespostaFalsa(200, bruto),
    })
    resultado = FonteINLABS(cfg, storage, sessao).coletar(DIA)

    assert len(resultado.publicacoes) == 1
    assert resultado.publicacoes[0].origem["id_materia"] == "777"


def test_o_zip_baixado_vai_para_o_cache_bruto(storage, zip_do1, credenciais):
    cfg = ConfigINLABS(secoes=["DO1"])
    sessao = SessaoFalsa({"DO1": RespostaFalsa(200, zip_do1)})
    FonteINLABS(cfg, storage, sessao).coletar(DIA)
    assert storage.ler_raw(DIA, "inlabs", "2026-09-03-DO1.zip") == zip_do1


def test_reprocessar_o_dia_nao_volta_a_rede(storage, zip_do1, credenciais):
    cfg = ConfigINLABS(secoes=["DO1"])
    sessao = SessaoFalsa({"DO1": RespostaFalsa(200, zip_do1)})
    fonte = FonteINLABS(cfg, storage, sessao)
    fonte.coletar(DIA)
    gets, posts = len(sessao.gets), sessao.posts

    segunda = fonte.coletar(DIA)
    assert len(sessao.gets) == gets, "o zip do dia já estava no cache"
    assert sessao.posts == posts, "sem download não há por que logar de novo"
    assert len(segunda.publicacoes) == 3


def test_forcar_ignora_o_cache(storage, zip_do1, credenciais):
    cfg = ConfigINLABS(secoes=["DO1"])
    sessao = SessaoFalsa({"DO1": RespostaFalsa(200, zip_do1)})
    fonte = FonteINLABS(cfg, storage, sessao)
    fonte.coletar(DIA)
    fonte.coletar(DIA, forcar=True)
    assert len(sessao.gets) == 2


def test_login_acontece_uma_vez_por_coleta(storage, zip_do1, credenciais):
    cfg = ConfigINLABS(secoes=["DO1", "DO2", "DO3"])
    sessao = SessaoFalsa({"DO1": RespostaFalsa(200, zip_do1)})
    FonteINLABS(cfg, storage, sessao).coletar(DIA)
    assert sessao.posts == 1, "três seções, um único login"


def test_credenciais_ausentes_sao_falha_da_fonte(cfg, storage, monkeypatch):
    """Sem credencial não há coleta; sair `vazio` diria "domingo" todo dia."""
    monkeypatch.delenv("INLABS_EMAIL", raising=False)
    monkeypatch.delenv("INLABS_SENHA", raising=False)
    with pytest.raises(FonteIndisponivel) as erro:
        FonteINLABS(cfg, storage, SessaoFalsa({})).coletar(DIA)
    assert "INLABS_EMAIL/INLABS_SENHA não definidos" in str(erro.value)


def test_cache_dispensa_credenciais(cfg, storage, zip_do1, monkeypatch):
    """Reprocessar um dia já baixado precisa funcionar sem conta no serviço."""
    monkeypatch.delenv("INLABS_EMAIL", raising=False)
    monkeypatch.delenv("INLABS_SENHA", raising=False)
    _semear(storage, DIA, "DO1", zip_do1)
    assert FonteINLABS(cfg, storage, SessaoProibida()).coletar(DIA).status == Status.OK
