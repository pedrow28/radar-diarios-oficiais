"""Classificação das publicações mantidas, lote a lote, com o LLM.

Três defesas contra o modelo, na ordem em que custam: validação do schema,
reconciliação por id e bisseção do lote. A quarta e última é o fallback D, que
nunca deixa uma publicação sumir da edição por causa de uma resposta ruim -
ela aparece como "outro ato", marcada, em vez de desaparecer em silêncio.
"""

from __future__ import annotations

import math
import time
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
            itens.append(item_de_resposta(pub, resposta))

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


def item_de_resposta(pub: Publicacao, resposta: dict[str, Any]) -> Item:
    """Junta o que o `radar` coletou com o juízo que o LLM emitiu.

    Os fatos vêm sempre da publicação; do modelo só vem a leitura dela - com uma
    exceção determinística: o piso de relevância do IOF-MG, abaixo.
    """
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
        categoria=resposta["categoria"],
        relevancia=_relevancia(pub, resposta),
        resumo=resposta["resumo"],
        por_que_importa=resposta["por_que_importa"],
        valor_brl=resposta["valor_brl"],
        entes=tuple(resposta["entes"]),
        tags=tuple(resposta["tags"]),
    )


def _relevancia(pub: Publicacao, resposta: dict[str, Any]) -> int:
    """Piso de relevância para o que sai do Diário Oficial de Minas Gerais.

    Todo ato do IOF-MG é mineiro por definição, e Minas é o mercado do boletim.
    Deixar isso a cargo do prompt não funcionou: na semana de 31/08 o modelo deu
    3 a habilitações na Bahia e 2 a deliberações CIB-SUS/MG que alocam recurso a
    município mineiro. Vale só para A e B - um ato de rotina do estado não vira
    prioridade só por ser de Minas.
    """
    relevancia = resposta["relevancia"]
    if pub.fonte == "iofmg" and resposta["categoria"] in ("A", "B"):
        return max(relevancia, _RELEVANCIA_MAXIMA)
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
