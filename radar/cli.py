"""Interface de linha de comando. Pensada para cron e para agente."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from radar.core.config import Config
from radar.core.datas import hoje, parse_data
from radar.core.erros import ErroRadar, Status, status_para_exit
from radar.core.http import criar_sessao
from radar.core.log import configurar_log
from radar.core.storage import Storage


def _montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="radar", description="Radar de Diários Oficiais")
    # `--config` fica só nos subcomandos: declará-lo também no parser de topo faz
    # o default do subparser sobrescrever silenciosamente o valor informado antes
    # do subcomando.
    sub = parser.add_subparsers(dest="comando", required=True)

    coletar = sub.add_parser("coletar", help="Coleta as publicações de uma data")
    coletar.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    coletar.add_argument("--data", default=None, help="AAAA-MM-DD ou DD/MM/AAAA (padrão: hoje)")
    coletar.add_argument("--fonte", choices=["dou", "iofmg", "todas"], default="todas")
    coletar.add_argument("--forcar", action="store_true", help="Ignora o cache de artefatos brutos")

    consultar = sub.add_parser("consultar", help="Busca no histórico já coletado")
    consultar.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    consultar.add_argument("termo")
    consultar.add_argument("--desde", default=None)
    return parser


def _fontes(nome: str, cfg: Config, storage: Storage, sessao) -> list:
    from radar.fontes.dou.coletor import FonteDOU
    from radar.fontes.iofmg.coletor import FonteIOFMG

    disponiveis = {
        "dou": lambda: FonteDOU(cfg.dou, storage, sessao),
        "iofmg": lambda: FonteIOFMG(cfg.iofmg, storage, sessao),
    }
    chaves = list(disponiveis) if nome == "todas" else [nome]
    return [disponiveis[c]() for c in chaves]


def _coletar(args) -> int:
    logger = configurar_log()
    cfg = Config.carregar(args.config)
    data = parse_data(args.data) if args.data else hoje()

    storage = Storage(cfg.dir_dados)
    sessao = criar_sessao()
    pior = 0
    try:
        for fonte in _fontes(args.fonte, cfg, storage, sessao):
            try:
                resultado = fonte.coletar(data, forcar=args.forcar)
            except ErroRadar as exc:
                logger.error("%s falhou: %s", fonte.nome, exc)
                pior = max(pior, status_para_exit(Status.ERRO))
                continue
            storage.salvar_normalizado(resultado)
            storage.gravar(resultado.publicacoes)
            pior = max(pior, status_para_exit(resultado.status))
            print(
                f"{resultado.fonte}: {resultado.status} | "
                f"{len(resultado.publicacoes)} publicações | {len(resultado.avisos)} avisos"
            )
    finally:
        storage.fechar()
    return pior


def _consultar(args) -> int:
    cfg = Config.carregar(args.config)
    storage = Storage(cfg.dir_dados)
    try:
        desde = parse_data(args.desde) if args.desde else None
        for linha in storage.consultar(args.termo, desde):
            print(f"{linha['data_publicacao']} | {linha['fonte']:6s} | {linha['titulo'][:70]}")
            print(f"    {linha['texto'][:160]}")
    finally:
        storage.fechar()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _montar_parser().parse_args(argv)
    configurar_log()
    try:
        if args.comando == "coletar":
            return _coletar(args)
        return _consultar(args)
    except (ErroRadar, ValueError, FileNotFoundError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2


def executar() -> None:
    raise SystemExit(main())


# Sem esta guarda, `python -m radar.cli coletar ...` importa o modulo, nao roda
# nada e sai com codigo 0. Um cron nessa forma reportaria sucesso todo dia sem
# coletar coisa alguma — falha total silenciosa, que e exatamente o que o
# contrato de status existe para impedir.
if __name__ == "__main__":
    executar()
