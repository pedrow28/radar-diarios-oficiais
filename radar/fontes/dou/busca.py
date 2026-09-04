"""Listagem do DOU a partir do JSON embutido na página de busca.

A busca do in.gov.br serve os resultados dentro de um <script
type="application/json">, o que dispensa navegador: basta HTTP e json.loads.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import quote_plus, urlencode

from radar.core.erros import ExtracaoParcial

BASE_BUSCA = "https://www.in.gov.br/consulta/-/buscar/dou"
BASE_PUBLICACAO = "https://www.in.gov.br/web/dou/-/"
ID_BLOCO_JSON = "_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"

# Verificado contra o site: o portal serve UTF-8 e o header diz a verdade.
ENCODING_BUSCA = "utf-8"
ENCODING_PUBLICACAO = "utf-8"

_PADRAO_BLOCO = re.compile(
    rf'<script id="{re.escape(ID_BLOCO_JSON)}" type="application/json">(.*?)</script>',
    re.DOTALL,
)
_PADRAO_TOTAL = re.compile(r"(\d+)\s+resultados?")
# Teto duro de páginas para quando o total não pôde ser lido: sem ele, a única
# saída do laço seria a página vazia ou repetida, e um portal que sempre
# devolvesse itens novos manteria a coleta rodando para sempre.
_TETO_SEM_TOTAL = 40


def decodificar_busca(bruto: bytes) -> str:
    """Decodifica a página de busca.

    UTF-8 é auto-validante: uma sequência inválida levanta em vez de produzir
    lixo silencioso. Por isso tentamos UTF-8 primeiro e só caímos em ISO-8859-1
    se os bytes não forem UTF-8 válido — o que só aconteceria se o portal
    mudasse. Latin-1 nunca falha, então jamais deve vir primeiro.
    """
    try:
        return bruto.decode(ENCODING_BUSCA)
    except UnicodeDecodeError:
        return bruto.decode("iso-8859-1")


def extrair_jsonarray(html: str) -> list[dict]:
    """Devolve os itens de resultado embutidos na página."""
    achado = _PADRAO_BLOCO.search(html)
    if not achado:
        raise ExtracaoParcial(
            "Bloco JSON de resultados não encontrado na busca do DOU. "
            "A estrutura da página pode ter mudado."
        )
    try:
        dados = json.loads(achado.group(1).strip())
    except json.JSONDecodeError as exc:
        raise ExtracaoParcial(f"Bloco JSON da busca do DOU é inválido: {exc}") from exc
    return dados.get("jsonArray", [])


def total_de_resultados(html: str) -> int:
    """Total informado pela própria busca, usado para saber quando parar."""
    achado = _PADRAO_TOTAL.search(html)
    return int(achado.group(1)) if achado else 0


@dataclass(frozen=True)
class Cursor:
    """Posição da paginação: o último item da página já lida.

    A busca do DOU pagina por cursor (`search_after`), não por offset. Mandar
    `currentPage=2` na URL não avança nada — o portal só ecoa o valor.
    """

    score: Any
    id: Any
    display_date: Any


def cursor_do_ultimo(itens: list[dict]) -> Cursor | None:
    if not itens:
        return None
    ultimo = itens[-1]
    return Cursor(
        score=ultimo.get("score"),
        id=ultimo.get("classPK"),
        display_date=ultimo.get("displayDateSortable"),
    )


def montar_url_busca(
    orgao: str,
    data: date,
    delta: int,
    pagina: int = 1,
    cursor: Cursor | None = None,
) -> str:
    """URL da busca para uma data e página.

    A data vai como `exactDate=personalizado` com `publishFrom`/`publishTo` em
    DD-MM-AAAA. A forma `exactDate=dia` + `dateDay/dateMonth/dateYear`, usada
    pelos scripts antigos, ignora a data pedida e devolve a edição corrente —
    sem erro, o que é pior.
    """
    data_br = data.strftime("%d-%m-%Y")
    parametros = {
        "q": "*",
        "s": "todos",
        "orgPrin": orgao,
        "exactDate": "personalizado",
        "publishFrom": data_br,
        "publishTo": data_br,
        "sortType": "0",
        "delta": delta,
    }
    if pagina > 1 and cursor is not None:
        parametros.update(
            {
                "currentPage": pagina - 1,
                "newPage": pagina,
                "score": cursor.score,
                "id": cursor.id,
                "displayDate": cursor.display_date,
            }
        )
    return f"{BASE_BUSCA}?{urlencode(parametros, quote_via=quote_plus)}"


def url_publicacao(url_title: str) -> str:
    return f"{BASE_PUBLICACAO}{url_title}"


def percorrer_paginas(buscar_pagina, delta: int) -> tuple[list[dict], list[str]]:
    """Percorre a paginação da busca acumulando itens únicos.

    `buscar_pagina(numero, cursor) -> html` é injetado para manter esta função
    testável sem rede. O cursor vem do último item da página anterior; sem ele a
    busca do DOU devolve sempre a primeira página.

    Três saídas explícitas, nunca um `except` pelado: total atingido, página
    vazia, ou página cujo conjunto de itens repete o da anterior — que é como a
    paginação trava. Nesse último caso devolve aviso em vez de declarar sucesso.
    """
    from radar.core.log import configurar_log

    logger = configurar_log()
    unicos: dict[str, dict] = {}
    avisos: list[str] = []
    total = 0
    total_conhecido = True
    vistos_anteriores: set[str] | None = None
    cursor: Cursor | None = None
    pagina = 1
    teto = 1

    while pagina <= teto:
        html = buscar_pagina(pagina, cursor)
        # O `jsonArray` é extraído ANTES de qualquer decisão sobre o total: o
        # total sai de um texto da página ("118 resultados") e some se o layout
        # mudar, enquanto os itens continuam íntegros. Decidir pelo total antes
        # de olhar os itens transformava mudança de layout em `vazio` com exit 0
        # e nenhum aviso — a falha silenciosa que o contrato existe para impedir.
        itens = extrair_jsonarray(html)
        if pagina == 1:
            total = total_de_resultados(html)
            if total == 0 and not itens:
                return [], []  # dia sem publicação: vazio legítimo, sem aviso.
            if total == 0:
                total_conhecido = False
                avisos.append(
                    "O total não pôde ser lido da página; o layout da busca pode "
                    "ter mudado. Seguindo com os itens do jsonArray."
                )
                logger.warning(avisos[-1])
                # Sem total não há teto derivável; a paginação para por página
                # vazia ou repetida, com um limite duro contra laço infinito.
                teto = _TETO_SEM_TOTAL
            else:
                # Uma página de margem para o caso de o total oscilar durante a coleta.
                teto = -(-total // delta) + 1

        if not itens:
            break

        chaves = {i.get("urlTitle", "") for i in itens}
        if vistos_anteriores is not None and chaves == vistos_anteriores:
            avisos.append(
                f"Paginação travou: a página {pagina} repetiu os itens da anterior. "
                f"Coletados {len(unicos)} de {total}."
            )
            logger.warning(avisos[-1])
            break
        vistos_anteriores = chaves

        for item in itens:
            chave = item.get("urlTitle", "")
            if chave:
                unicos[chave] = item

        if total_conhecido and len(unicos) >= total:
            break
        cursor = cursor_do_ultimo(itens)
        pagina += 1

    if total and len(unicos) < total and not avisos:
        avisos.append(f"Coletadas {len(unicos)} de {total} publicações informadas pela busca.")
        logger.warning(avisos[-1])

    return list(unicos.values()), avisos
