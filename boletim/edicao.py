"""Modelos da edição do boletim e a montagem da edição do dia.

A edição é o produto final: título, "em 30 segundos", intro e os itens já
separados por seção. O texto de abertura é a única parte escrita pelo LLM, e
por isso é a única que passa por `validar_voz` antes de virar edição - o resto
são fatos que vieram do diário.

Quando o modelo erra a voz duas vezes, ou está fora do ar, a edição sai com
título e destaques determinísticos. Boletim atrasado não serve para quem
precisa do prazo de um edital.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Sequence

from boletim.esquemas import EDITORIAL_SCHEMA, validar
from boletim.llm import LLM, LLMIndisponivel
from boletim.prompts import SISTEMA_EDITORIAL, montar_editorial
from radar.core.log import configurar_log

Categoria = Literal["A", "B", "C", "D", "X"]

ROTULOS = {
    "A": "Captação de recursos",
    "B": "Mudança de regra",
    "C": "Editais e chamamentos",
    "D": "Outros atos",
}


@dataclass(frozen=True)
class Item:
    id: str
    fonte: str
    orgao: str
    unidade: str | None
    tipo: str | None
    numero: str | None
    data_publicacao: date
    secao: str | None
    pagina: int | None
    edicao: str | None
    titulo: str
    url: str
    categoria: Categoria
    relevancia: int
    resumo: str
    por_que_importa: str | None = None
    valor_brl: float | None = None
    entes: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    fallback: bool = False


@dataclass(frozen=True)
class FonteResumo:
    nome: str
    status: str
    edicao: str | None
    paginas: str | None
    avisos: tuple[str, ...] = ()


@dataclass(frozen=True)
class Edicao:
    data: date
    titulo: str
    em_30_segundos: tuple[str, ...]
    intro: str
    secoes: dict[str, tuple[Item, ...]]  # chaves "A","B","C","D"
    fontes: tuple[FonteResumo, ...]
    parcial: bool
    gerado_em: datetime

    def total_relevante(self) -> int:
        return sum(len(self.secoes.get(cat, ())) for cat in ("A", "B", "C"))


def item_para_dict(item: Item) -> dict[str, Any]:
    """Serializa um `Item` para `itens.json`: datas em ISO, tuplas em listas."""
    d = asdict(item)
    d["data_publicacao"] = item.data_publicacao.isoformat()
    d["entes"] = list(item.entes)
    d["tags"] = list(item.tags)
    return d


def item_de_dict(d: dict[str, Any]) -> Item:
    """Reconstrói um `Item` a partir do dict lido de `itens.json`."""
    campos = dict(d)
    campos["data_publicacao"] = date.fromisoformat(campos["data_publicacao"])
    campos["entes"] = tuple(campos.get("entes", ()))
    campos["tags"] = tuple(campos.get("tags", ()))
    return Item(**campos)


# ── montagem da edição ──────────────────────────────────────────────────
_TRAVESSAO = re.compile(r"[—–]")
_EMOJI = re.compile(r"[🌀-🫿☀-➿]")
_PROIBIDAS = re.compile(r"\b(dica|truque)\b", re.IGNORECASE)
_PONTUACAO = ".,;:!?()[]\"'"
_MAX_BULLETS_FALLBACK = 3

# Conectivos ficam fora da conta de proporção: "de" e "do" de um nome de
# instituição diluiriam qualquer título até ele passar.
_CONECTIVOS = frozenset(
    "de da do dos das e em para por com no na a o os as que ao à".split()
)
_MIN_CAPITALIZADAS_TITULO_CASE = 4
_FRACAO_TITULO_CASE = 0.6

# Limites de comprimento da abertura. Estavam só no prompt, e em v2 da semana
# saíram títulos de 128 e 98 caracteres: o modelo obedece ao número quando o
# número volta medido na correção.
#
# O teto da intro nasceu em 400 e nenhuma edição real chegou perto: o modelo
# entregou de 716 a 1102 caracteres nas sete edições da semana, e o limite
# reprovava 7 de 7. Limite que nunca é cumprido não é limite, é uma segunda
# chamada garantida por dia. 1100 é o maior valor real arredondado: a intro de
# duas frases cabe com folga, e a que dobrar de tamanho ainda cai.
MAX_TITULO = 90
MAX_BULLET = 140
MAX_INTRO = 1100

# Os três campos da abertura. Cada um é aprovado ou reprovado sozinho: uma
# intro comprida não pode custar o título que passou.
CAMPOS_ABERTURA = ("titulo", "em_30_segundos", "intro")
_ROTULO_CAMPO = {"titulo": "título", "em_30_segundos": "bullet", "intro": "intro"}

SEM_RELEVANTES = "Sem publicações relevantes nesta data"
INTRO_SEM_RELEVANTES = (
    "Nenhuma publicação de captação de recursos, mudança de regra ou edital nesta "
    "data. O radar segue lendo o Diário Oficial da União e o Diário Oficial de "
    "Minas Gerais no próximo dia útil."
)


def ordenar(itens: Sequence[Item]) -> dict[str, tuple[Item, ...]]:
    """Agrupa por seção na ordem em que o gestor lê. X fica de fora da edição.

    Em A o desempate é o valor: entre duas habilitações igualmente relevantes,
    quem lê quer ver primeiro a que move mais dinheiro.
    """
    por_categoria = {
        cat: [i for i in itens if i.categoria == cat] for cat in ROTULOS
    }
    return {
        "A": tuple(
            sorted(
                por_categoria["A"],
                key=lambda i: (-i.relevancia, -(i.valor_brl or 0.0)),
            )
        ),
        "B": tuple(sorted(por_categoria["B"], key=lambda i: -i.relevancia)),
        "C": tuple(sorted(por_categoria["C"], key=lambda i: -i.relevancia)),
        "D": tuple(sorted(por_categoria["D"], key=lambda i: i.titulo)),
    }


def validar_voz(texto: str) -> list[str]:
    """Erros de voz Thauma no texto. Lista vazia significa aprovado.

    Devolve todos de uma vez porque a lista vira a instrução de correção na
    segunda tentativa do modelo.
    """
    erros: list[str] = []
    if _TRAVESSAO.search(texto):
        erros.append("travessão encontrado; use hífen (-)")
    if _EMOJI.search(texto):
        erros.append("emoji encontrado; o boletim não usa emoji")
    if "?" in texto:
        erros.append("pergunta retórica; escreva em afirmativa")
    for achado in set(m.group(0).lower() for m in _PROIBIDAS.finditer(texto)):
        erros.append(f'palavra proibida: "{achado}"')
    if _tem_title_case(texto):
        erros.append(
            "Title Case: a frase inteira está capitalizada; escreva em formato de sentença"
        )
    return erros


def sem_travessao(texto: str) -> str:
    """Troca travessão e meia-risca por hífen, conforme a diretriz de marca.

    Vale para o texto do LLM e para o do diário: o em-dash entra por copiar e
    colar de PDF, e um único deles numa peça já quebra a voz.
    """
    return _TRAVESSAO.sub("-", texto)


def _tem_title_case(texto: str) -> bool:
    """Title Case da frase, não nome próprio dentro dela.

    A regra antiga reprovava 4 iniciais maiúsculas seguidas, e com isso
    "Programa Agora Tem Especialistas" - o nome de um programa federal que
    aparece em quase todo dia da semana - derrubava o título editorial. Na
    primeira semana real isso custou 3 dos 5 títulos.

    O que separa "Habilitações Do Programa Somam Cento E Oitenta Milhões" de
    "3 habilitações do Programa Agora Tem Especialistas somam R$ 180 milhões"
    é a proporção: no primeiro a frase inteira está capitalizada, no segundo o
    nome próprio é uma ilha de 4 palavras num texto de 7. Siglas, números e
    conectivos ficam fora da conta - "de" e "do" de um nome de instituição
    diluiriam qualquer título.
    """
    palavras: list[str] = []
    for bruto in texto.split():
        palavra = bruto.strip(_PONTUACAO)
        if not palavra or not palavra[0].isalpha():
            continue  # número, cifra, marcador
        if palavra.isupper():
            continue  # sigla: "MAC", "SES-MG", "CIB-SUS/MG"
        if palavra.lower() in _CONECTIVOS:
            continue
        palavras.append(palavra)

    capitalizadas = sum(1 for p in palavras if p[0].isupper())
    if capitalizadas < _MIN_CAPITALIZADAS_TITULO_CASE:
        return False
    return capitalizadas / len(palavras) >= _FRACAO_TITULO_CASE


def titulo_fallback(data: date, n: int) -> str:
    """Título sem LLM: factual, com número, e sempre aprovado na voz."""
    return f"Boletim de {data:%d/%m/%Y}: {n} publicações relevantes"


def montar_edicao(
    itens: Sequence[Item],
    fontes: Sequence[FonteResumo],
    parcial: bool,
    llm: LLM,
    data: date,
    agora: datetime,
) -> Edicao:
    """Monta a edição do dia, com ou sem o texto de abertura do LLM."""
    secoes = ordenar(itens)
    relevantes = [*secoes["A"], *secoes["B"], *secoes["C"]]
    if relevantes:
        titulo, em_30_segundos, intro = _abertura(relevantes, secoes, llm, data)
    else:
        titulo, em_30_segundos, intro = _abertura_sem_relevantes(secoes["D"], data)

    return Edicao(
        data=data,
        titulo=titulo,
        em_30_segundos=em_30_segundos,
        intro=intro,
        secoes=secoes,
        fontes=tuple(fontes),
        # Item em fallback também torna o dia parcial: a edição saiu, mas com
        # uma parte do julgamento faltando.
        parcial=parcial or any(i.fallback for i in itens),
        gerado_em=agora,
    )


def _abertura_sem_relevantes(
    outros: tuple[Item, ...], data: date
) -> tuple[str, tuple[str, ...], str]:
    """Abertura de um dia sem A, B nem C, escrita sem chamar o LLM.

    Não há o que resumir, e gastar uma chamada para escrever "não houve nada"
    é dinheiro fora.
    """
    destaques = tuple(i.titulo for i in outros[:_MAX_BULLETS_FALLBACK])
    return (
        titulo_fallback(data, 0),
        destaques or (SEM_RELEVANTES,),
        INTRO_SEM_RELEVANTES,
    )


def _abertura(
    relevantes: list[Item],
    secoes: dict[str, tuple[Item, ...]],
    llm: LLM,
    data: date,
) -> tuple[str, tuple[str, ...], str]:
    """Pede a abertura ao LLM, com uma segunda chance quando a voz reprova.

    A segunda chamada leva as correções junto: sem dizer o que estava errado,
    repetir o mesmo prompt tende a produzir o mesmo travessão.

    A aprovação é por campo. Antes ela era do bloco inteiro, e uma intro
    comprida levava junto um título bom: em 31/08 e 01/09 da semana real o
    título passava em tudo e caiu no fallback por causa da intro. O que valida
    fica guardado, e depois da segunda tentativa só o campo que continuou
    reprovado é trocado pelo determinístico.
    """
    logger = configurar_log()
    contagens = {cat: len(secoes[cat]) for cat in ROTULOS}
    base = montar_editorial(relevantes, contagens, data)
    prompt = base
    aprovados: dict[str, Any] = {}
    reprovados: dict[str, list[str]] = {}

    for _ in range(2):
        try:
            resposta = llm.completar_json(
                SISTEMA_EDITORIAL, prompt, EDITORIAL_SCHEMA, rotulo="editorial"
            )
        except LLMIndisponivel as exc:
            logger.warning("editorial: LLM indisponível (%s), abertura determinística", exc)
            break
        erros_schema = validar(resposta, EDITORIAL_SCHEMA)
        if erros_schema:
            # Fora do schema não há campo para aproveitar: pode faltar o campo.
            reprovados = {campo: list(erros_schema) for campo in CAMPOS_ABERTURA}
            prompt = f"{base}\n\nCorreções obrigatórias: {'; '.join(erros_schema)}"
            continue
        # Travessão é erro de digitação, não de julgamento: normalizar antes de
        # validar poupa uma chamada e não deixa o dia sem título quando o
        # modelo insiste no em-dash.
        resposta = _normalizado(resposta)
        reprovados = _erros_de_voz(resposta)
        if not reprovados:
            return (
                resposta["titulo"],
                tuple(resposta["em_30_segundos"]),
                resposta["intro"],
            )
        for campo in CAMPOS_ABERTURA:
            if campo not in reprovados:
                aprovados.setdefault(campo, resposta[campo])
        prompt = f"{base}\n\nCorreções obrigatórias: {'; '.join(_mensagens(reprovados))}"
    else:
        # O `for` terminou sem `break`: as duas tentativas caíram na
        # validação (schema ou voz), não no LLM fora do ar.
        logger.warning(
            "editorial: %s reprovado 2x (%s); fallback determinístico só nesse campo",
            ", ".join(c for c in CAMPOS_ABERTURA if c not in aprovados),
            "; ".join(_mensagens(reprovados)),
        )

    determinista = _abertura_determinista(relevantes, data)
    escolhidos = {campo: aprovados.get(campo, determinista[campo]) for campo in CAMPOS_ABERTURA}
    return (
        escolhidos["titulo"],
        tuple(escolhidos["em_30_segundos"]),
        escolhidos["intro"],
    )


def _abertura_determinista(relevantes: list[Item], data: date) -> dict[str, Any]:
    """A abertura sem modelo, campo a campo, para preencher só o que faltar."""
    return {
        "titulo": titulo_fallback(data, len(relevantes)),
        "em_30_segundos": [i.resumo for i in relevantes[:_MAX_BULLETS_FALLBACK]],
        "intro": (
            f"O radar encontrou {len(relevantes)} publicações relevantes nesta data. "
            "O texto de abertura não pôde ser gerado, e os destaques abaixo saem "
            "direto da classificação."
        ),
    }


def _mensagens(reprovados: dict[str, list[str]]) -> list[str]:
    """Achata os erros por campo na lista que vai na correção, sem repetição."""
    mensagens: list[str] = []
    for campo in CAMPOS_ABERTURA:
        for erro in reprovados.get(campo, ()):
            if erro not in mensagens:
                mensagens.append(erro)
    return mensagens


def _normalizado(editorial: dict[str, Any]) -> dict[str, Any]:
    """Aplica a normalização determinística de traço nos três campos."""
    return {
        "titulo": sem_travessao(editorial["titulo"]),
        "em_30_segundos": [sem_travessao(b) for b in editorial["em_30_segundos"]],
        "intro": sem_travessao(editorial["intro"]),
    }


def _erros_de_voz(editorial: dict[str, Any]) -> dict[str, list[str]]:
    """Voz e comprimento da abertura, com os erros separados por campo.

    O comprimento vivia só no prompt, e em v2 da semana saíram títulos de 128 e
    98 caracteres e bullets acima de 140. É a regra mais fácil de conferir sem o
    modelo, e o caminho da correção já existe: o número medido volta na segunda
    chamada, e se ela também falhar entra o fallback determinístico - agora só
    no campo que errou, e não na abertura inteira.

    Devolve apenas os campos reprovados; dicionário vazio é abertura aprovada.
    """
    textos = {
        "titulo": [editorial["titulo"]],
        "em_30_segundos": list(editorial["em_30_segundos"]),
        "intro": [editorial["intro"]],
    }
    maximos = {"titulo": MAX_TITULO, "em_30_segundos": MAX_BULLET, "intro": MAX_INTRO}

    reprovados: dict[str, list[str]] = {}
    for campo in CAMPOS_ABERTURA:
        rotulo = _ROTULO_CAMPO[campo]
        erros: list[str] = []
        for texto in textos[campo]:
            for erro in validar_voz(texto):
                mensagem = f"{rotulo}: {erro}"
                if mensagem not in erros:
                    erros.append(mensagem)
            if len(texto) > maximos[campo]:
                erro = f"{rotulo} com {len(texto)} caracteres (máx. {maximos[campo]})"
                if erro not in erros:
                    erros.append(erro)
        if erros:
            reprovados[campo] = erros
    return reprovados
