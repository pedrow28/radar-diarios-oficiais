"""Uma `Edicao` completa montada das fixtures, para render, site e CLI.

Os três blocos precisam da mesma edição, e escrevê-la à mão em cada teste faria
o HTML ser conferido contra dados que o resto do pipeline nunca produziria.
Aqui ela nasce do caminho real: publicações normalizadas -> classificação do
`lote1.json` -> `montar_edicao` com o editorial do `editorial.json`.

A composição é escolhida, não sorteada: 2 itens em A (os dois com valor, um de
cada fonte), 1 em B, 1 em C e 2 em D, sendo um deles em fallback - é o pior
caso visual do e-mail, com todas as seções presentes e todas as variações de
linha de meta (seção do DOU, página do IOF-MG, valor, "por que importa").
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from boletim.carga import carregar
from boletim.classifica import item_de_resposta
from boletim.edicao import Edicao, Item, montar_edicao
from boletim.llm import LLMFalso

BASE = Path(__file__).parent
DATA = date(2026, 9, 3)
DATA_VAZIA = date(2026, 9, 6)
GERADO_EM = datetime(2026, 9, 3, 9, 30, tzinfo=timezone.utc)
FONTES = ["inlabs", "iofmg"]

# Selecionados pelo começo do título, que é estável; o id é um hash.
_CLASSIFICADOS = (
    "PORTARIA GM/MS Nº 3.412",                  # A, R$ 1.234.567,89, inlabs
    "DELIBERAÇÃO CIB-SUS/MG Nº 4.512",          # A, R$ 28.100.000,00, iofmg
    "PORTARIA SAPS/MS Nº 3.418",                # B, inlabs
    "EDITAL DE CHAMAMENTO PÚBLICO Nº 12/2026",  # C, inlabs
    "PORTARIA PRE Nº 218",                      # D, iofmg
)
_EM_FALLBACK = "RESOLUÇÃO DE DIRETORIA COLEGIADA - RDC Nº 942"
_LIMITE_RESUMO_FALLBACK = 200


def _resposta_do_lote() -> dict[str, dict]:
    bruto = json.loads((BASE / "llm" / "lote1.json").read_text(encoding="utf-8"))
    return {item["id"]: item for item in bruto["itens"]}


def _editorial() -> dict:
    return json.loads((BASE / "llm" / "editorial.json").read_text(encoding="utf-8"))


def _fallback(pub) -> Item:
    """O item que o LLM não classificou: entra em D, marcado, sem sumir."""
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


def edicao_exemplo() -> Edicao:
    """A edição de 03/09/2026, com uma fonte ok e uma fonte parcial."""
    carga = carregar(BASE, DATA, FONTES)
    por_titulo = {p.titulo: p for p in carga.publicacoes}
    respostas = _resposta_do_lote()

    def publicacao(prefixo: str):
        return next(p for t, p in por_titulo.items() if t.startswith(prefixo))

    itens: list[Item] = [
        item_de_resposta(publicacao(p), respostas[publicacao(p).id])
        for p in _CLASSIFICADOS
    ]
    itens.append(_fallback(publicacao(_EM_FALLBACK)))

    llm = LLMFalso({"editorial": _editorial()})
    return montar_edicao(itens, carga.fontes, carga.parcial, llm, DATA, GERADO_EM)
