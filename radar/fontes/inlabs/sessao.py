"""Login e download no INLABS, o serviço de distribuição do DOU em XML.

O portal `in.gov.br` bloqueia IP de datacenter; este serviço é a porta oficial
para quem coleta de nuvem. Exige conta gratuita, e o acesso é por cookie de
sessão obtido num POST de formulário.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

from radar.core.erros import FonteIndisponivel
from radar.core.http import _TIMEOUT, criar_sessao, obter_bytes
from radar.core.log import configurar_log

URL_LOGIN = "https://inlabs.in.gov.br/logar.php"
_URL_BASE = "https://inlabs.in.gov.br/index.php"

# Hex de "script". O serviço exige o header para atender cliente que não é
# navegador — no login e também no download.
HEADER_ORIGEM = {"origem": "736372697072"}

# O serviço responde 200 com a própria página de login quando recusa as
# credenciais. Só a presença deste cookie distingue entrar de não entrar.
_COOKIE_SESSAO = "inlabs_session_cookie"


def montar_url_download(data: date, secao: str) -> str:
    """URL do zip de uma seção (`DO1`, `DO2`, `DO3` e as extras `DO1E`…)."""
    dia = data.isoformat()
    return f"{_URL_BASE}?p={dia}&dl={dia}-{secao}.zip"


def abrir_sessao(email: str, senha: str, sessao=None):
    """Autentica e devolve a sessão com o cookie do INLABS.

    A senha nunca é registrada: ela passa daqui direto para o corpo do POST.
    """
    logger = configurar_log()
    sessao = criar_sessao() if sessao is None else sessao
    cabecalhos = {**HEADER_ORIGEM, "Content-Type": "application/x-www-form-urlencoded"}

    logger.info("INLABS: autenticando %s", email)
    sessao.post(URL_LOGIN, data={"email": email, "password": senha},
                headers=cabecalhos, timeout=_TIMEOUT)

    if _COOKIE_SESSAO not in sessao.cookies:
        raise FonteIndisponivel("login INLABS recusado (cookie de sessão ausente)")
    return sessao


def baixar_zip(sessao, data: date, secao: str) -> bytes | None:
    """Baixa o zip da seção. `None` quando não existe arquivo nessa data.

    404 aqui é domingo, feriado ou seção ainda não publicada — a resposta
    normal do serviço, não uma falha. Já um 200 que não traz um zip é a página
    de login servida no lugar do arquivo: deixá-la seguir faria o parse relatar
    "edição sem matérias" no lugar do bloqueio real.
    """
    url = montar_url_download(data, secao)
    bruto = obter_bytes(sessao, url, aceitar_404=True, headers=HEADER_ORIGEM)
    if bruto is None:
        return None
    if not zipfile.is_zipfile(io.BytesIO(bruto)):
        raise FonteIndisponivel(
            f"resposta de {url} não é um zip ({len(bruto)} bytes); "
            f"a sessão do INLABS pode ter expirado"
        )
    return bruto
