"""Erros tipados e o status de coleta que cada um produz.

O contrato com o agente consumidor depende desta distinção: sem ela, queda de
rede, HTTP 500 e domingo sem edição ficam indistinguíveis.
"""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    OK = "ok"
    VAZIO = "vazio"
    PARCIAL = "parcial"
    ERRO = "erro"


_EXIT_POR_STATUS = {
    Status.OK: 0,
    Status.VAZIO: 0,
    Status.PARCIAL: 1,
    Status.ERRO: 2,
}


def status_para_exit(status: Status) -> int:
    """Converte o status em exit code, para o agente decidir pelo código."""
    return _EXIT_POR_STATUS[status]


class ErroRadar(Exception):
    """Base de todos os erros de coleta."""


class SemEdicao(ErroRadar):
    """Não houve edição publicada nesta data (feriado, domingo, 401 da API)."""


class FonteIndisponivel(ErroRadar):
    """A fonte não respondeu ou respondeu com erro de servidor."""


class ExtracaoParcial(ErroRadar):
    """Coletou, mas parte do conteúdo não pôde ser obtida."""

    def __init__(self, mensagem: str, avisos: list[str] | None = None) -> None:
        super().__init__(mensagem)
        self.avisos = avisos or []
