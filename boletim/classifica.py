"""Classificação das publicações mantidas, lote a lote, com o LLM.

Três defesas contra o modelo, na ordem em que custam: validação do schema,
reconciliação por id e bisseção do lote. A quarta e última é o fallback D, que
nunca deixa uma publicação sumir da edição por causa de uma resposta ruim -
ela aparece como "outro ato", marcada, em vez de desaparecer em silêncio.
"""

from __future__ import annotations

from typing import Any, Sequence

from boletim.config import ConfigBoletim
from boletim.edicao import Item
from boletim.esquemas import LOTE_SCHEMA, validar
from boletim.llm import LLM, LLMIndisponivel
from boletim.prompts import SISTEMA_CLASSIFICACAO, montar_lote
from radar.core.log import configurar_log
from radar.core.modelos import Publicacao

_LIMITE_RESUMO_FALLBACK = 200


def classificar(
    mantidas: Sequence[Publicacao], llm: LLM, cfg: ConfigBoletim
) -> tuple[list[Item], list[str]]:
    """Devolve um `Item` por publicação mantida, na mesma ordem, mais avisos.

    Sempre um item por publicação: quem lê o boletim precisa saber que o ato
    existiu, mesmo quando o modelo não conseguiu opinar sobre ele.
    """
    logger = configurar_log()
    respostas: dict[str, dict[str, Any]] = {}
    avisos: list[str] = []
    estado = _Estado()

    for indice in range(0, len(mantidas), cfg.lote):
        lote = list(mantidas[indice : indice + cfg.lote])
        rotulo = f"lote-{indice // cfg.lote}"
        _resolver(lote, llm, cfg, rotulo, respostas, avisos, estado)

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


class _Estado:
    """O que o LLM já entregou nesta execução, e se ele ainda está de pé.

    Importa para o exit code: cair antes do primeiro lote é falha total e o CLI
    sai 2; cair depois é edição parcial, que ainda vale a pena publicar.
    """

    def __init__(self) -> None:
        self.algum_sucesso = False
        self.desistiu = False


def _resolver(
    pubs: list[Publicacao],
    llm: LLM,
    cfg: ConfigBoletim,
    rotulo: str,
    respostas: dict[str, dict[str, Any]],
    avisos: list[str],
    estado: _Estado,
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
        try:
            bruto = llm.completar_json(
                SISTEMA_CLASSIFICACAO,
                montar_lote(pubs, cfg),
                LOTE_SCHEMA,
                rotulo=rotulo,
            )
        except LLMIndisponivel:
            if not estado.algum_sucesso:
                # Nada classificado ainda: não é uma resposta ruim, é o modelo
                # fora do ar. Propagar deixa o CLI sair 2 em vez de publicar
                # uma edição inteira de fallback D.
                raise
            estado.desistiu = True
            avisos.append(f"{rotulo}: LLM indisponível, o restante do dia fica sem classificação")
            logger.warning("%s: LLM indisponível depois de %d respostas", rotulo, len(respostas))
            return

        erros = validar(bruto, LOTE_SCHEMA)
        if erros:
            avisos.append(
                f"{rotulo}: resposta inválida na tentativa {tentativa}: {erros[0]}"
            )
            logger.warning("%s: resposta inválida (%d erros)", rotulo, len(erros))
            continue

        for item in bruto["itens"]:
            if item["id"] in esperados:
                respostas[item["id"]] = item
                estado.algum_sucesso = True
            else:
                avisos.append(f"{rotulo}: id fora do lote ignorado: {item['id']}")
        if esperados <= respostas.keys():
            return

    faltantes = [p for p in pubs if p.id not in respostas]
    if len(faltantes) <= 1:
        return
    meio = len(faltantes) // 2
    _resolver(faltantes[:meio], llm, cfg, rotulo, respostas, avisos, estado)
    _resolver(faltantes[meio:], llm, cfg, rotulo, respostas, avisos, estado)


def item_de_resposta(pub: Publicacao, resposta: dict[str, Any]) -> Item:
    """Junta o que o `radar` coletou com o juízo que o LLM emitiu.

    Os fatos vêm sempre da publicação; do modelo só vem a leitura dela.
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
        relevancia=resposta["relevancia"],
        resumo=resposta["resumo"],
        por_que_importa=resposta["por_que_importa"],
        valor_brl=resposta["valor_brl"],
        entes=tuple(resposta["entes"]),
        tags=tuple(resposta["tags"]),
    )


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
