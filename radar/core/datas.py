"""Resolução de datas no fuso do diário, não no do servidor."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

TZ_BR = ZoneInfo("America/Sao_Paulo")

_FORMATOS = ("%Y-%m-%d", "%d/%m/%Y")


def hoje() -> date:
    """Data de hoje no fuso de São Paulo.

    Usar UTC aqui faz qualquer execução após as 21h BRT pedir a edição de
    amanhã, que não existe.
    """
    return datetime.now(TZ_BR).date()


def agora_utc() -> datetime:
    """Instante atual em UTC, para carimbar `coletado_em`."""
    return datetime.now(timezone.utc)


def parse_data(texto: str) -> date:
    """Interpreta AAAA-MM-DD ou DD/MM/AAAA."""
    for formato in _FORMATOS:
        try:
            return datetime.strptime(texto.strip(), formato).date()
        except ValueError:
            continue
    raise ValueError(f"Data inválida: {texto!r}. Use AAAA-MM-DD ou DD/MM/AAAA.")
