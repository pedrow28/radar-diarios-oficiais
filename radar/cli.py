"""Interface de linha de comando. Pensada para cron e para agente."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from radar.core.config import Config
from radar.core.datas import hoje, parse_data
from radar.core.erros import Status, status_para_exit
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

    notificar = sub.add_parser("notificar", help="Envia por e-mail o que já foi coletado")
    notificar.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    notificar.add_argument("--data", default=None)
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
            # `Exception`, não só `ErroRadar`: uma `ValueError` do desembrulho,
            # uma `TypeError` de `int(totalPaginas)` ou uma `OSError` de disco
            # escapariam, o Python escolheria exit 1 — que o contrato reserva
            # para `parcial`, "processar e alertar" — e a fonte seguinte nem
            # rodaria. Aqui a fonte quebrada vira `erro` e a outra segue. As
            # gravações em disco/SQLite ficam DENTRO deste `try`: uma falha
            # nelas (disco cheio, SQLite bloqueado) é exatamente do mesmo tipo
            # de acidente que uma falha de coleta e não pode matar a fonte
            # seguinte.
            try:
                resultado = fonte.coletar(data, forcar=args.forcar)
                storage.salvar_normalizado(resultado)
                storage.gravar(resultado.publicacoes)
            except Exception as exc:
                logger.exception("%s falhou: %s", fonte.nome, exc)
                pior = max(pior, status_para_exit(Status.ERRO))
                # Também em stdout: quem captura só stdout perdia a informação
                # de que uma fonte caiu, e via apenas a linha da que deu certo.
                print(f"{fonte.nome}: erro | {exc}")
                continue
            pior = max(pior, status_para_exit(resultado.status))
            print(
                f"{resultado.fonte}: {resultado.status} | "
                f"{len(resultado.publicacoes)} publicações | {len(resultado.avisos)} avisos"
            )
        _limpar_bruto(storage, cfg.reter_bruto_dias, logger)
    finally:
        storage.fechar()
    return pior


def _limpar_bruto(storage: Storage, dias: int, logger) -> None:
    """Aplica a retenção de `raw/` (spec §8.1), sem derrubar a coleta.

    A coleta já terminou aqui: uma falha ao apagar cache antigo não pode
    transformar um dia bem coletado em exit 2.
    """
    try:
        removidos = storage.limpar_raw_antigos(dias)
    except OSError as exc:
        logger.warning("Não foi possível limpar %s: %s", storage.dir_raw, exc)
        return
    if removidos:
        logger.info("Retenção: %d dia(s) de bruto removidos (limite %d dias)", removidos, dias)


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


def _notificar(args) -> int:
    import json

    from radar.core.modelos import Resultado
    from radar.notificacao.email import enviar, montar_html

    cfg = Config.carregar(args.config)
    data = parse_data(args.data) if args.data else hoje()
    pasta = cfg.dir_dados / "normalized" / data.isoformat()
    if not pasta.exists():
        print(f"erro: nada coletado em {data.isoformat()}", file=sys.stderr)
        return 2

    resultados = []
    for arquivo in sorted(pasta.glob("*.json")):
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        resultados.append(
            Resultado(
                fonte=dados["fonte"],
                data_publicacao=data,
                coletado_em=hoje_como_datetime(),
                status=Status(dados["status"]),
                escopo=dados["escopo"],
                publicacoes=[],
                avisos=dados["avisos"],
            )
        )
        resultados[-1].publicacoes = _publicacoes_de(dados, data)

    assunto = f"Radar de Diários Oficiais — {data.strftime('%d/%m/%Y')}"
    enviado = enviar(montar_html(resultados), assunto, cfg.email)
    print("e-mail enviado" if enviado else "e-mail não enviado (ver config/log)")
    return 0


def hoje_como_datetime():
    from radar.core.datas import agora_utc

    return agora_utc()


def _publicacoes_de(dados: dict, data) -> list:
    from datetime import datetime, timezone

    from radar.core.modelos import Publicacao

    publicacoes = []
    for bruto in dados["publicacoes"]:
        campos = dict(bruto)
        campos["data_publicacao"] = data
        campos["coletado_em"] = datetime.fromisoformat(
            campos["coletado_em"].replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        publicacoes.append(Publicacao(**campos))
    return publicacoes


def main(argv: list[str] | None = None) -> int:
    """Despacha o subcomando e devolve SEMPRE um exit code do contrato.

    O exit code nunca pode ser escolhido pelo Python: uma exceção que escapa
    sai com 1, e 1 significa `parcial` — "processar e alertar" —, então uma
    quebra total seria lida pelo agente como coleta aproveitável.
    """
    args = _montar_parser().parse_args(argv)
    logger = configurar_log()
    try:
        if args.comando == "coletar":
            return _coletar(args)
        if args.comando == "notificar":
            return _notificar(args)
        return _consultar(args)
    except Exception as exc:
        logger.exception("radar %s falhou: %s", args.comando, exc)
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
