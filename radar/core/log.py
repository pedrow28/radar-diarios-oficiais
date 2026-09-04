"""Logging configurado uma única vez por processo."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

NOME = "radar"
_FORMATO = "%(asctime)s | %(levelname)-8s | %(message)s"


def configurar_log(nivel: str = "INFO", arquivo: Path | None = None) -> logging.Logger:
    """Devolve o logger do radar, configurando-o só na primeira chamada.

    Idempotente de propósito: os scripts atuais chamam o setup no `main()` e de
    novo dentro do `run()`, o que duplica cada linha e cria dois arquivos de log.
    """
    logger = logging.getLogger(NOME)
    if any(getattr(h, "_radar_handler", False) for h in logger.handlers):
        return logger

    logger.setLevel(getattr(logging, nivel.upper(), logging.INFO))
    logger.propagate = False

    formatador = logging.Formatter(_FORMATO)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatador)
    console._radar_handler = True  # type: ignore[attr-defined]
    logger.addHandler(console)

    if arquivo is not None:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        em_disco = logging.FileHandler(arquivo, encoding="utf-8")
        em_disco.setFormatter(formatador)
        em_disco._radar_handler = True  # type: ignore[attr-defined]
        logger.addHandler(em_disco)

    return logger
