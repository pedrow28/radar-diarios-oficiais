"""Interface de linha de comando do boletim. Pensada para cron e para agente."""

from __future__ import annotations

import argparse
from pathlib import Path


def _montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="boletim", description="Boletim do Radar de Diários Oficiais"
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    gerar = sub.add_parser("gerar", help="Classifica as publicações do dia e monta a edição")
    gerar.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    gerar.add_argument("--data", default=None, help="AAAA-MM-DD (padrão: hoje)")

    renderizar = sub.add_parser("renderizar", help="Renderiza a edição em HTML/e-mail")
    renderizar.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    renderizar.add_argument("--data", default=None, help="AAAA-MM-DD (padrão: hoje)")

    site = sub.add_parser("site", help="Publica a edição no site estático")
    site.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    site.add_argument("--data", default=None, help="AAAA-MM-DD (padrão: hoje)")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Despacha o subcomando. Por enquanto nenhum está implementado."""
    args = _montar_parser().parse_args(argv)
    print(f"{args.comando}: não implementado")
    return 2


def executar() -> None:
    raise SystemExit(main())


# Sem esta guarda, `python -m boletim.cli gerar ...` importa o modulo, nao roda
# nada e sai com codigo 0. Um cron nessa forma reportaria sucesso todo dia sem
# gerar coisa alguma — falha total silenciosa, que e exatamente o que o
# contrato de status existe para impedir.
if __name__ == "__main__":
    executar()
