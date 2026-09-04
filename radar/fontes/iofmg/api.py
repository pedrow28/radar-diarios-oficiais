"""Cliente da API de edições do Jornal Minas Gerais."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import urlencode

from radar.core.erros import FonteIndisponivel, SemEdicao
from radar.core.http import obter_bytes

URL_API = (
    "https://www.jornalminasgerais.mg.gov.br/api/v1/Jornal/ObterEdicaoPorDataPublicacao"
)


def montar_url(data: date) -> str:
    return f"{URL_API}?{urlencode({'dataPublicacao': data.strftime('%Y-%m-%d')})}"


def dados_de(bruto: bytes, data: date) -> dict:
    """Extrai o objeto `dados` de uma resposta já baixada.

    Separado de `consultar_edicao` para que o caminho com cache em disco e o
    caminho de rede compartilhem exatamente a mesma interpretação.

    O único sinal válido de "sem edição" é a chave `dados` presente e nula —
    validado contra a API num domingo: `{"dados": null, "erros": []}`. Tratar
    qualquer outra coisa falsy (chave ausente, `{}`, `[]`, envelope trocado)
    como sem edição faria uma mudança de esquema na API virar "domingo" para
    sempre, com exit 0 — a falha silenciosa que o contrato de status existe
    para impedir.
    """
    try:
        resposta = json.loads(bruto)
    except json.JSONDecodeError as exc:
        raise FonteIndisponivel(f"Resposta da API do IOF-MG não é JSON: {exc}") from exc

    if not isinstance(resposta, dict) or "dados" not in resposta:
        raise FonteIndisponivel(
            "Resposta da API do IOF-MG não tem a chave 'dados'; o esquema da "
            "resposta pode ter mudado."
        )

    dados = resposta["dados"]
    if dados is None:
        raise SemEdicao(f"Nenhuma edição do IOF-MG publicada em {data.isoformat()}")

    if not isinstance(dados, dict) or not dados:
        raise FonteIndisponivel(
            f"Resposta da API do IOF-MG trouxe 'dados' vazio ou de tipo "
            f"inesperado ({type(dados).__name__}); o esquema da resposta pode "
            f"ter mudado."
        )

    return dados


def consultar_edicao(sessao, data: date) -> dict:
    """Devolve o objeto `dados` da edição. Sem edição na data → `SemEdicao`."""
    return dados_de(obter_bytes(sessao, montar_url(data)), data)


def caderno_principal(dados: dict, descricao: str) -> dict:
    """Localiza o caderno pedido pela descrição configurada."""
    for caderno in dados.get("cadernos", []):
        if caderno.get("descricao") == descricao:
            return caderno
    disponiveis = [c.get("descricao") for c in dados.get("cadernos", [])]
    raise SemEdicao(f"Caderno {descricao!r} não encontrado. Disponíveis: {disponiveis}")


def extrair_base64(dados: dict) -> str:
    return str(dados.get("arquivoCadernoPrincipal", {}).get("arquivo", ""))
