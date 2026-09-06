"""Recorte por órgão, compartilhado pelas duas fontes do DOU.

O portal (`hierarchyStr`) e o INLABS (`artCategory`) descrevem o órgão do mesmo
jeito: níveis separados por "/". A regra de quem entra é, portanto, uma só —
duplicá-la faria as duas fontes divergirem no primeiro ajuste feito num lado só.
"""

from __future__ import annotations

from collections.abc import Sequence

# A ANVISA às vezes é 1º nível da hierarquia e às vezes vem sob o "Ministério
# da Saúde" — o mesmo órgão, em duas árvores. Casar em qualquer nível é o que
# impede a RDC de sumir conforme o dia.
ANVISA = "Agência Nacional de Vigilância Sanitária"

# A "Presidência da República" assina boa parte do diário. Sem exigir a
# subunidade, incluí-la em `orgaos` faria o recorte deixar de recortar.
PRESIDENCIA = "Presidência da República"


def niveis_de(hierarquia: str | None) -> list[str]:
    """Quebra "A/B/C" nos níveis não vazios, já sem espaço nas pontas."""
    return [n.strip() for n in (hierarquia or "").split("/") if n.strip()]


def em_escopo(
    niveis: Sequence[str],
    orgaos: Sequence[str],
    subunidades_extra: Sequence[str],
) -> bool:
    """Diz se a hierarquia é de um órgão que se quer acompanhar."""
    if ANVISA in orgaos and ANVISA in niveis:
        return True
    primeiro = niveis[0] if niveis else ""
    if primeiro not in orgaos:
        return False
    if primeiro == PRESIDENCIA:
        return len(niveis) > 1 and niveis[1] in subunidades_extra
    return True
