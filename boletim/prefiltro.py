"""Triagem determinística antes do LLM: barata, auditável e reversível.

Mandar o diário inteiro para o modelo custa caro e, pior, dilui o julgamento em
centenas de nomeações e extratos de contrato. Aqui só entram regras que um
humano consegue conferir lendo o regex — nada de "achismo" antes da hora. O que
o prefiltro descarta fica registrado com a regra que o descartou, para que uma
regra ruim possa ser encontrada e corrigida.

A retenção forte vence o descarte de propósito: uma portaria que nomeia o
gestor E habilita leitos é, para quem capta recurso, uma habilitação. Mas ela
só olha o título e a ementa. A rodada real de 31/08 a 04/09/2026 mostrou que,
olhando o corpo, 44% do que o prefiltro mandava ao modelo era ruído que ele
mesmo já tinha marcado: preâmbulo de Resolução-RE citando a RDC que fundamenta
o ato, "edital" no meio de um extrato de contrato, `R$ 0,00` de contrapartida.
O corpo continua contando para a *força* — que decide quem fica quando o dia
estoura o teto — mas não resgata mais nada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from boletim.config import ConfigBoletim
from radar.core.modelos import Publicacao

def _compilar(regras: tuple[str, ...]) -> re.Pattern[str]:
    """Uma alternação só, para a pergunta "casou alguma?"."""
    return re.compile("|".join(regras), re.IGNORECASE)


def _uma_a_uma(regras: tuple[str, ...]) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Cada regra separada, para a pergunta "quantas casaram?".

    É por isso que as regras vivem em tuplas e não numa string só: a força de
    uma publicação é o nº de *regras* distintas que casaram, e contá-las pelo
    trecho casado confundiria "altera o critério" com "altera o prazo".
    """
    return tuple((r, re.compile(r, re.IGNORECASE)) for r in regras)


# Ruído de diário oficial: ato de pessoal, contrato, doação e aviso de licitação.
_REGRAS_DESCARTE = (
    r"nomea",
    r"exonera",
    r"designa",
    r"dispensa (de )?(servidor|função)",
    r"férias",
    r"diária",
    r"boletim de serviço",
    r"ata de registro de preços",
    r"aviso de licitação",
    r"extrato de (contrato|termo aditivo|inexigibilidade|dispensa|doação"
    r"|apostilamento|comodato|rescisão|cessão|cooperação)",
    r"aviso de (homologação|suspensão|revogação|dispensa|reabertura|adiamento"
    r"|retificação)",
    r"retificação",
    r"termo de (apostilamento|doação)",
    r"resultado de julgamento",
    r"resolução-re\b",
    r"autorização de funcionamento",
    r"cancelamento de registro",
    r"torna sem efeito",
    r"concede férias",
    r"portaria de pessoal",
    r"progressão funcional",
    r"licença (prêmio|capacitação)",
    r"aposentadoria",
    r"pensão",
)
_DESCARTE = _compilar(_REGRAS_DESCARTE)

# Vocabulário de dinheiro e de regra: o que o gestor que capta recurso procura.
# Avaliado só sobre tipo + título + ementa — ver o docstring do módulo.
_REGRAS_FORTE = (
    r"habilita",
    r"credencia",
    r"desabilita",
    r"teto (mac|financeiro)",
    r"limite financeiro",
    r"incremento",
    r"custeio",
    r"investimento",
    r"emenda parlamentar",
    r"fundo a fundo",
    r"fundo nacional de saúde",
    r"repasse",
    r"transfer(e|ência) de recursos",
    r"r\$\s?\d",
    r"cib[- ]sus",
    r"deliberação",
    r"programação (orçamentária|assistencial)",
    r"crédito (suplementar|especial|extraordinário)",
    r"\bloa\b",
    r"\bldo\b",
    r"lei orçamentária",
    r"altera .{0,40}(critério|piso|prazo)",
    # Muda a regra de faturamento de quem fatura SUS: a Portaria SAES/MS 4.795
    # de 26/08/2026 saía daqui com força zero e foi cortada pelo teto.
    r"altera .{0,40}(procedimento|tabela|atributo|requisito)",
    r"tabela de procedimentos",
    r"sigtap",
    r"órteses",
    r"próteses",
    r"\bopm\b",
    r"inclui procedimento",
    r"incorpora(ção)? .{0,40}(sus|procedimento|tecnologia)",
    r"chamamento público",
    r"edital",
)
_FORTE = _compilar(_REGRAS_FORTE)
_FORTE_UMA_A_UMA = _uma_a_uma(_REGRAS_FORTE)

# O corpo não resgata nada; só soma força, e só quando traz dinheiro de verdade
# ou alocação nominal. `r\$\s?\d` casava com o `R$ 0,00` de contrapartida de
# qualquer extrato — daí a exigência do separador de milhar.
_REGRAS_FORTE_CORPO = (
    r"r\$\s?\d{1,3}(?:\.\d{3})+,\d{2}",
    r"habilita",
    r"credencia",
    r"teto (mac|financeiro)",
    r"limite financeiro",
    r"incremento",
    r"emenda parlamentar",
    r"fundo a fundo",
    r"transfer(e|ência) de recursos",
    r"repasse",
)
_FORTE_CORPO_UMA_A_UMA = _uma_a_uma(_REGRAS_FORTE_CORPO)

_VALOR = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})")

_MAIUSCULA = "A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ"
# Inicial maiúscula seguida de minúscula: "Dias" entra no nome, "ANEXO" não.
# O texto do IOF-MG vem de PDF e emenda o cabeçalho do anexo no nome do ente.
_PALAVRA = rf"[{_MAIUSCULA}](?![{_MAIUSCULA}])[^\W\d_]*"
_LIGACAO = r"(?:de|do|da|dos|das)"
_MARCADOR = r"Munic[íi]pios? de|Hospital|Santa Casa|Funda[çc][ãa]o|Instituto"
# O marcador entra no nome: "César Leite" sozinho é nome de pessoa, "Hospital
# César Leite" é a entidade que o gestor reconhece. O nome corre por palavras
# capitalizadas e conectivos ("Santa Casa de Misericórdia de Belo Horizonte") e
# para na primeira pontuação ou palavra comum.
_ENTE = re.compile(rf"(?:{_MARCADOR})(?:\s+(?:{_PALAVRA}|{_LIGACAO}))+")
_TERMINA_EM_LIGACAO = re.compile(rf"\s+{_LIGACAO}$", re.IGNORECASE)
# O PDF quebra o nome no meio ("Montes \nClaros"); a linha em branco, não: ali
# começa outro bloco, e o nome não deve atravessá-la.
_PARAGRAFO = re.compile(r"\n[^\S\n]*\n")
_ESPACO = re.compile(r"\s+")

MAX_ENTES = 10
_CHARS_EMENTA = 400
_CHARS_TEXTO_FORTE = 2000


@dataclass(frozen=True)
class Descarte:
    id: str
    regra: str


@dataclass(frozen=True)
class Triagem:
    mantidas: tuple[Publicacao, ...]
    descartadas: tuple[Descarte, ...]
    avisos: tuple[str, ...] = ()


def valores_brl(texto: str) -> tuple[float, ...]:
    """Valores em reais citados no texto, na ordem em que aparecem.

    Só com a cifra: um "1.234,00" solto tanto pode ser dinheiro quanto
    quantidade de leitos, e inventar valor é o pior erro possível aqui.
    """
    return tuple(
        float(f"{inteiro.replace('.', '')}.{centavos}")
        for inteiro, centavos in _VALOR.findall(texto)
    )


def entes_candidatos(texto: str) -> tuple[str, ...]:
    """Municípios, hospitais e fundações nominais citados no texto.

    Candidatos, não verdades: servem de pista para o LLM e para o prefiltro,
    e são deduplicados preservando a ordem de aparição.

    O espaço em branco é normalizado antes de casar, porque o texto do IOF-MG
    vem de PDF: sem isso o candidato sai com a quebra de linha dentro
    ("Hospital Santa Casa de Montes \\nClaros") e nem o e-mail nem a conferência
    automática de "o ente consta no texto?" o reconhecem.
    """
    texto = _ESPACO.sub(" ", _PARAGRAFO.sub(". ", texto))
    encontrados: list[str] = []
    for bruto in _ENTE.findall(texto):
        nome = _TERMINA_EM_LIGACAO.sub("", bruto).strip()
        if nome not in encontrados:
            encontrados.append(nome)
        if len(encontrados) == MAX_ENTES:
            break
    return tuple(encontrados)


def triar(pubs: Sequence[Publicacao], cfg: ConfigBoletim) -> Triagem:
    """Separa o que vale a pena classificar do ruído previsível do diário."""
    mantidas: list[Publicacao] = []
    descartadas: list[Descarte] = []

    for pub in pubs:
        if pub.fonte in ("dou", "inlabs") and pub.secao == "2":
            descartadas.append(Descarte(pub.id, "secao_2"))
            continue
        alvo = _alvo(pub)
        # O descarte roda primeiro, e só o título e a ementa podem resgatá-lo.
        if _DESCARTE.search(alvo) and not _FORTE.search(alvo):
            descartadas.append(Descarte(pub.id, "descarte"))
            continue
        mantidas.append(pub)

    avisos: list[str] = []
    if len(mantidas) > cfg.max_itens_dia:
        mantidas, cortadas = _aplicar_teto(mantidas, cfg.max_itens_dia)
        descartadas.extend(Descarte(p.id, "teto") for p in cortadas)
        avisos.append(
            f"{len(cortadas)} itens além do teto de {cfg.max_itens_dia} "
            "não foram classificados"
        )

    return Triagem(tuple(mantidas), tuple(descartadas), tuple(avisos))


def _aplicar_teto(
    mantidas: list[Publicacao], maximo: int
) -> tuple[list[Publicacao], list[Publicacao]]:
    """Corta o dia até o teto sem nunca tocar no IOF-MG.

    São ~30 publicações por dia contra centenas do DOU, e são elas que trazem
    as deliberações CIB-SUS/MG de maior valor (até R$ 168,9 mi na semana de
    31/08). Deixá-las disputar vaga com extrato de doação federal é entregar a
    edição do dia ao acaso da ordenação.
    """
    pontos = {p.id: (forca(p), i) for i, p in enumerate(mantidas)}
    protegidas = [p for p in mantidas if p.fonte == "iofmg"]
    demais = [p for p in mantidas if p.fonte != "iofmg"]
    vagas = max(maximo - len(protegidas), 0)
    # `sorted` é estável: entre itens de força igual vale a ordem do diário.
    por_forca = sorted(demais, key=lambda p: -pontos[p.id][0])
    sobreviventes = protegidas + por_forca[:vagas]
    sobreviventes.sort(
        key=lambda p: (-pontos[p.id][0], p.fonte != "iofmg", pontos[p.id][1])
    )
    return sobreviventes, por_forca[vagas:]


def _alvo(pub: Publicacao) -> str:
    return " ".join([pub.tipo or "", pub.titulo, (pub.ementa or "")[:_CHARS_EMENTA]])


def forca(pub: Publicacao) -> int:
    """Quantas regras fortes distintas a publicação traz.

    Regras, e não ocorrências nem substrings: uma portaria que repete "custeio"
    seis vezes não é mais relevante que uma que fala de teto MAC, repasse e
    habilitação, e "altera o critério" mais "altera o prazo" são a mesma regra.
    A mesma regra casando no título e no corpo também conta uma vez só.
    """
    alvo = _alvo(pub)
    corpo = pub.texto[:_CHARS_TEXTO_FORTE]
    casadas = {regra for regra, rx in _FORTE_UMA_A_UMA if rx.search(alvo)}
    casadas |= {regra for regra, rx in _FORTE_CORPO_UMA_A_UMA if rx.search(corpo)}
    return len(casadas)
