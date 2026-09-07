import dataclasses
import json
from datetime import date, datetime, timezone

import pytest

from boletim.carga import carregar
from boletim.classifica import classificar, item_de_resposta
from boletim.config import ConfigBoletim
from boletim.llm import LLMFalso, LLMIndisponivel
from boletim.prefiltro import triar
from radar.core.modelos import Publicacao, gerar_id


def _pub(n: int) -> Publicacao:
    url = f"https://exemplo/{n}"
    titulo = f"PORTARIA Nº {n}"
    return Publicacao(
        id=gerar_id("inlabs", date(2026, 9, 3), url, titulo),
        fonte="inlabs",
        data_publicacao=date(2026, 9, 3),
        coletado_em=datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc),
        orgao="Ministério da Saúde",
        unidade=None,
        secao="1",
        pagina=n,
        edicao="169",
        tipo="Portaria",
        numero=str(n),
        titulo=titulo,
        ementa=f"Ementa da portaria {n}.",
        texto=f"Texto da portaria {n}.",
        url=url,
        origem={},
    )


def _resposta(pub: Publicacao, **kw) -> dict:
    base = {
        "id": pub.id,
        "categoria": "A",
        "relevancia": 3,
        "resumo": f"resumo de {pub.titulo}",
        "por_que_importa": "importa muito",
        "valor_brl": 1000.0,
        "entes": ["Município de Manhuaçu"],
        "tags": ["habilitação"],
    }
    base.update(kw)
    return base


def _lote(*respostas: dict) -> dict:
    return {"itens": list(respostas)}


@pytest.fixture
def cfg() -> ConfigBoletim:
    config = ConfigBoletim()
    config.lote = 12
    config.tentativas_llm = 2
    return config


# ── item_de_resposta ────────────────────────────────────────────────────
def test_item_de_resposta_junta_publicacao_e_juizo_do_llm():
    pub = _pub(1)
    item = item_de_resposta(pub, _resposta(pub, categoria="B", relevancia=2))
    assert item.id == pub.id
    assert item.titulo == pub.titulo
    assert item.orgao == pub.orgao
    assert item.url == pub.url
    assert item.data_publicacao == pub.data_publicacao
    assert item.categoria == "B"
    assert item.relevancia == 2
    assert item.entes == ("Município de Manhuaçu",)
    assert item.tags == ("habilitação",)
    assert item.fallback is False


def _pub_iofmg(n: int) -> Publicacao:
    return dataclasses.replace(_pub(n), fonte="iofmg")


def test_item_do_iofmg_em_a_ou_b_sobe_para_relevancia_3():
    """O IOF-MG é Minas por definição, e Minas é o mercado do boletim.

    Na primeira semana real o modelo deu relevância 2 a deliberações CIB-SUS/MG
    que alocam recurso a município mineiro enquanto dava 3 a habilitações na
    Bahia. Isso não é ajuste de prompt: é regra, e regra fica no código.
    """
    pub = _pub_iofmg(1)
    for categoria in ("A", "B"):
        item = item_de_resposta(pub, _resposta(pub, categoria=categoria, relevancia=2))
        assert item.relevancia == 3


def test_item_do_iofmg_fora_de_a_e_b_mantem_a_relevancia_do_llm():
    pub = _pub_iofmg(1)
    for categoria in ("C", "D", "X"):
        item = item_de_resposta(pub, _resposta(pub, categoria=categoria, relevancia=1))
        assert item.relevancia == 1


def test_prioridade_do_iofmg_nunca_rebaixa_a_relevancia():
    pub = _pub_iofmg(1)
    assert item_de_resposta(pub, _resposta(pub, relevancia=3)).relevancia == 3


def test_prioridade_do_iofmg_nao_alcanca_o_dou():
    pub = _pub(1)
    assert item_de_resposta(pub, _resposta(pub, relevancia=2)).relevancia == 2


# ── R1: B que é ato administrativo vira X ───────────────────────────────
def _pub_titulado(titulo: str) -> Publicacao:
    return dataclasses.replace(_pub(1), titulo=titulo)


@pytest.mark.parametrize(
    "titulo",
    [
        "EXTRATO DE REGISTRO DE PREÇOS Nº 12/2026",
        "Retificação da Portaria GM/MS nº 4.795",
        "AVISO DE ALTERAÇÃO DE EDITAL Nº 3/2026",
        "Edital de notificação nº 8/2026",
        "EDITAL DE INTIMAÇÃO Nº 9/2026",
        "Despacho de 2 de setembro de 2026",
        "ATA DE REGISTRO DE PREÇOS Nº 45/2026",
        "Termo aditivo nº 4 ao convênio 900123",
        "APOSTILAMENTO Nº 2 AO CONTRATO 77/2026",
    ],
)
def test_b_com_titulo_de_ato_administrativo_vira_x(titulo):
    """A fronteira A/B não é estável entre execuções, e regra fica no código.

    Na semana de 31/08 as mesmas habilitações saíram A numa rodada e B na
    seguinte, com a instrução literal nos dois prompts. Extrato, retificação,
    aviso e despacho nunca são norma: o que o modelo põe em B por causa de uma
    cifra no corpo sai da edição em vez de ocupar "mudança de regra".
    """
    pub = _pub_titulado(titulo)
    item = item_de_resposta(pub, _resposta(pub, categoria="B", relevancia=3))
    assert item.categoria == "X"
    assert item.relevancia == 0
    assert "regra:b-administrativo" in item.tags


def test_titulo_administrativo_so_alcanca_a_categoria_b():
    pub = _pub_titulado("EXTRATO DE REGISTRO DE PREÇOS Nº 12/2026")
    for categoria in ("A", "C", "D", "X"):
        item = item_de_resposta(pub, _resposta(pub, categoria=categoria, relevancia=3))
        assert item.categoria == categoria
        assert "regra:b-administrativo" not in item.tags


def test_edital_de_chamamento_nao_e_ato_administrativo():
    """Só notificação e intimação; edital de chamamento é o coração da seção C."""
    pub = _pub_titulado("EDITAL DE CHAMAMENTO PÚBLICO Nº 12/2026")
    item = item_de_resposta(pub, _resposta(pub, categoria="B", resumo="chamamento"))
    assert item.categoria == "B"


def test_ato_administrativo_so_conta_no_comeco_do_titulo():
    pub = _pub_titulado("PORTARIA GM/MS Nº 12 que aprova a ata da comissão")
    item = item_de_resposta(pub, _resposta(pub, categoria="B", resumo="aprova ata"))
    assert item.categoria == "B"


# ── R2: B que é habilitação vira A ──────────────────────────────────────
@pytest.mark.parametrize(
    "resumo",
    [
        "Habilita o Hospital Santa Luzia no Programa Agora Tem Especialistas.",
        "Credencia estabelecimento para terapia renal substitutiva.",
        "Qualifica a unidade como hospital de ensino.",
        "Desabilita dois leitos de UTI do Hospital São Mateus.",
        "Descredencia o serviço de hemodiálise.",
        "Renovação da habilitação do serviço de oncologia.",
        "Amplia o teto MAC do Hospital César Leite.",
        "Altera o limite financeiro anual do município.",
        "Concede incremento temporário de custeio.",
        "Autoriza repasse fundo a fundo ao município.",
    ],
)
def test_b_que_e_habilitacao_ou_dinheiro_vira_a(resumo):
    pub = _pub(1)
    item = item_de_resposta(pub, _resposta(pub, categoria="B", resumo=resumo))
    assert item.categoria == "A"
    assert "regra:b-para-a" in item.tags


def test_b_para_a_reconhece_a_habilitacao_pelo_titulo():
    pub = _pub_titulado("PORTARIA GM/MS Nº 3.412: habilita leitos de UTI")
    item = item_de_resposta(pub, _resposta(pub, categoria="B", resumo="dez leitos"))
    assert item.categoria == "A"


def test_b_normativo_de_verdade_continua_b():
    pub = _pub(1)
    resumo = "Muda o critério de cálculo do piso da atenção primária."
    item = item_de_resposta(pub, _resposta(pub, categoria="B", resumo=resumo))
    assert item.categoria == "B"
    assert item.tags == ("habilitação",)


def test_ato_administrativo_vence_habilitacao_no_mesmo_item():
    """Um extrato que fala de habilitação continua sendo um extrato."""
    pub = _pub_titulado("EXTRATO DE TERMO DE HABILITAÇÃO Nº 3/2026")
    item = item_de_resposta(pub, _resposta(pub, categoria="B", resumo="habilita"))
    assert item.categoria == "X"
    assert "regra:b-para-a" not in item.tags


def test_regra_de_categoria_preserva_as_tags_do_modelo():
    pub = _pub(1)
    item = item_de_resposta(pub, _resposta(pub, categoria="B", resumo="Habilita leitos"))
    assert item.tags == ("habilitação", "regra:b-para-a")


# ── R3: teto de relevância fora de Minas ────────────────────────────────
def test_a_sem_marca_de_minas_nao_passa_de_relevancia_2():
    """A contraparte do piso do IOF-MG: fora de Minas, o teto é 2.

    Em v2 da semana o modelo deu 3 a 23 itens de 31/08 e 04/09 sem nenhuma
    relação com Minas - habilitações na Bahia, saneamento no Nordeste - e eles
    subiram para o topo da seção de captação, à frente das deliberações
    CIB-SUS/MG. A iteração no prompt derrubou o número, não o fechou.
    """
    pub = _pub(1)
    item = item_de_resposta(pub, _resposta(pub, categoria="A", relevancia=3))
    assert item.relevancia == 2


@pytest.mark.parametrize(
    "marca",
    [
        "Minas Gerais",
        "Hospital de Itabira/MG",
        "Itabira (MG)",
        "Itabira-MG",
        "atende em MG conforme pactuação",
        "SES-MG",
        "SES/MG",
        "CIB-SUS/MG",
        "FHEMIG",
        "Belo Horizonte",
        "consórcio mineiro de saúde",
    ],
)
def test_marca_de_minas_no_titulo_preserva_a_relevancia(marca):
    pub = _pub_titulado(f"PORTARIA GM/MS Nº 3.412 - {marca}")
    item = item_de_resposta(pub, _resposta(pub, categoria="A", relevancia=3))
    assert item.relevancia == 3


def test_marca_de_minas_vale_no_resumo_nos_entes_e_no_texto_integral():
    pub = _pub(1)
    campos = [
        {"resumo": "Habilitação em Belo Horizonte."},
        {"entes": ["Município de Belo Horizonte"]},
    ]
    for campo in campos:
        item = item_de_resposta(pub, _resposta(pub, categoria="A", relevancia=3, **campo))
        assert item.relevancia == 3

    com_texto = dataclasses.replace(pub, texto="Ato publicado no estado de Minas Gerais.")
    item = item_de_resposta(com_texto, _resposta(pub, categoria="A", relevancia=3))
    assert item.relevancia == 3


def test_texto_integral_alem_do_limite_de_leitura_nao_conta(cfg):
    """A marca precisa estar no trecho que o modelo leu, não na página 40."""
    longe = "x" * cfg.max_chars_texto + " Minas Gerais"
    pub = dataclasses.replace(_pub(1), texto=longe)
    item = item_de_resposta(pub, _resposta(pub, categoria="A", relevancia=3), cfg)
    assert item.relevancia == 2


def test_sigla_de_minas_dentro_de_palavra_nao_conta():
    pub = _pub_titulado("PORTARIA que credencia a FHEMIGRANTE e a AMGEN do Paraná")
    item = item_de_resposta(pub, _resposta(pub, categoria="A", relevancia=3))
    assert item.relevancia == 2


def test_teto_fora_de_minas_nao_alcanca_b_nem_as_outras_categorias():
    """B é regra nacional: uma portaria que muda a tabela SUS vale para Minas."""
    pub = _pub(1)
    for categoria in ("B", "C", "D"):
        item = item_de_resposta(pub, _resposta(pub, categoria=categoria, relevancia=3))
        assert item.relevancia == 3


def test_teto_fora_de_minas_nao_sobe_relevancia():
    pub = _pub(1)
    item = item_de_resposta(pub, _resposta(pub, categoria="A", relevancia=1))
    assert item.relevancia == 1


def test_teto_fora_de_minas_nao_alcanca_o_iofmg():
    pub = _pub_iofmg(1)
    item = item_de_resposta(pub, _resposta(pub, categoria="A", relevancia=3))
    assert item.relevancia == 3


def test_b_que_virou_a_tambem_recebe_o_teto():
    """A habilitação da Bahia que a R2 tirou de B não vira prioridade por isso."""
    pub = _pub(1)
    resposta = _resposta(pub, categoria="B", relevancia=3, resumo="Habilita leitos")
    item = item_de_resposta(pub, resposta)
    assert item.categoria == "A"
    assert item.relevancia == 2


# ── R5: cifra repetida no por_que_importa ───────────────────────────────
def _por_que_importa(texto: str, valor: float | None = 2700000.0) -> str:
    pub = _pub(1)
    resposta = _resposta(pub, por_que_importa=texto, valor_brl=valor)
    return item_de_resposta(pub, resposta).por_que_importa


# As quatro frases abaixo saíram de `semana-v2`; a cifra já está no `valor_brl`
# do mesmo item e no card da edição, e repeti-la come o espaço do argumento.
def test_cifra_entre_parenteses_sai_inteira():
    antes = (
        "Muda regra de acesso a recursos para reabilitação (R$ 849 mil). Impacta "
        "indiretamente entidades que executam projetos de reabilitação e inclusão "
        "de pessoas com deficiência."
    )
    assert _por_que_importa(antes) == (
        "Muda regra de acesso a recursos para reabilitação. Impacta indiretamente "
        "entidades que executam projetos de reabilitação e inclusão de pessoas com "
        "deficiência."
    )


def test_cifra_introduzida_por_preposicao_sai_com_a_preposicao():
    antes = (
        "Novo repasse de R$ 2,7 milhões para organização filantrópica; programa de "
        "inclusão e acessibilidade para pessoas com Transtorno do Espectro Autista"
    )
    assert _por_que_importa(antes) == (
        "Novo repasse para organização filantrópica; programa de inclusão e "
        "acessibilidade para pessoas com Transtorno do Espectro Autista"
    )


def test_cifra_em_no_valor_de_sai_com_a_locucao_inteira():
    antes = (
        "MUDA REGRA: Glosas técnicas no valor de R$ 6.300.368,77 são parceladas em "
        "60 vezes via boleto no INVESTSUS. Não quitação incorre em Tomada de Contas "
        "Especial."
    )
    assert _por_que_importa(antes) == (
        "MUDA REGRA: Glosas técnicas são parceladas em 60 vezes via boleto no "
        "INVESTSUS. Não quitação incorre em Tomada de Contas Especial."
    )


def test_cifra_apos_gerundio_de_soma_sai_com_o_gerundio():
    antes = (
        "Abre possibilidade de contratação por estados/municípios; três grandes "
        "estabelecimentos credenciados com matrizes de oferta somando R$ 70,4 "
        "milhões; requer pactuação na CIB estadual"
    )
    assert _por_que_importa(antes) == (
        "Abre possibilidade de contratação por estados/municípios; três grandes "
        "estabelecimentos credenciados com matrizes de oferta; requer pactuação na "
        "CIB estadual"
    )


def test_cifra_que_e_o_objeto_da_frase_fica_onde_esta():
    """Tirar a cifra daqui deixaria "Define como novo limite anual".

    A regra só remove a cifra que vem introduzida por preposição ou isolada
    entre parênteses: nos dois casos o que sobra continua sendo uma frase.
    """
    antes = (
        "Muda os valores máximos que estabelecimentos podem receber. Define "
        "R$ 721.233,95 como novo limite anual."
    )
    assert _por_que_importa(antes) == antes


def test_cifra_fica_quando_o_item_nao_tem_valor():
    """Sem `valor_brl` não há repetição: a cifra do texto é a única que existe."""
    antes = "Contrapartida municipal de R$ 3 mil sobre um total não informado no ato."
    assert _por_que_importa(antes, valor=None) == antes


def test_texto_curto_demais_depois_do_corte_fica_como_estava():
    antes = "Repasse de R$ 2,7 milhões."
    assert _por_que_importa(antes) == antes


def test_por_que_importa_ausente_continua_ausente():
    pub = _pub(1)
    resposta = _resposta(pub, por_que_importa=None)
    assert item_de_resposta(pub, resposta).por_que_importa is None


def test_marcas_de_minas_vem_do_config(cfg):
    cfg.marcas_mg = ["Uberlândia"]
    pub = _pub_titulado("PORTARIA que habilita leitos em Uberlândia")
    assert item_de_resposta(pub, _resposta(pub, relevancia=3), cfg).relevancia == 3

    fora = _pub_titulado("PORTARIA que habilita leitos em Belo Horizonte")
    assert item_de_resposta(fora, _resposta(fora, relevancia=3), cfg).relevancia == 2


# ── caminho feliz ───────────────────────────────────────────────────────
def test_lote_unico_classifica_os_sete_itens_da_fixture(cfg, dir_fixtures):
    carga = carregar(dir_fixtures / "boletim", date(2026, 9, 3), ["inlabs", "iofmg"])
    mantidas = triar(carga.publicacoes, cfg).mantidas
    lote1 = json.loads(
        (dir_fixtures / "boletim" / "llm" / "lote1.json").read_text(encoding="utf-8")
    )
    llm = LLMFalso({"lote-0": lote1})

    itens, avisos = classificar(mantidas, llm, cfg)

    assert len(itens) == 7
    assert avisos == []
    assert len(llm.chamadas) == 1
    assert llm.chamadas[0][0] == "lote-0"
    assert [i.categoria for i in itens] == ["A", "B", "B", "C", "A", "B", "D"]
    assert not any(i.fallback for i in itens)


def test_itens_saem_na_ordem_das_publicacoes_mantidas(cfg):
    pubs = [_pub(1), _pub(2), _pub(3)]
    llm = LLMFalso(
        {"lote-0": _lote(_resposta(pubs[2]), _resposta(pubs[0]), _resposta(pubs[1]))}
    )
    itens, _ = classificar(pubs, llm, cfg)
    assert [i.id for i in itens] == [p.id for p in pubs]


def test_lotes_respeitam_o_tamanho_configurado(cfg):
    cfg.lote = 2
    pubs = [_pub(n) for n in range(1, 5)]
    llm = LLMFalso(
        {
            "lote-0": _lote(_resposta(pubs[0]), _resposta(pubs[1])),
            "lote-1": _lote(_resposta(pubs[2]), _resposta(pubs[3])),
        }
    )
    itens, avisos = classificar(pubs, llm, cfg)
    assert len(itens) == 4
    assert avisos == []
    assert [c[0] for c in llm.chamadas] == ["lote-0", "lote-1"]


# ── tentativas, bisseção e fallback ─────────────────────────────────────
def test_resposta_invalida_na_primeira_tentativa_e_valida_na_segunda(cfg):
    pubs = [_pub(1)]
    llm = LLMFalso(
        {"lote-0": [{"itens": [{"id": pubs[0].id, "categoria": "Z"}]}, _lote(_resposta(pubs[0]))]}
    )
    itens, avisos = classificar(pubs, llm, cfg)
    assert len(itens) == 1
    assert itens[0].fallback is False
    assert len(llm.chamadas) == 2
    assert any("inválida" in a for a in avisos)


def test_lote_incompleto_e_reprocessado_por_bisseccao(cfg):
    pubs = [_pub(n) for n in range(1, 5)]
    metade = _lote(_resposta(pubs[0]), _resposta(pubs[1]))
    llm = LLMFalso(
        {
            "lote-0": [
                metade,
                metade,
                _lote(_resposta(pubs[2])),
                _lote(_resposta(pubs[3])),
            ]
        }
    )
    itens, avisos = classificar(pubs, llm, cfg)

    assert [i.id for i in itens] == [p.id for p in pubs]
    assert not any(i.fallback for i in itens)
    assert len(llm.chamadas) == 4
    # A bisseção só reenvia o que faltou: os dois últimos vão sozinhos.
    assert pubs[0].id not in llm.chamadas[2][2]
    assert pubs[2].id in llm.chamadas[2][2]


def test_item_unico_restante_recebe_retentativa_solo(cfg):
    pubs = [_pub(1), _pub(2), _pub(3)]
    parcial = _lote(_resposta(pubs[0]), _resposta(pubs[1]))
    llm = LLMFalso({"lote-0": [parcial, parcial, _lote(_resposta(pubs[2]))]})

    itens, avisos = classificar(pubs, llm, cfg)

    assert [i.id for i in itens] == [p.id for p in pubs]
    assert not any(i.fallback for i in itens)
    assert len(llm.chamadas) == 3
    # A terceira chamada é a retentativa solo do único item que sobrou.
    assert pubs[0].id not in llm.chamadas[2][2]
    assert pubs[2].id in llm.chamadas[2][2]


def test_item_que_o_llm_nunca_devolve_vira_fallback_d(cfg):
    pubs = [_pub(1), _pub(2)]
    llm = LLMFalso({"lote-0": _lote(_resposta(pubs[0]))})
    itens, avisos = classificar(pubs, llm, cfg)

    assert len(itens) == 2
    orfao = itens[1]
    assert orfao.categoria == "D"
    assert orfao.relevancia == 1
    assert orfao.resumo == "Ementa da portaria 2."
    assert orfao.fallback is True
    assert "1 itens sem classificação por LLM (fallback D)" in avisos


def test_fallback_usa_o_titulo_quando_nao_ha_ementa(cfg):
    pub = _pub(1)
    sem_ementa = dataclasses.replace(pub, ementa=None)
    llm = LLMFalso({"lote-0": _lote()})
    itens, _ = classificar([sem_ementa], llm, cfg)
    assert itens[0].resumo == sem_ementa.titulo


def test_id_estranho_na_resposta_e_ignorado_com_aviso(cfg):
    pubs = [_pub(1)]
    intruso = dict(_resposta(pubs[0]), id="idqueninguempediu")
    llm = LLMFalso({"lote-0": _lote(_resposta(pubs[0]), intruso)})
    itens, avisos = classificar(pubs, llm, cfg)

    assert len(itens) == 1
    assert itens[0].id == pubs[0].id
    assert any("idqueninguempediu" in a for a in avisos)


# ── LLM fora do ar ──────────────────────────────────────────────────────
class _Relogio:
    """Dublê da espera entre retentativas: registra em vez de dormir."""

    def __init__(self) -> None:
        self.esperas: list[float] = []

    def __call__(self, segundos: float) -> None:
        self.esperas.append(segundos)


class _CaiAntesDeResponder:
    """LLM que fica indisponível nas N primeiras chamadas de cada rótulo."""

    def __init__(self, base: LLMFalso, quedas: dict[str, int]) -> None:
        self.base = base
        self.quedas = dict(quedas)

    @property
    def chamadas(self) -> list[tuple[str, str, str]]:
        return self.base.chamadas

    def completar_json(self, sistema, usuario, schema, *, rotulo) -> dict:
        if self.quedas.get(rotulo, 0) > 0:
            self.quedas[rotulo] -= 1
            raise LLMIndisponivel(f"llm {rotulo}: sem resposta em 180s")
        return self.base.completar_json(sistema, usuario, schema, rotulo=rotulo)


def test_llm_indisponivel_na_primeira_chamada_de_todas_propaga(cfg):
    relogio = _Relogio()
    with pytest.raises(LLMIndisponivel):
        classificar([_pub(1)], LLMFalso({}), cfg, esperar=relogio)
    assert relogio.esperas == []


def test_queda_no_meio_do_dia_e_retentada_com_espera(cfg):
    """Uma queda depois do primeiro lote quase sempre é transitória.

    Em 01/09 e 03/09 a sessão OAuth expirou no meio da rodada e 20 e 26 itens
    foram para o fallback D sem que ninguém tentasse de novo. A reexecução de
    03/09 passou inteira, com lotes de 70 a 90 s: era soluço, não indisponibilidade.
    """
    cfg.lote = 1
    pubs = [_pub(1), _pub(2)]
    base = LLMFalso(
        {"lote-0": _lote(_resposta(pubs[0])), "lote-1": _lote(_resposta(pubs[1]))}
    )
    llm = _CaiAntesDeResponder(base, quedas={"lote-1": 1})
    relogio = _Relogio()

    itens, avisos = classificar(pubs, llm, cfg, esperar=relogio)

    assert not any(i.fallback for i in itens)
    assert relogio.esperas == [20]
    assert avisos == []


def test_retentativa_desiste_depois_de_duas_esperas(cfg):
    cfg.lote = 1
    pubs = [_pub(1), _pub(2)]
    llm = LLMFalso({"lote-0": _lote(_resposta(pubs[0]))})
    relogio = _Relogio()

    itens, avisos = classificar(pubs, llm, cfg, esperar=relogio)

    assert relogio.esperas == [20, 60]
    assert itens[0].fallback is False
    assert itens[1].fallback is True
    assert "1 itens sem classificação por LLM (fallback D)" in avisos


def test_aviso_de_indisponibilidade_traz_a_mensagem_do_erro(cfg):
    """Sem a mensagem, o aviso do dia não distingue timeout de cota estourada."""
    cfg.lote = 1
    pubs = [_pub(1), _pub(2)]
    llm = LLMFalso({"lote-0": _lote(_resposta(pubs[0]))})

    _, avisos = classificar(pubs, llm, cfg, esperar=_Relogio())

    indisponivel = [a for a in avisos if "LLM indisponível" in a]
    assert indisponivel == [
        "lote-1: LLM indisponível (llm falso: sem resposta para o rótulo lote-1), "
        "o restante do dia fica sem classificação"
    ]


def test_llm_que_cai_depois_do_primeiro_lote_vira_fallback(cfg):
    cfg.lote = 1
    pubs = [_pub(1), _pub(2)]
    llm = LLMFalso({"lote-0": _lote(_resposta(pubs[0]))})
    itens, avisos = classificar(pubs, llm, cfg, esperar=_Relogio())

    assert len(itens) == 2
    assert itens[0].fallback is False
    assert itens[1].fallback is True
    assert "1 itens sem classificação por LLM (fallback D)" in avisos


def test_sem_publicacoes_nao_chama_o_llm(cfg):
    llm = LLMFalso({})
    assert classificar([], llm, cfg) == ([], [])
    assert llm.chamadas == []


# ── orçamento global de chamadas ────────────────────────────────────────
_INVALIDA = {"itens": [{"id": "idqualquer", "categoria": "Z"}]}


def test_resposta_sempre_invalida_nao_multiplica_as_chamadas(cfg):
    """Schema quebrado no lote inteiro não pode virar fan-out ilimitado.

    Antes do orçamento, 24 publicações viravam 92 chamadas: só
    `LLMIndisponivel` desistia, e a bisseção recursiva multiplicava as
    tentativas de uma resposta que nunca ia validar. `--max-budget-usd` é por
    chamada, então quem paga a conta é a cota da assinatura.
    """
    pubs = [_pub(n) for n in range(1, 25)]
    llm = LLMFalso({"lote-0": _INVALIDA, "lote-1": _INVALIDA})

    itens, avisos = classificar(pubs, llm, cfg)

    assert len(llm.chamadas) <= 3 * 2 + 2
    assert len(itens) == 24
    assert all(item.categoria == "D" and item.fallback for item in itens)
    assert "24 itens sem classificação por LLM (fallback D)" in avisos


def test_orcamento_esgotado_desiste_com_aviso(cfg):
    """Com muitas tentativas por lote, quem encerra a rodada é o teto global."""
    cfg.tentativas_llm = 5
    pubs = [_pub(n) for n in range(1, 25)]
    llm = LLMFalso({"lote-0": _INVALIDA, "lote-1": _INVALIDA})

    itens, avisos = classificar(pubs, llm, cfg)

    assert len(llm.chamadas) == 3 * 2 + 2
    assert any("orçamento de chamadas esgotado" in aviso for aviso in avisos)
    assert all(item.fallback for item in itens)


def test_item_solo_reprovado_seguidamente_encerra_a_rodada(cfg):
    """`tentativas_llm` rejeições seguidas num item só é formato quebrado.

    Um item sozinho é o menor pedido possível: se nem ele volta no schema, o
    resto do dia não vai voltar, e insistir só gasta cota.
    """
    cfg.lote = 1
    pubs = [_pub(1), _pub(2)]
    llm = LLMFalso({"lote-0": _INVALIDA, "lote-1": _INVALIDA})

    itens, avisos = classificar(pubs, llm, cfg)

    assert len(llm.chamadas) == cfg.tentativas_llm
    assert all(item.fallback for item in itens)
    assert any("fora do schema" in aviso for aviso in avisos)
