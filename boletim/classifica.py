"""Classificação das publicações mantidas, lote a lote, com o LLM.

Três defesas contra o modelo, na ordem em que custam: validação do schema,
reconciliação por id e bisseção do lote. A quarta e última é o fallback D, que
nunca deixa uma publicação sumir da edição por causa de uma resposta ruim -
ela aparece como "outro ato", marcada, em vez de desaparecer em silêncio.

Depois que a resposta chega há um último passo, este determinístico: as regras
de `item_de_resposta`. Elas existem porque o prompt não fecha fronteira - na
semana de 31/08 as mesmas habilitações saíram A numa execução e B na seguinte,
com a instrução literal nos dois casos. O que precisa ser estável entre
execuções vira código; o prompt fica com o que é julgamento.
"""

from __future__ import annotations

import math
import re
import time
from functools import lru_cache
from typing import Any, Callable, Sequence

from boletim.config import ConfigBoletim
from boletim.edicao import Item
from boletim.esquemas import LOTE_SCHEMA, validar
from boletim.llm import LLM, LLMIndisponivel
from boletim.prompts import SISTEMA_CLASSIFICACAO, montar_lote
from radar.core.log import configurar_log
from radar.core.modelos import Publicacao

_LIMITE_RESUMO_FALLBACK = 200
_RELEVANCIA_MAXIMA = 3
_RELEVANCIA_FORA_DE_MG = 2

# Esperas, em segundos, antes de cada retentativa de um lote que caiu no meio do
# dia. Duas bastam: o que derruba a chamada no meio de uma rodada é sessão OAuth
# renovando ou limite momentâneo, e um minuto cobre os dois. Mais que isso
# atrasaria a edição por um modelo que de fato saiu do ar.
ESPERAS_RETENTATIVA = (20, 60)


def classificar(
    mantidas: Sequence[Publicacao],
    llm: LLM,
    cfg: ConfigBoletim,
    *,
    esperar: Callable[[float], None] = time.sleep,
) -> tuple[list[Item], list[str]]:
    """Devolve um `Item` por publicação mantida, na mesma ordem, mais avisos.

    Sempre um item por publicação: quem lê o boletim precisa saber que o ato
    existiu, mesmo quando o modelo não conseguiu opinar sobre ele.

    `esperar` é injetável para que o teste da retentativa não durma 80 s.
    """
    logger = configurar_log()
    respostas: dict[str, dict[str, Any]] = {}
    avisos: list[str] = []
    estado = _Estado(orcamento_chamadas=orcamento_de_chamadas(len(mantidas), cfg))

    for indice in range(0, len(mantidas), cfg.lote):
        lote = list(mantidas[indice : indice + cfg.lote])
        rotulo = f"lote-{indice // cfg.lote}"
        _resolver(lote, llm, cfg, rotulo, respostas, avisos, estado, esperar)

    itens: list[Item] = []
    sem_classificacao = 0
    for pub in mantidas:
        resposta = respostas.get(pub.id)
        if resposta is None:
            sem_classificacao += 1
            itens.append(_item_fallback(pub))
        else:
            itens.append(item_de_resposta(pub, resposta, cfg))

    if sem_classificacao:
        aviso = f"{sem_classificacao} itens sem classificação por LLM (fallback D)"
        avisos.append(aviso)
        logger.warning(aviso)
    return itens, avisos


def orcamento_de_chamadas(mantidas: int, cfg: ConfigBoletim) -> int:
    """Teto global de chamadas ao LLM para a execução inteira.

    O `--max-budget-usd` do CLI é por chamada, não por dia. Sem um teto global,
    uma resposta que nunca valida no schema - exatamente o que uma mudança de
    versão do CLI produziria - faz a bisseção recursiva multiplicar as
    tentativas: 24 publicações viraram 92 chamadas na medição, e um dia real de
    120 mantidas passaria de 400. Isso queima a cota da assinatura, estoura o
    tempo do job e enche o `itens.json` de avisos.

    Três chamadas por lote cobrem com folga o caminho normal (tentativas mais
    bisseção), o `+2` paga as retentativas solo do fim, e o piso de 4 vale para
    o dia de uma publicação só.
    """
    lotes = math.ceil(mantidas / cfg.lote) if mantidas else 0
    return max(4, 3 * lotes + 2)


class _Estado:
    """O que o LLM já entregou nesta execução, e se ele ainda está de pé.

    Importa para o exit code: cair antes do primeiro lote é falha total e o CLI
    sai 2; cair depois é edição parcial, que ainda vale a pena publicar.

    `orcamento_chamadas` e `rejeicoes_seguidas` são os dois freios do fan-out:
    o primeiro é o teto do dia, o segundo desiste quando nem um item sozinho
    volta no schema - aí não é azar, é o formato da resposta que mudou.
    """

    def __init__(self, orcamento_chamadas: int) -> None:
        self.algum_sucesso = False
        self.desistiu = False
        self.orcamento_chamadas = orcamento_chamadas
        self.rejeicoes_seguidas = 0


def _resolver(
    pubs: list[Publicacao],
    llm: LLM,
    cfg: ConfigBoletim,
    rotulo: str,
    respostas: dict[str, dict[str, Any]],
    avisos: list[str],
    estado: _Estado,
    esperar: Callable[[float], None],
) -> None:
    """Preenche `respostas` com o que o LLM disser sobre `pubs`.

    Tenta o lote inteiro até `cfg.tentativas_llm` vezes; o que sobrar volta
    dividido ao meio, porque o mais comum é um único ato gigante estourar o
    contexto e levar junto os vizinhos que teriam sido classificados bem.
    """
    logger = configurar_log()
    if not pubs or estado.desistiu:
        return
    esperados = {p.id for p in pubs}

    for tentativa in range(1, cfg.tentativas_llm + 1):
        if estado.orcamento_chamadas <= 0:
            estado.desistiu = True
            avisos.append(
                f"{rotulo}: orçamento de chamadas esgotado, "
                "o restante do dia fica sem classificação"
            )
            logger.warning(
                "%s: orçamento de chamadas esgotado depois de %d respostas",
                rotulo,
                len(respostas),
            )
            return
        estado.orcamento_chamadas -= 1
        try:
            bruto = _completar(llm, pubs, cfg, rotulo, estado, esperar, logger)
        except LLMIndisponivel as exc:
            if not estado.algum_sucesso:
                # Nada classificado ainda: não é uma resposta ruim, é o modelo
                # fora do ar. Propagar deixa o CLI sair 2 em vez de publicar
                # uma edição inteira de fallback D.
                raise
            estado.desistiu = True
            avisos.append(
                f"{rotulo}: LLM indisponível ({exc}), "
                "o restante do dia fica sem classificação"
            )
            logger.warning(
                "%s: LLM indisponível depois de %d respostas: %s",
                rotulo,
                len(respostas),
                exc,
            )
            return

        erros = validar(bruto, LOTE_SCHEMA)
        if erros:
            avisos.append(
                f"{rotulo}: resposta inválida na tentativa {tentativa}: {erros[0]}"
            )
            logger.warning("%s: resposta inválida (%d erros)", rotulo, len(erros))
            if len(pubs) == 1:
                # Um item sozinho é o menor pedido possível. Se nem ele volta no
                # schema, insistir no resto do dia só gasta cota: o que mudou
                # foi o formato da resposta, não o tamanho do lote.
                estado.rejeicoes_seguidas += 1
                if estado.rejeicoes_seguidas >= cfg.tentativas_llm:
                    estado.desistiu = True
                    avisos.append(
                        f"{rotulo}: {estado.rejeicoes_seguidas} respostas seguidas "
                        "fora do schema em item único, o restante do dia fica "
                        "sem classificação"
                    )
                    logger.warning(
                        "%s: %d respostas seguidas fora do schema em item único",
                        rotulo,
                        estado.rejeicoes_seguidas,
                    )
                    return
            continue

        estado.rejeicoes_seguidas = 0
        for item in bruto["itens"]:
            if item["id"] in esperados:
                respostas[item["id"]] = item
                estado.algum_sucesso = True
            else:
                avisos.append(f"{rotulo}: id fora do lote ignorado: {item['id']}")
        if esperados <= respostas.keys():
            return

    faltantes = [p for p in pubs if p.id not in respostas]
    if not faltantes:
        return
    if len(faltantes) == 1:
        # Bisseção "até tamanho 1": o item sozinho ainda merece uma chamada só
        # dele antes de virar fallback D. A recursão termina porque, dentro
        # dela, `pubs` já é esse mesmo item único (`len(pubs) == 1`).
        if len(pubs) > 1:
            _resolver(faltantes, llm, cfg, rotulo, respostas, avisos, estado, esperar)
        return
    meio = len(faltantes) // 2
    _resolver(faltantes[:meio], llm, cfg, rotulo, respostas, avisos, estado, esperar)
    _resolver(faltantes[meio:], llm, cfg, rotulo, respostas, avisos, estado, esperar)


def _completar(
    llm: LLM,
    pubs: list[Publicacao],
    cfg: ConfigBoletim,
    rotulo: str,
    estado: _Estado,
    esperar: Callable[[float], None],
    logger: Any,
) -> dict[str, Any]:
    """Uma chamada de classificação, com retentativa quando o modelo cai.

    A queda no meio de uma rodada é quase sempre transitória: em 01/09 e 03/09
    da primeira semana real foi a sessão OAuth expirando, e 20 e 26 itens foram
    para o fallback D sem que ninguém tentasse de novo - entre eles as
    deliberações CIB-SUS/MG de maior valor da semana. A reexecução de 03/09
    passou inteira minutos depois.

    Antes do primeiro sucesso não há retentativa: aí a queda é o modelo fora do
    ar de verdade, e o lugar de descobrir isso é o exit code, não 80 s de espera.
    """
    prompt = montar_lote(pubs, cfg)
    esperas = ESPERAS_RETENTATIVA if estado.algum_sucesso else ()
    for indice in range(len(esperas) + 1):
        try:
            return llm.completar_json(
                SISTEMA_CLASSIFICACAO, prompt, LOTE_SCHEMA, rotulo=rotulo
            )
        except LLMIndisponivel as exc:
            if indice >= len(esperas) or estado.orcamento_chamadas <= 0:
                raise
            espera = esperas[indice]
            estado.orcamento_chamadas -= 1
            logger.warning(
                "%s: LLM indisponível (%s), nova tentativa em %d s", rotulo, exc, espera
            )
            esperar(espera)
    raise AssertionError("laço de retentativa sempre retorna ou levanta")


def item_de_resposta(
    pub: Publicacao, resposta: dict[str, Any], cfg: ConfigBoletim | None = None
) -> Item:
    """Junta o que o `radar` coletou com o juízo que o LLM emitiu.

    Os fatos vêm sempre da publicação; do modelo vem a leitura dela, já passada
    pelas regras determinísticas de `_pos_processar`. O `cfg` entra por causa
    das marcas de Minas e do tamanho do texto que o modelo leu; sem ele valem os
    padrões, que são os do `config/config.yaml`.
    """
    cfg = cfg if cfg is not None else ConfigBoletim()
    categoria, relevancia, tags = _pos_processar(pub, resposta, cfg)
    return Item(
        id=pub.id,
        fonte=pub.fonte,
        orgao=pub.orgao,
        unidade=pub.unidade,
        tipo=pub.tipo,
        numero=pub.numero,
        data_publicacao=pub.data_publicacao,
        secao=pub.secao,
        pagina=pub.pagina,
        edicao=pub.edicao,
        titulo=pub.titulo,
        url=pub.url,
        categoria=categoria,
        relevancia=relevancia,
        resumo=resposta["resumo"],
        por_que_importa=_sem_cifra_repetida(
            resposta["por_que_importa"], resposta["valor_brl"]
        ),
        valor_brl=resposta["valor_brl"],
        entes=tuple(resposta["entes"]),
        tags=tags,
    )


# ── regras determinísticas depois do modelo ─────────────────────────────
TAG_B_ADMINISTRATIVO = "regra:b-administrativo"
TAG_B_PARA_A = "regra:b-para-a"

_ACENTOS = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn")
_ESPACO = re.compile(r"\s+")

# Tipos de ato que nunca são norma. O modelo os manda para B quando o corpo cita
# dinheiro, e eles entram na edição ocupando a seção de mudança de regra: em
# 31/08, 5 dos 8 itens de B eram extrato ou retificação.
#
# O plural conta: o DOU publica "EXTRATOS DE REGISTROS DE PREÇOS" e "EXTRATOS DE
# CONVÊNIOS" como um bloco só, e sem ele dois itens de 03/09 e 04/09 escapavam.
#
# "Aviso" sozinho não serve: "AVISO DE CHAMAMENTO PÚBLICO" é o começo de um
# chamamento, o coração da seção C, e a regra o mandava para fora da edição.
# Só o aviso que anuncia um trâmite - licitação, alteração de edital, resultado,
# homologação, suspensão - é ato administrativo.
_AVISO_ADMINISTRATIVO = (
    "licita|altera|padroniza|resultado|homologa|suspens|revoga|dispensa"
    "|penalidade|cancelamento"
)
_TITULO_ADMINISTRATIVO = re.compile(
    r"^(?:(?:extratos?|retifica(?:cao|coes)"
    r"|edita(?:l|is) de (?:notificac(?:ao|oes)|intimac(?:ao|oes))"
    r"|despachos?|atas?|termos? aditivos?|apostilamentos?)\b"
    rf"|avisos? de (?:{_AVISO_ADMINISTRATIVO}))"
)
# Vocabulário de captação. Habilitar, credenciar e mexer em teto é dinheiro novo
# para quem lê o boletim, não mudança de regra - e é exatamente a fronteira que
# o modelo atravessa de uma execução para a outra.
_CAPTACAO = re.compile(
    r"\b(?:habilita|credencia|qualifica|desabilita|descredencia"
    r"|renova(?:cao)? (?:da )?habilitacao|teto|limite financeiro"
    r"|incremento|repasse)"
)
# O verbo de captação só conta onde o ato se anuncia: no título ou na abertura
# do resumo. Procurá-lo no resumo inteiro puxava norma de verdade para A - a
# `RESOLUÇÃO DA DIRETORIA COLEGIADA ANVISA nº 1.039` virou captação porque o
# corpo dizia "habilita a Reblas". É o mesmo recorte que `medir-g11.py` usa.
_ABERTURA_RESUMO = 60
# Ato cujo título já se declara norma não é habilitação, por mais que o corpo
# fale de teto ou de repasse.
_TITULO_NORMATIVO = re.compile(
    r"^(?:resolucao|rdc|instrucao normativa|decreto|lei)\b"
)
# Alcance nacional é a outra marca de norma: "altera o critério de cálculo do
# teto financeiro de todos os municípios" muda regra para o país inteiro, e em
# A ele ainda levava o teto de relevância da R3 por não citar Minas.
_ESCOPO_NACIONAL = re.compile(
    r"todos os municipios|todos os estados|nacional|em todo o pais"
)


# ── R5: a cifra que o item já carrega não se repete no argumento ────────
# O `valor_brl` vira uma linha própria na edição. Repeti-la em `por_que_importa`
# come o espaço do argumento, e a proibição literal no prompt não resolveu: 27
# itens repetiam a cifra em v1 da semana e os mesmos 27 em v2.
_MOEDA = r"R\$\s?[\d.,]*\d(?:\s?(?:milh(?:ão|ões)|bilh(?:ão|ões)|mil|bi)\b)?"
_MOEDA_RX = re.compile(_MOEDA, re.IGNORECASE)
# "R$ 3 milhões anuais" sai inteiro: deixar "anuais" para trás produz
# concordância solta ("nova fonte de receita anuais").
_UNIDADE = r"(?:\s+(?:anuais|anual|mensais|mensal|adicionais|adicional))?"
_APROXIMACAO = r"(?:apenas|quase|cerca de|até|mais de|aproximadamente)\s+"
# Locuções cujo único complemento é a cifra: sem ela, elas também não param de pé.
_PONTE = (
    r"no valor de|no montante de|no total de|somando|totalizando"
    r"|equivalente a|correspondente a"
)
# A cifra só sai quando vem isolada entre parênteses ou introduzida por uma
# preposição (ou por uma das locuções-ponte). Cifra que é sujeito ou objeto da
# frase fica onde está: tirá-la deixaria "Define como novo limite anual".
#
# O terceiro padrão é o da forma mais comum da rodada v3, "acesso a R$ 3,04
# milhões anuais em CVCF": ali a preposição fica e quem sai é a cifra com o "em"
# que a ligava ao que ela conta, de modo que a preposição passa a reger o
# complemento ("acesso a CVCF").
_REMOCOES = tuple(
    (re.compile(padrao, re.IGNORECASE), troca)
    for padrao, troca in (
        (rf"\s*\([^()]{{0,40}}{_MOEDA}[^()]{{0,25}}\)", ""),
        (rf"\s+(?:{_PONTE})\s+(?:{_APROXIMACAO})?{_MOEDA}{_UNIDADE}", ""),
        (
            rf"\b(a|ao|de|em|para|com|por)\s+(?:{_APROXIMACAO})?"
            rf"{_MOEDA}{_UNIDADE}\s+em\s+",
            r"\1 ",
        ),
        (rf"\s+(?:de|em|com|por)\s+(?:{_APROXIMACAO})?{_MOEDA}{_UNIDADE}", ""),
    )
)
_PASSES_REMOCAO = 3
_MIN_POR_QUE_IMPORTA = 25

_ESPACO_SOBRANDO = re.compile(r" {2,}")
_ESPACO_ANTES_DE_PONTUACAO = re.compile(r"\s+([,.;:)])")
_PONTUACAO_DOBRADA = re.compile(r"([,;:])\s*([,.;:])")

# Terminações de verbo conjugado ou no infinitivo, mais as poucas palavras
# comuns que terminam igual sem ser verbo. O teste é grosseiro de propósito: ele
# existe só para barrar a remoção que deixaria um sintagma sem predicado, e um
# falso positivo não muda nada, porque as remoções já são conservadoras.
_TERMINACOES_VERBO = (
    "ndo", "ram", "rem", "vam", "ria", "ou", "am", "em", "ar", "er", "ir",
)
_NAO_SAO_VERBOS = frozenset(
    "para com sem bem tambem alem porem nem quem alguem ninguem hospitalar "
    "familiar particular similar militar escolar popular regular auxiliar "
    "exemplar lugar mar par item".split()
)


def _sem_cifra_repetida(
    por_que_importa: str | None, valor_brl: float | None
) -> str | None:
    """Tira do argumento a cifra que o item já carrega em `valor_brl`.

    Sem `valor_brl` não há repetição - a cifra do texto é a única que existe - e
    o texto passa intacto. Depois do corte valem duas guardas: o que sobrou
    precisa continuar tendo tamanho de frase e não pode ter perdido o verbo que
    o original tinha. Falhando qualquer uma delas, volta o texto do modelo.
    """
    if not por_que_importa or valor_brl is None:
        return por_que_importa
    if not _MOEDA_RX.search(por_que_importa):
        return por_que_importa

    novo = por_que_importa
    for _ in range(_PASSES_REMOCAO):
        antes = novo
        for remocao, troca in _REMOCOES:
            novo = remocao.sub(troca, novo)
        if novo == antes:
            break

    novo = _limpar(novo)
    if len(novo) < _MIN_POR_QUE_IMPORTA:
        return por_que_importa
    if _tem_verbo(por_que_importa) and not _tem_verbo(novo):
        return por_que_importa
    return novo


def _limpar(texto: str) -> str:
    """Fecha os buracos que a remoção deixa: espaço duplo e pontuação órfã."""
    texto = _ESPACO_SOBRANDO.sub(" ", texto)
    texto = _ESPACO_ANTES_DE_PONTUACAO.sub(r"\1", texto)
    texto = _PONTUACAO_DOBRADA.sub(r"\2", texto)
    return texto.strip().strip(",;:").strip()


def _tem_verbo(texto: str) -> bool:
    for bruto in _normalizar(texto).split():
        palavra = bruto.strip(".,;:()[]\"'!?%")
        if len(palavra) < 3 or palavra in _NAO_SAO_VERBOS:
            continue
        if palavra.endswith(_TERMINACOES_VERBO):
            return True
    return False


def _normalizar(texto: str) -> str:
    """Caixa baixa, sem acento e com espaço único: o alvo de todas as regras."""
    return _ESPACO.sub(" ", texto.casefold().translate(_ACENTOS))


# A sigla do estado é a única marca que colide com uma unidade de medida: antes
# dela não pode vir número, nem número seguido de espaço.
_SIGLA_MG = "mg"
_GUARDA_MILIGRAMA = r"(?<!\d)(?<!\d\s)"


@lru_cache(maxsize=4)
def _padrao_marcas(marcas: tuple[str, ...]) -> re.Pattern[str]:
    """Uma alternação com as marcas de Minas já normalizadas.

    Em cache porque a lista vem do config e não muda dentro de uma execução,
    enquanto a função roda uma vez por publicação classificada.
    """
    return re.compile("|".join(_padrao_marca(m) for m in marcas if m))


def _padrao_marca(marca: str) -> str:
    alvo = _normalizar(marca)
    padrao = re.escape(alvo)
    if alvo == _SIGLA_MG:
        # A marca era " MG " com espaço dos dois lados, e por isso "Pirajuba -
        # MG," - do jeito que o diário escreve - não casava: a vírgula ocupava o
        # lugar do espaço. Fronteira de palavra resolve, mas "mg" também é
        # miligrama, e "500 mg de dipirona" não é Minas.
        return _GUARDA_MILIGRAMA + r"\b" + padrao + r"\b"
    if alvo[:1].isalnum():
        padrao = r"\b" + padrao
    # Só a marca escrita em maiúscula é sigla fechada: "FHEMIG" não pode valer
    # por "FHEMIGRANTE", mas "mineir" existe justamente para pegar "mineiro".
    if marca[-1:].isupper() or marca[-1:].isdigit():
        padrao += r"\b"
    return padrao


def _tem_marca_mg(
    pub: Publicacao, resposta: dict[str, Any], cfg: ConfigBoletim
) -> bool:
    """Se o ato cita Minas em algum lugar do que o modelo teve à frente.

    O texto entra só até `max_chars_texto`: a marca precisa estar no trecho que
    o modelo leu, senão o item seria promovido por uma menção que ninguém viu.
    Os campos são unidos por espaço para que nenhuma marca case atravessando a
    fronteira entre dois deles.
    """
    alvo = " ".join(
        [
            pub.titulo,
            resposta["resumo"],
            *resposta["entes"],
            pub.texto[: cfg.max_chars_texto],
        ]
    )
    padrao = _padrao_marcas(tuple(cfg.marcas_mg))
    return bool(padrao.search(f" {_normalizar(alvo)} "))


def _pos_processar(
    pub: Publicacao, resposta: dict[str, Any], cfg: ConfigBoletim
) -> tuple[str, int, tuple[str, ...]]:
    """Aplica as regras determinísticas à resposta do modelo.

    A ordem importa: a categoria é decidida antes da relevância, porque o piso
    do IOF-MG olha a categoria final, e o ato administrativo que sai de B leva a
    relevância a zero de qualquer jeito.

    Cada regra que muda alguma coisa deixa uma tag no item, para que a auditoria
    de uma rodada saiba dizer o que foi do modelo e o que foi do código.
    """
    categoria = resposta["categoria"]
    relevancia = resposta["relevancia"]
    tags = list(resposta["tags"])
    movido_para_a = False

    if categoria == "B":
        if _TITULO_ADMINISTRATIVO.search(_normalizar(pub.titulo)):
            categoria, relevancia = "X", 0
            tags.append(TAG_B_ADMINISTRATIVO)
        elif _e_captacao(pub, resposta):
            categoria = "A"
            movido_para_a = True
            tags.append(TAG_B_PARA_A)

    relevancia = _relevancia(pub, resposta, categoria, relevancia, cfg, movido_para_a)
    return categoria, relevancia, tuple(tags)


def _e_captacao(pub: Publicacao, resposta: dict[str, Any]) -> bool:
    """Se o B que o modelo devolveu é, na verdade, dinheiro novo para alguém.

    Duas guardas antes do vocabulário, e as duas vieram de casos reais: um ato
    que se anuncia como norma no título continua norma (a RDC da Anvisa que
    "habilita a Reblas" no corpo), e um ato de alcance nacional também (o que
    "altera o critério de cálculo do teto financeiro de todos os municípios").
    Os dois viravam A, e em A o teto da R3 ainda os rebaixava por não citarem
    Minas: uma mudança de regra federal saía da seção certa e da ordenação.

    O verbo vale no título ou nos primeiros 60 caracteres do resumo, onde o ato
    diz o que faz. Mais adiante ele costuma ser contexto.
    """
    titulo = _normalizar(pub.titulo)
    resumo = _normalizar(resposta["resumo"])
    if _TITULO_NORMATIVO.match(titulo) or _ESCOPO_NACIONAL.search(resumo):
        return False
    return bool(
        _CAPTACAO.search(titulo) or _CAPTACAO.search(resumo[:_ABERTURA_RESUMO])
    )


def _relevancia(
    pub: Publicacao,
    resposta: dict[str, Any],
    categoria: str,
    relevancia: int,
    cfg: ConfigBoletim,
    movido_para_a: bool = False,
) -> int:
    """Piso do IOF-MG e teto de quem não fala de Minas: as duas pontas da régua.

    Todo ato do IOF-MG é mineiro por definição, e Minas é o mercado do boletim.
    Deixar isso a cargo do prompt não funcionou: na semana de 31/08 o modelo deu
    3 a habilitações na Bahia e 2 a deliberações CIB-SUS/MG que alocam recurso a
    município mineiro. O piso vale só para A e B - um ato de rotina do estado
    não vira prioridade só por ser de Minas.

    O teto é a contraparte e vale só para A: captação que não cita Minas em
    lugar nenhum não é prioridade do dia, por maior que seja a cifra. B fica de
    fora porque mudança de regra federal alcança Minas junto com o país.

    O A que veio da R2 só recebe o teto quando o ato nomeia o ente beneficiado:
    aí ele é mesmo alocação para um lugar, e o lugar não é Minas. Sem ente
    nominal, o que a R2 moveu é um ato de alcance amplo, e rebaixá-lo repetiria
    em A o erro que o teto existe para evitar em B.
    """
    if pub.fonte == "iofmg" and categoria in ("A", "B"):
        return max(relevancia, _RELEVANCIA_MAXIMA)
    if movido_para_a and not resposta["entes"]:
        return relevancia
    if categoria == "A" and not _tem_marca_mg(pub, resposta, cfg):
        return min(relevancia, _RELEVANCIA_FORA_DE_MG)
    return relevancia


def _item_fallback(pub: Publicacao) -> Item:
    """Item de última instância: aparece como "outro ato", marcado."""
    return Item(
        id=pub.id,
        fonte=pub.fonte,
        orgao=pub.orgao,
        unidade=pub.unidade,
        tipo=pub.tipo,
        numero=pub.numero,
        data_publicacao=pub.data_publicacao,
        secao=pub.secao,
        pagina=pub.pagina,
        edicao=pub.edicao,
        titulo=pub.titulo,
        url=pub.url,
        categoria="D",
        relevancia=1,
        resumo=(pub.ementa or pub.titulo)[:_LIMITE_RESUMO_FALLBACK],
        fallback=True,
    )
