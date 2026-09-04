"""Acesso HTTP com política de retry que distingue falha transitória de permanente."""

from __future__ import annotations

import time

import requests

from radar.core.erros import FonteIndisponivel
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
    aceitar_404: bool = False,
    headers: dict[str, str] | None = None,
) -> bytes | None:
    """Busca a URL devolvendo bytes crus.

    Erro transitório (rede, 5xx, 429) é retentado com backoff exponencial.
    Erro permanente (4xx, 401 incluído) não é: retentar um 404 nunca o
    transforma em 200, e um 401 é bloqueio de acesso, não ausência de edição.

    `aceitar_404` devolve `None` no lugar de levantar, e só quem sabe que
    naquela URL o 404 significa "o arquivo do dia não existe" pode pedi-lo —
    é o caso do download do INLABS num domingo. Para as demais fontes o 404
    continua sendo erro permanente.
    """
    logger = configurar_log()
    ultimo: Exception | None = None
    # `headers` só entra na chamada quando há o que passar: assim qualquer
    # objeto com assinatura `get(url, timeout)` — as sessões falsas dos testes
    # inclusive — continua servindo de sessão.
    extras = {"headers": headers} if headers else {}

    for tentativa in range(1, tentativas + 1):
        try:
            resposta = sessao.get(url, timeout=_TIMEOUT, **extras)
        except requests.RequestException as exc:
            ultimo = exc
            logger.warning("Falha de rede em %s (tentativa %d/%d): %s", url, tentativa, tentativas, exc)
        else:
            codigo = resposta.status_code
            if codigo == 200:
                return resposta.content
            if codigo == 404 and aceitar_404:
                logger.info("HTTP 404 em %s: arquivo inexistente nesta data", url)
                return None
            # Sem ramo para 401: a validação contra a API real provou que num
            # dia sem edição ela responde HTTP 200 com `{"dados":null}`, nunca
            # 401. O único 401 que ela pode emitir é bloqueio de acesso (WAF, IP
            # banido) — que, traduzido em "domingo, siga sem alarme", calaria a
            # coleta todo dia, para sempre. Cai no erro permanente.
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
