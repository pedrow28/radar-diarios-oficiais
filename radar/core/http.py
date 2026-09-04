"""Acesso HTTP com política de retry que distingue falha transitória de permanente."""

from __future__ import annotations

import time

import requests

from radar.core.erros import FonteIndisponivel, SemEdicao
from radar.core.log import configurar_log

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 429 entra aqui porque é limite de taxa, não erro do pedido.
_TRANSITORIOS = {429, 500, 502, 503, 504}
_TIMEOUT = 60


def criar_sessao(user_agent: str | None = None) -> requests.Session:
    sessao = requests.Session()
    sessao.headers["User-Agent"] = user_agent or USER_AGENT
    return sessao


def obter_bytes(
    sessao,
    url: str,
    *,
    tentativas: int = 3,
    espera_base: float = 1.0,
) -> bytes:
    """Busca a URL devolvendo bytes crus.

    Erro transitório (rede, 5xx, 429) é retentado com backoff exponencial.
    Erro permanente (4xx) não é: retentar um 404 nunca o transforma em 200.
    """
    logger = configurar_log()
    ultimo: Exception | None = None

    for tentativa in range(1, tentativas + 1):
        try:
            resposta = sessao.get(url, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            ultimo = exc
            logger.warning("Falha de rede em %s (tentativa %d/%d): %s", url, tentativa, tentativas, exc)
        else:
            codigo = resposta.status_code
            if codigo == 200:
                return resposta.content
            if codigo == 401:
                raise SemEdicao(f"Sem edição disponível em {url} (HTTP 401)")
            if codigo not in _TRANSITORIOS:
                raise FonteIndisponivel(f"HTTP {codigo} em {url} (erro permanente, sem retry)")
            ultimo = FonteIndisponivel(f"HTTP {codigo} em {url}")
            logger.warning("HTTP %d em %s (tentativa %d/%d)", codigo, url, tentativa, tentativas)

        if tentativa < tentativas and espera_base:
            time.sleep(espera_base * (2 ** (tentativa - 1)))

    raise FonteIndisponivel(f"Falhou após {tentativas} tentativas em {url}: {ultimo}")


def obter_texto(
    sessao,
    url: str,
    *,
    encoding: str,
    tentativas: int = 3,
    espera_base: float = 1.0,
) -> str:
    """Busca a URL decodificando com o encoding informado.

    O encoding é sempre explícito porque a busca do DOU declara `charset=UTF-8`
    e serve ISO-8859-1; confiar no header produz mojibake.
    """
    bruto = obter_bytes(sessao, url, tentativas=tentativas, espera_base=espera_base)
    return bruto.decode(encoding)
