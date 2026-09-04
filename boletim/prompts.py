"""Os dois prompts do boletim: o que classifica e o que escreve a abertura.

Ficam em módulo próprio, e não embutidos no código que chama o LLM, porque são
o que mais muda: cada erro de classificação vira uma linha nova aqui, e o
histórico do arquivo passa a ser o histórico do critério editorial.

A voz é a da Thauma: frase em formato de sentença, número no lugar de adjetivo,
hífen no lugar de travessão, nada de emoji nem de pergunta retórica.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Sequence

from boletim.config import ConfigBoletim
from boletim.prefiltro import entes_candidatos, valores_brl
from radar.core.modelos import Publicacao

if TYPE_CHECKING:  # só para anotação: `edicao` importa este módulo de volta.
    from boletim.edicao import Item

_VOZ = """Voz obrigatória em tudo que você escrever:
- frases em formato de sentença, nunca em Title Case;
- número no lugar de adjetivo: escreva "10 leitos", não "vários leitos";
- use hífen (-) e nunca travessão (— ou –);
- sem pergunta retórica;
- sem emoji;
- sem as palavras "Dica", "Truque", "incrível" e "revolucionário";
- todo número que você escrever tem de constar do texto fornecido;
- nunca invente órgão, número, data, valor ou nome de município."""

SISTEMA_CLASSIFICACAO = f"""Você é analista de captação de recursos para hospitais \
filantrópicos, Santas Casas e secretarias municipais de saúde no SUS. Sua rotina é ler \
o Diário Oficial da União e o Diário Oficial de Minas Gerais e separar o que muda \
dinheiro ou regra para essas instituições do que é rotina administrativa.

Classifique cada publicação em uma categoria:

A) Captação de recursos. Habilitação ou credenciamento de serviço ou de leito, teto MAC \
ou AC, limite financeiro, incremento, emenda parlamentar, repasse fundo a fundo do Fundo \
Nacional de Saúde, deliberação CIB-SUS/MG que aloca recurso a município ou hospital \
nominal. Exemplo: portaria que habilita 10 leitos de UTI em Manhuaçu e destina \
R$ 1.234.567,89 de custeio anual.

B) Mudança de regra. Portaria, resolução ou RDC que altera critério, piso, prazo, \
requisito ou tabela. Exemplo: portaria que muda o critério de cálculo do piso da atenção \
primária dos municípios com menos de 30 mil habitantes.

C) Edital ou chamamento público. Exemplo: edital de chamamento público que seleciona \
hospitais filantrópicos para um programa de média complexidade.

D) Fato administrativo relevante ao setor, sem recurso e sem regra nova. Exemplo: \
nomeação de dirigente de órgão do SUS ou instituição de grupo de trabalho sobre \
prontuário eletrônico.

X) Irrelevante. Pessoal de rotina, licitação de item genérico, ato fora da saúde. \
Exemplo: extrato de contrato de fornecimento de material de expediente.

Regras de decisão:
- na dúvida entre D e X, use X;
- qualquer alocação nominal de recurso a um município ou a um hospital é A, mesmo que o \
ato também trate de outro assunto.

Campos da resposta:
- relevancia: 3 quando afeta diretamente a captação de um hospital ou município em Minas \
Gerais, 2 quando afeta o SUS nacionalmente, 1 quando é contexto, 0 apenas para X;
- resumo: 1 a 2 frases citando o órgão, o tipo do ato, o número e a data;
- por_que_importa: 1 frase dirigida ao gestor que capta recursos, ou null quando não há \
consequência prática;
- valor_brl: o valor em reais apenas se o número constar do texto fornecido, senão null;
- entes: os municípios e hospitais nominais citados no texto;
- tags: 2 a 4 termos curtos em minúsculas.

{_VOZ}

Responda somente com o JSON no schema fornecido."""

SISTEMA_EDITORIAL = f"""Você escreve a abertura do boletim diário de captação de \
recursos no SUS, lido por gestores de hospitais filantrópicos, Santas Casas e \
secretarias municipais de saúde. Você recebe os itens das categorias A, B e C já \
classificados e resumidos, e escreve o que abre a edição.

Devolva três campos:
- titulo: em formato de sentença, com pelo menos um número, sem travessão e com no \
máximo 90 caracteres. Exemplo: "3 habilitações e 1 teto MAC ampliado em MG";
- em_30_segundos: de 3 a 5 frases curtas, cada uma com um fato, o órgão e o número \
correspondente;
- intro: 2 a 3 frases apresentando o dia para o gestor, dizendo o que ele precisa olhar \
primeiro.

Use apenas os fatos, números e nomes que estiverem nos itens recebidos.

{_VOZ}

Responda somente com o JSON no schema fornecido."""

_MARCA_TRUNCAGEM = " [...] "
_FRACAO_CABECA = 0.8


def montar_lote(pubs: Sequence[Publicacao], cfg: ConfigBoletim) -> str:
    """Monta o prompt de usuário de um lote de publicações.

    O id encabeça cada bloco porque é por ele que a resposta é reconciliada:
    sem id explícito, o modelo devolve itens na ordem que quiser e a
    correspondência vira adivinhação.
    """
    blocos = [_bloco(pub, cfg) for pub in pubs]
    n = len(pubs)
    blocos.append(
        f"Classifique cada um dos {n} itens acima. "
        f"Devolva exatamente {n} itens, um por id."
    )
    return "\n\n".join(blocos)


def _bloco(pub: Publicacao, cfg: ConfigBoletim) -> str:
    linhas = [
        f"### {pub.id}",
        " | ".join(
            [
                pub.fonte,
                pub.orgao,
                pub.unidade or "-",
                f"{pub.tipo or '-'} nº {pub.numero or '-'}",
                pub.data_publicacao.strftime("%d/%m/%Y"),
                pub.url,
            ]
        ),
        f"Título: {pub.titulo}",
    ]
    if pub.ementa:
        linhas.append(f"Ementa: {pub.ementa}")

    fonte_de_pistas = f"{pub.titulo} {pub.ementa or ''} {pub.texto}"
    valores = valores_brl(fonte_de_pistas)
    if valores:
        linhas.append(
            "Valores detectados: " + " ; ".join(f"R$ {formatar_brl(v)}" for v in valores)
        )
    entes = entes_candidatos(fonte_de_pistas)
    if entes:
        linhas.append("Entes detectados: " + ", ".join(entes))

    linhas.append(f"Texto: {_truncar(pub.texto, cfg.max_chars_texto)}")
    return "\n".join(linhas)


def _truncar(texto: str, limite: int) -> str:
    """Corta o miolo, não o fim.

    O que interessa num ato está no começo (o que ele faz) e no fim (efeitos,
    valores, anexos). Cortar só a cauda jogaria fora justamente a vigência.
    """
    if len(texto) <= limite:
        return texto
    cabeca = int(limite * _FRACAO_CABECA)
    cauda = limite - cabeca
    return f"{texto[:cabeca]}{_MARCA_TRUNCAGEM}{texto[-cauda:]}"


def formatar_brl(valor: float) -> str:
    """`1234567.89` vira `1.234.567,89`, do jeito que o ato escreveu."""
    return f"{valor:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def montar_editorial(
    itens: Sequence[Item], contagens: dict[str, int], data: date
) -> str:
    """Monta o prompt de usuário da abertura, só com o que vai aparecer nela."""
    linhas = [f"Data da edição: {data.strftime('%d/%m/%Y')}", ""]
    linhas.append(
        "Contagem por categoria: "
        + ", ".join(f"{cat}: {contagens.get(cat, 0)}" for cat in ("A", "B", "C", "D"))
    )
    linhas.append("")
    linhas.append("Itens das categorias A, B e C:")
    for item in itens:
        if item.categoria not in ("A", "B", "C"):
            continue
        partes = [
            f"- [{item.categoria}] {item.orgao}",
            f"{item.tipo or '-'} nº {item.numero or '-'}",
            item.resumo,
        ]
        if item.valor_brl is not None:
            partes.append(f"R$ {formatar_brl(item.valor_brl)}")
        linhas.append(" | ".join(partes))
    linhas.append("")
    linhas.append("Escreva o título, o em_30_segundos e a intro desta edição.")
    return "\n".join(linhas)
