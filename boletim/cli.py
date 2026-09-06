"""Interface de linha de comando do boletim. Pensada para cron e para agente.

O contrato de saída é o mesmo do `radar`: 0 saiu inteiro, 1 saiu com ressalva,
2 não saiu. A ressalva importa porque uma edição com uma fonte faltando ainda
vale a pena publicar - o prazo de um edital não espera o IOF-MG voltar.

`gerar` renderiza tudo em memória antes de escrever qualquer arquivo. Se o LLM
cair ou um template quebrar, a falha acontece antes da primeira gravação e o
site continua exatamente como estava; meia edição no ar é pior que nenhuma.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from boletim import site as publicacao
from boletim.carga import Carga, carregar
from boletim.classifica import classificar
from boletim.config import ConfigBoletim
from boletim.edicao import (
    ROTULOS,
    Edicao,
    FonteResumo,
    Item,
    item_de_dict,
    item_para_dict,
    montar_edicao,
    ordenar,
)
from boletim.llm import LLM, ClaudeCodeCLI, LLMFalso
from boletim.prefiltro import Triagem, triar
from boletim.render import render_email, render_md, render_web
from radar.core.datas import agora_utc, hoje, parse_data
from radar.core.log import configurar_log

# `--llm falso` usa as respostas das fixtures por padrão: é o modo de ensaiar o
# pipeline inteiro sem gastar chamada de modelo nem depender de rede.
RESPOSTAS_PADRAO = Path("tests/fixtures/boletim/llm")
ARQUIVOS_FALSOS = {"lote-0": "lote1.json", "editorial": "editorial.json"}


def _montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="boletim", description="Boletim do Radar de Diários Oficiais"
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    gerar = sub.add_parser("gerar", help="Classifica as publicações do dia e monta a edição")
    gerar.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    gerar.add_argument("--data", default=None, help="AAAA-MM-DD (padrão: hoje)")
    gerar.add_argument(
        "--llm",
        choices=("claude", "falso"),
        default="claude",
        help="'falso' responde das fixtures, sem rede e sem custo",
    )
    gerar.add_argument(
        "--respostas",
        type=Path,
        default=RESPOSTAS_PADRAO,
        help=f"pasta com {' e '.join(ARQUIVOS_FALSOS.values())}, para --llm falso",
    )
    gerar.add_argument("--sem-site", action="store_true", help="Não publica no site")

    renderizar = sub.add_parser("renderizar", help="Renderiza a edição já gerada, sem LLM")
    renderizar.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    renderizar.add_argument("--data", default=None, help="AAAA-MM-DD (padrão: hoje)")

    site = sub.add_parser("site", help="Reconstrói o índice do site estático")
    site.add_argument("--config", type=Path, default=Path("config/config.yaml"))

    return parser


def _llm(args, cfg: ConfigBoletim) -> LLM:
    """O modelo real ou o dublê alimentado por uma pasta de respostas gravadas.

    Arquivo faltando não é erro: sem ele o rótulo simplesmente não tem resposta,
    e o pipeline percorre o mesmo caminho de um modelo fora do ar.
    """
    if args.llm == "claude":
        return ClaudeCodeCLI(cfg.modelo, cfg.timeout_llm_s)
    respostas: dict[str, dict | list[dict]] = {}
    for rotulo, arquivo in ARQUIVOS_FALSOS.items():
        caminho = Path(args.respostas) / arquivo
        if caminho.exists():
            respostas[rotulo] = json.loads(caminho.read_text(encoding="utf-8"))
    return LLMFalso(respostas)


def _gerar(args) -> int:
    cfg = ConfigBoletim.carregar(args.config)
    data = parse_data(args.data) if args.data else hoje()
    carga = carregar(cfg.dir_dados, data, cfg.fontes)

    if carga.todas_vazias:
        # Silêncio não é falha: feriado e domingo saem 0, e sem arquivo nenhum.
        print("boletim: vazio")
        return 0

    llm = _llm(args, cfg)
    triagem = triar(carga.publicacoes, cfg)
    itens, avisos_llm = classificar(triagem.mantidas, llm, cfg)
    edicao = montar_edicao(itens, carga.fontes, carga.parcial, llm, data, agora_utc())
    avisos = [*triagem.avisos, *avisos_llm]

    # Tudo renderizado antes da primeira gravação: template quebrado falha aqui,
    # com o site ainda intacto.
    email = render_email(edicao, cfg)
    web = render_web(edicao, cfg)
    markdown = render_md(edicao, cfg)

    dia = Path(cfg.dir_saida) / data.isoformat()
    dia.mkdir(parents=True, exist_ok=True)
    _gravar_json(dia / "prefiltro.json", _ficha_prefiltro(data, carga, triagem))
    _gravar_json(dia / "itens.json", _ficha_itens(edicao, itens, avisos))
    _gravar_texto(dia / "edicao.md", markdown)
    _gravar_texto(dia / "edicao.html", email)

    if not args.sem_site:
        print(f"boletim: site em {publicacao.publicar(edicao, web, cfg)}")

    print(_linha_de_status(len(carga.publicacoes), len(triagem.mantidas), itens, edicao))
    return 1 if edicao.parcial or avisos else 0


def _renderizar(args) -> int:
    """Refaz os artefatos do dia a partir do disco, sem gastar uma chamada de LLM.

    É o comando de corrigir template: o julgamento do dia já está em
    `itens.json` e não precisa ser pedido de novo ao modelo.
    """
    cfg = ConfigBoletim.carregar(args.config)
    data = parse_data(args.data) if args.data else hoje()
    dia = Path(cfg.dir_saida) / data.isoformat()

    ficha_itens = _ler_json(dia / "itens.json")
    ficha_prefiltro = _ler_json(dia / "prefiltro.json")
    edicao = _edicao_de_ficha(ficha_itens, data)
    itens = [item_de_dict(d) for d in ficha_itens["itens"]]

    email = render_email(edicao, cfg)
    web = render_web(edicao, cfg)
    _gravar_texto(dia / "edicao.md", render_md(edicao, cfg))
    _gravar_texto(dia / "edicao.html", email)
    print(f"boletim: site em {publicacao.publicar(edicao, web, cfg)}")
    print(
        _linha_de_status(
            ficha_prefiltro["publicacoes"], ficha_prefiltro["mantidas"], itens, edicao
        )
    )
    return 0


def _site(args) -> int:
    cfg = ConfigBoletim.carregar(args.config)
    print(f"boletim: índice em {publicacao.reconstruir_indice(cfg)}")
    return 0


# ── arquivos do dia ─────────────────────────────────────────────────────
def _ficha_prefiltro(data: date, carga: Carga, triagem: Triagem) -> dict[str, Any]:
    """O que a triagem jogou fora e por qual regra: auditável e reversível."""
    return {
        "data": data.isoformat(),
        "publicacoes": len(carga.publicacoes),
        "mantidas": len(triagem.mantidas),
        "avisos": list(triagem.avisos),
        "descartadas": [{"id": d.id, "regra": d.regra} for d in triagem.descartadas],
    }


def _ficha_itens(edicao: Edicao, itens: list[Item], avisos: list[str]) -> dict[str, Any]:
    """Tudo que `renderizar` precisa para refazer a edição sem chamar o LLM.

    Inclusive os itens em X, que não entram na edição: sem eles, regerar o dia
    perderia o registro de que a publicação existiu e foi julgada irrelevante.
    """
    return {
        "data": edicao.data.isoformat(),
        "gerado_em": edicao.gerado_em.isoformat(),
        "avisos": avisos,
        "edicao": {
            "titulo": edicao.titulo,
            "em_30_segundos": list(edicao.em_30_segundos),
            "intro": edicao.intro,
            "parcial": edicao.parcial,
            "fontes": [
                {
                    "nome": fonte.nome,
                    "status": fonte.status,
                    "edicao": fonte.edicao,
                    "paginas": fonte.paginas,
                    "avisos": list(fonte.avisos),
                }
                for fonte in edicao.fontes
            ],
        },
        "itens": [item_para_dict(item) for item in itens],
    }


def _edicao_de_ficha(ficha: dict[str, Any], data: date) -> Edicao:
    cabecalho = ficha["edicao"]
    itens = [item_de_dict(d) for d in ficha["itens"]]
    return Edicao(
        data=data,
        titulo=cabecalho["titulo"],
        em_30_segundos=tuple(cabecalho["em_30_segundos"]),
        intro=cabecalho["intro"],
        secoes=ordenar(itens),
        fontes=tuple(
            FonteResumo(**{**fonte, "avisos": tuple(fonte["avisos"])})
            for fonte in cabecalho["fontes"]
        ),
        parcial=cabecalho["parcial"],
        gerado_em=datetime.fromisoformat(ficha["gerado_em"]),
    )


def _linha_de_status(
    publicacoes: int, mantidas: int, itens: list[Item], edicao: Edicao
) -> str:
    """A linha que o cron guarda no log e o agente lê para decidir o que fazer."""
    categorias = (*ROTULOS, "X")
    contagens = {categoria: 0 for categoria in categorias}
    for item in itens:
        contagens[item.categoria] += 1
    detalhe = " ".join(f"{categoria}={contagens[categoria]}" for categoria in categorias)
    status = "parcial" if edicao.parcial else "ok"
    return (
        f"boletim: {publicacoes} publicações, {mantidas} mantidas, "
        f"{len(itens)} itens ({detalhe}), status={status}"
    )


def _gravar_json(caminho: Path, conteudo: dict[str, Any]) -> None:
    _gravar_texto(caminho, json.dumps(conteudo, ensure_ascii=False, indent=2) + "\n")


def _gravar_texto(caminho: Path, conteudo: str) -> None:
    # `newline="\n"` também no Windows: o mesmo dia gerado na VPS e na máquina
    # do Pedro tem de produzir arquivos idênticos.
    caminho.write_text(conteudo, encoding="utf-8", newline="\n")


def _ler_json(caminho: Path) -> dict[str, Any]:
    if not caminho.exists():
        raise FileNotFoundError(f"arquivo do dia não encontrado: {caminho}")
    return json.loads(caminho.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    """Despacha o subcomando e devolve SEMPRE um exit code do contrato.

    O exit code nunca pode ser escolhido pelo Python: uma exceção que escapa
    sai com 1, e 1 significa `parcial` - "publicou com ressalva" -, então uma
    quebra total seria lida pelo agente como edição aproveitável.
    """
    args = _montar_parser().parse_args(argv)
    logger = configurar_log()
    try:
        if args.comando == "gerar":
            return _gerar(args)
        if args.comando == "renderizar":
            return _renderizar(args)
        return _site(args)
    except Exception as exc:
        logger.exception("boletim %s falhou: %s", args.comando, exc)
        print(f"erro: {exc}", file=sys.stderr)
        return 2


def executar() -> None:
    raise SystemExit(main())


# Sem esta guarda, `python -m boletim.cli gerar ...` importa o modulo, nao roda
# nada e sai com codigo 0. Um cron nessa forma reportaria sucesso todo dia sem
# gerar coisa alguma - falha total silenciosa, que e exatamente o que o
# contrato de status existe para impedir.
if __name__ == "__main__":
    executar()
