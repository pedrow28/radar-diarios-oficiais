"""Recorte por órgão, compartilhado pelas duas fontes do DOU.

O portal (`hierarchyStr`) e o INLABS (`artCategory`) descrevem o órgão do mesmo
jeito: níveis separados por "/". A regra de quem entra é, portanto, uma só —
duplicá-la faria as duas fontes divergirem no primeiro ajuste feito num lado só.

A comparação é **normalizada**: sem caixa, sem acento e com o espaço colapsado.
Os níveis são texto livre da fonte, não um enum — a coleta real de 04/09 trouxe
`Secretaria do Tesouro Nacional` e `Gabinete do Ministro` escritos à mão —, e a
igualdade exata transforma qualquer divergência de digitação entre o YAML e o
diário num recorte que descarta tudo sem dizer nada.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

# A ANVISA às vezes é 1º nível da hierarquia e às vezes vem sob o "Ministério
# da Saúde" — o mesmo órgão, em duas árvores. Casar em qualquer nível é o que
# impede a RDC de sumir conforme o dia.
ANVISA = "Agência Nacional de Vigilância Sanitária"

# A "Presidência da República" assina boa parte do diário. Sem exigir a
# subunidade, incluí-la em `orgaos` faria o recorte deixar de recortar.
PRESIDENCIA = "Presidência da República"

_ESPACO = re.compile(r"\s+")


def normalizar(nome: str) -> str:
    """Chave de comparação de um nome de órgão ou de unidade.

    Sem acento, sem caixa e com o espaço colapsado: é o mínimo para que a
    diferença de digitação entre o YAML e o que a fonte publicou não vire um
    recorte vazio e silencioso.
    """
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return _ESPACO.sub(" ", sem_acento).strip().lower()


def niveis_de(hierarquia: str | None) -> list[str]:
    """Quebra "A/B/C" nos níveis não vazios, já sem espaço nas pontas."""
    return [n.strip() for n in (hierarquia or "").split("/") if n.strip()]


def em_escopo(
    niveis: Sequence[str],
    orgaos: Sequence[str],
    subunidades_extra: Sequence[str],
) -> bool:
    """Diz se a hierarquia é de um órgão que se quer acompanhar."""
    alvo = {normalizar(o) for o in orgaos}
    anvisa = normalizar(ANVISA)
    if anvisa in alvo and any(normalizar(n) == anvisa for n in niveis):
        return True
    primeiro = normalizar(niveis[0]) if niveis else ""
    if primeiro not in alvo:
        return False
    if primeiro == normalizar(PRESIDENCIA):
        exigidas = {normalizar(u) for u in subunidades_extra}
        return len(niveis) > 1 and normalizar(niveis[1]) in exigidas
    return True
