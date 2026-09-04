"""Lê a saída normalizada do `radar` e devolve o dia inteiro em memória.

Fronteira entre os dois pacotes: daqui para baixo nada julga relevância; o que
o `radar` gravou é lido como está, inclusive o status de cada fonte, porque é
ele que diz se o boletim do dia sai completo ou com ressalva.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from boletim.edicao import FonteResumo
from radar.core.log import configurar_log
from radar.core.modelos import Publicacao, publicacao_de_dict

AUSENTE = "ausente"
_AVISO_AUSENTE = "arquivo não encontrado"


@dataclass(frozen=True)
class Carga:
    data: date
    fontes: tuple[FonteResumo, ...]
    publicacoes: tuple[Publicacao, ...]

    @property
    def todas_vazias(self) -> bool:
        """Dia sem nada a classificar: feriado, domingo, edição sem saúde.

        Distinto de `parcial`: aqui o boletim sai mesmo assim, com a nota de
        que não houve publicação relevante — silêncio nunca é sinal de falha.
        """
        presentes = [f for f in self.fontes if f.status != AUSENTE]
        if presentes and all(f.status == "vazio" for f in presentes):
            return True
        return not self.publicacoes and not any(
            f.status in ("ok", "parcial") for f in self.fontes
        )

    @property
    def parcial(self) -> bool:
        """Alguma fonte falhou ou nem chegou a ser coletada."""
        return any(f.status in ("parcial", AUSENTE) for f in self.fontes)


def carregar(dir_dados: Path, data: date, fontes_esperadas: list[str]) -> Carga:
    """Junta `dir_dados/normalized/<data>/<fonte>.json` das fontes esperadas.

    Fonte sem arquivo não é erro: vira um `FonteResumo` com status `ausente`,
    para que o boletim saia com o que existe e diga o que faltou. Engolir a
    ausência em silêncio produziria uma edição que parece completa.
    """
    logger = configurar_log()
    pasta = Path(dir_dados) / "normalized" / data.isoformat()
    fontes: list[FonteResumo] = []
    publicacoes: list[Publicacao] = []

    for nome in fontes_esperadas:
        caminho = pasta / f"{nome}.json"
        if not caminho.exists():
            logger.warning("%s: %s em %s", nome, _AVISO_AUSENTE, caminho)
            fontes.append(
                FonteResumo(
                    nome=nome,
                    status=AUSENTE,
                    edicao=None,
                    paginas=None,
                    avisos=(_AVISO_AUSENTE,),
                )
            )
            continue
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        pubs = [publicacao_de_dict(bruto, data) for bruto in dados.get("publicacoes", [])]
        fontes.append(
            FonteResumo(
                nome=nome,
                status=dados["status"],
                edicao=next((p.edicao for p in pubs if p.edicao), None),
                paginas=_faixa_de_paginas(pubs),
                avisos=tuple(dados.get("avisos", ())),
            )
        )
        publicacoes.extend(pubs)

    return Carga(data=data, fontes=tuple(fontes), publicacoes=tuple(publicacoes))


def _faixa_de_paginas(pubs: list[Publicacao]) -> str | None:
    """`"pp. min-max"` das publicações que trazem página; `None` se nenhuma traz."""
    paginas = [p.pagina for p in pubs if p.pagina is not None]
    if not paginas:
        return None
    return f"pp. {min(paginas)}-{max(paginas)}"
