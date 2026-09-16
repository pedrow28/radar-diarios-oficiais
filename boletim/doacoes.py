"""Doações do Ministério da Saúde a entes públicos, lidas sem modelo.

Em 16/09/2026 o DOU trouxe 54 extratos de termo de doação da Secretaria de
Atenção Especializada: micro-ônibus, vans, viaturas do SAMU 192 e ambulâncias
para prefeituras nominais, R$ 27,8 milhões no total. O prefiltro os descartava
todos como "extrato de doação", e a edição saiu com zero relevantes. É alocação
nominal de recurso a município: categoria A.

O extrato tem formato fixo ("Doador: ... Donatário: ..., CNPJ ... Doação de NN
veículo(s) para utilização como ..., no valor de R$ ..."), e por isso uma regex
é mais confiável que o modelo e poupa cinco chamadas num dia assim. As doações
viram um item só por edição: 54 itens iguais afogariam o resto da seção A.

O que a regex não consegue ler não some: `agrupar` devolve um aviso por
publicação e o CLI a manda para o modelo como qualquer outra.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from boletim.edicao import Item
from radar.core.modelos import Publicacao

TAG_DOACOES = "regra:doacoes-agrupadas"
UF_MINAS = "MG"

_DONATARIO = re.compile(r"Donat[áa]rio:\s*(.+?),\s*CNPJ", re.IGNORECASE)
_UF = re.compile(r"/([A-Z]{2})$")
_PREFIXOS = re.compile(
    r"^(?:Prefeitura Municipal de|Munic[íi]pio de|Fundo Municipal de Sa[úu]de de"
    r"|Secretaria Municipal de Sa[úu]de de)\s+",
    re.IGNORECASE,
)
_QUANTIDADE = re.compile(r"Doa[çc][ãa]o de (\d+)\s+(\w+)", re.IGNORECASE)
_OBJETO = re.compile(r"para utiliza[çc][ãa]o como (.+?)(?:, com encargos|, no valor|\.)")
_VALOR = re.compile(r"R\$ ?([\d.]+),(\d{2})")

_MAX_MINEIROS = 5
MAX_RESUMO = 260
POR_QUE_IMPORTA_MG = (
    "Municípios mineiros contemplados confirmam que o programa está ativo no "
    "estado; os demais podem pleitear os mesmos veículos."
)


@dataclass(frozen=True)
class Doacao:
    id: str
    municipio: str | None
    uf: str | None
    donatario: str
    quantidade: int | None
    objeto: str
    valor_brl: float | None
    url: str


def extrair(pub: Publicacao) -> Doacao | None:
    """Os campos do extrato, ou `None` quando falta donatário ou valor.

    Sem donatário não há a quem atribuir o recurso, e sem valor o item agrupado
    somaria um total errado: nos dois casos a publicação vai para o modelo.
    """
    texto = " ".join(pub.texto.split())
    donatario = _DONATARIO.search(texto)
    valor = _VALOR.search(texto)
    if not donatario or not valor:
        return None
    nome = donatario.group(1).strip()
    uf = _UF.search(nome)
    municipio: str | None = None
    sem_prefixo = _PREFIXOS.sub("", nome)
    if uf or sem_prefixo != nome:
        municipio = _UF.sub("", sem_prefixo).strip() or None
    quantidade = _QUANTIDADE.search(texto)
    objeto = _OBJETO.search(texto)
    return Doacao(
        id=pub.id,
        municipio=municipio,
        uf=uf.group(1) if uf else None,
        donatario=nome,
        quantidade=int(quantidade.group(1)) if quantidade else None,
        objeto=objeto.group(1).strip() if objeto else "",
        valor_brl=float(f"{valor.group(1).replace('.', '')}.{valor.group(2)}"),
        url=pub.url,
    )


def agrupar(
    pubs: Sequence[Publicacao], data: date, marcas_mg: Sequence[str]
) -> tuple[Item | None, list[str]]:
    """Um `Item` de categoria A com todas as doações extraídas, mais avisos.

    O item não passa por `item_de_resposta`: as regras R1 a R5 foram escritas
    para corrigir o julgamento do modelo, e aqui não há julgamento a corrigir.
    A relevância segue a mesma régua (3 com Minas, 2 sem).
    """
    avisos: list[str] = []
    pares: list[tuple[Publicacao, Doacao]] = []
    for pub in pubs:
        doacao = extrair(pub)
        if doacao is None:
            avisos.append(
                f"doação do Ministério da Saúde não extraída ({pub.id}); "
                "segue para o modelo"
            )
        else:
            pares.append((pub, doacao))
    if not pares:
        return None, avisos

    doacoes = [d for _, d in pares]
    mineiras = [d for d in doacoes if _em_minas(d, marcas_mg)]
    entes = _entes(doacoes, mineiras)
    total = round(sum(d.valor_brl or 0.0 for d in doacoes), 2)
    primeira = pares[0][0]
    url = mineiras[0].url if mineiras else doacoes[0].url
    unidades = Counter(p.unidade for p, _ in pares if p.unidade)

    return (
        Item(
            id=hashlib.sha256(f"doacoes|{data.isoformat()}".encode()).hexdigest()[:16],
            fonte=primeira.fonte,
            orgao="Ministério da Saúde",
            unidade=unidades.most_common(1)[0][0] if unidades else None,
            tipo="Extrato de Termo de Doação",
            numero=None,
            data_publicacao=primeira.data_publicacao,
            secao=primeira.secao,
            pagina=primeira.pagina,
            edicao=primeira.edicao,
            titulo=_titulo(pares),
            url=url,
            categoria="A",
            relevancia=3 if mineiras else 2,
            resumo=_resumo(pares, total, mineiras),
            por_que_importa=POR_QUE_IMPORTA_MG if mineiras else None,
            valor_brl=total,
            entes=entes,
            tags=(TAG_DOACOES,),
            fallback=False,
        ),
        avisos,
    )


# ── partes do item ──────────────────────────────────────────────────────
def _ente(doacao: Doacao) -> str:
    return doacao.municipio or doacao.donatario


def _chave_alfabetica(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return sem_acento.casefold()


def _em_minas(doacao: Doacao, marcas_mg: Sequence[str]) -> bool:
    """UF `MG` no donatário, ou marca de Minas no nome de um ente sem UF.

    A sigla solta "MG" fica de fora da segunda checagem: sem a barra ela casaria
    dentro de qualquer nome, e o donatário com UF já foi decidido pela primeira.
    """
    if doacao.uf is not None:
        return doacao.uf == UF_MINAS
    nome = doacao.donatario.casefold()
    return any(
        marca.casefold() in nome for marca in marcas_mg if marca.strip() != UF_MINAS
    )


def _entes(doacoes: list[Doacao], mineiras: list[Doacao]) -> tuple[str, ...]:
    """Minas primeiro, depois ordem alfabética, sem repetir o mesmo ente."""
    ids_mineiros = {d.id for d in mineiras}
    ordenadas = sorted(
        doacoes, key=lambda d: (d.id not in ids_mineiros, _chave_alfabetica(_ente(d)))
    )
    vistos: list[str] = []
    for doacao in ordenadas:
        if _ente(doacao) not in vistos:
            vistos.append(_ente(doacao))
    return tuple(vistos)


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _contagem_entes(doacoes: list[Doacao]) -> tuple[str, int]:
    """`"6 municípios e 1 estado"` e o total de entes distintos."""
    municipios = {d.municipio for d in doacoes if d.municipio}
    outros = {d.donatario for d in doacoes if not d.municipio}
    estados = {n for n in outros if "estad" in n.casefold()}
    demais = outros - estados
    partes = []
    if municipios:
        partes.append(_plural(len(municipios), "município", "municípios"))
    if estados:
        partes.append(_plural(len(estados), "estado", "estados"))
    if demais:
        partes.append(_plural(len(demais), "outro ente", "outros entes"))
    return _juntar(partes), len(municipios) + len(outros)


def _juntar(partes: list[str]) -> str:
    if len(partes) <= 1:
        return "".join(partes)
    return f"{', '.join(partes[:-1])} e {partes[-1]}"


def _veiculos(pares: list[tuple[Publicacao, Doacao]]) -> tuple[int, bool]:
    """Total de bens doados e se todos são veículos.

    Doação sem quantidade legível conta um: é pelo menos um bem, e sem isso a
    soma dos tipos não bateria com o total.
    """
    total = sum(d.quantidade or 1 for _, d in pares)
    todos_veiculos = all(
        (m := _QUANTIDADE.search(" ".join(p.texto.split())))
        and m.group(2).casefold().startswith("veículo")
        for p, _ in pares
    )
    return total, todos_veiculos


def _tipo(pub: Publicacao, doacao: Doacao) -> tuple[str, str]:
    """Nome curto do bem, no singular e no plural."""
    objeto = doacao.objeto.casefold()
    if "micro-ônibus" in objeto:
        return "micro-ônibus de transporte sanitário", "micro-ônibus de transporte sanitário"
    if re.search(r"\bvan\b", objeto):
        return "van de transporte sanitário", "vans de transporte sanitário"
    if "ambulância" in objeto:
        return "ambulância", "ambulâncias"
    if "frota" in objeto and "SAMU" in pub.texto:
        return "viatura do SAMU 192", "viaturas do SAMU 192"
    return "outro veículo", "outros veículos"


def _titulo(pares: list[tuple[Publicacao, Doacao]]) -> str:
    """Formato de sentença e só siglas da lista de `titulo_ato`.

    O filtro `titulo_ato` desce para minúscula toda palavra fora de `SIGLAS`: um
    "Ministério da Saúde" no título sairia "ministério da saúde" no site e no
    e-mail. Por isso o título fala em SUS e deixa o órgão para a linha de meta.
    """
    doacoes = [d for _, d in pares]
    entes, _ = _contagem_entes(doacoes)
    total, todos_veiculos = _veiculos(pares)
    bens = _plural(total, "veículo", "veículos") if todos_veiculos else _plural(
        total, "bem", "bens"
    )
    return f"Doação de {bens} do SUS a {entes}"


def _milhoes(valor: float) -> str:
    if valor >= 1_000_000:
        numero = f"{valor / 1_000_000:.1f}".replace(".", ",")
        return f"R$ {numero} {'milhão' if valor < 2_000_000 else 'milhões'}"
    return f"R$ {f'{valor / 1_000:.1f}'.replace('.', ',')} mil"


def _resumo(
    pares: list[tuple[Publicacao, Doacao]], total: float, mineiras: list[Doacao]
) -> str:
    doacoes = [d for _, d in pares]
    entes, n_entes = _contagem_entes(doacoes)
    quantidade, todos_veiculos = _veiculos(pares)
    bens = _plural(quantidade, "veículo", "veículos") if todos_veiculos else _plural(
        quantidade, "bem", "bens"
    )

    por_tipo: Counter[tuple[str, str]] = Counter()
    for pub, doacao in pares:  # Counter preserva a ordem de aparição no empate.
        por_tipo[_tipo(pub, doacao)] += doacao.quantidade or 1
    tipos = _juntar(
        [_plural(n, singular, plural) for (singular, plural), n in por_tipo.most_common(3)]
    )

    verbo = "recebe" if n_entes == 1 else "recebem"
    frase = (
        f"{entes} {verbo} {bens} do Ministério da Saúde: {tipos}, "
        f"no total de {_milhoes(total)}."
    )
    if mineiras:
        nomes = list(dict.fromkeys(_ente(d) for d in mineiras))
        nomes.sort(key=_chave_alfabetica)
        if len(nomes) > _MAX_MINEIROS:
            lista = f"{', '.join(nomes[:_MAX_MINEIROS])} e mais {len(nomes) - _MAX_MINEIROS}"
        else:
            lista = _juntar(nomes)
        frase += f" Em Minas: {lista}."
    if len(frase) > MAX_RESUMO:
        # O órgão já está na linha de meta: é o primeiro trecho a sair.
        frase = frase.replace(" do Ministério da Saúde:", ":", 1)
    return frase
