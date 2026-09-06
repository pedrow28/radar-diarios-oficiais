"""Regra de escopo compartilhada: mesma hierarquia, mesmo recorte, duas fontes.

O portal (`hierarchyStr`) e o INLABS (`artCategory`) descrevem o órgão da mesma
forma — níveis separados por "/". A regra que decide quem entra vive uma vez só;
duas cópias divergiriam no dia em que uma delas fosse ajustada.
"""

from __future__ import annotations

from radar.fontes.escopo import em_escopo, niveis_de

ORGAOS = [
    "Ministério da Saúde",
    "Presidência da República",
    "Ministério da Fazenda",
    "Ministério do Planejamento e Orçamento",
]
SUBUNIDADES = ["Casa Civil"]


def _em(hierarquia: str, orgaos=None, subunidades=None) -> bool:
    return em_escopo(
        niveis_de(hierarquia),
        orgaos if orgaos is not None else ORGAOS,
        subunidades if subunidades is not None else SUBUNIDADES,
    )


def test_niveis_ignora_vazios_e_espacos():
    assert niveis_de("Ministério da Saúde/ Gabinete do Ministro //") == [
        "Ministério da Saúde",
        "Gabinete do Ministro",
    ]
    assert niveis_de(None) == []
    assert niveis_de("") == []


def test_orgao_configurado_no_primeiro_nivel_entra():
    assert _em("Ministério da Saúde/Gabinete do Ministro")


def test_orgao_de_fora_nao_entra():
    assert not _em("Ministério da Educação/Gabinete do Ministro")


def test_hierarquia_vazia_nao_entra():
    assert not _em("")


def test_presidencia_so_entra_pela_subunidade_configurada():
    assert _em("Presidência da República/Casa Civil")
    assert not _em("Presidência da República/Secretaria-Geral")
    assert not _em("Presidência da República")


def test_anvisa_entra_em_qualquer_nivel_quando_esta_nos_orgaos():
    orgaos = [*ORGAOS, "Agência Nacional de Vigilância Sanitária"]
    assert _em("Agência Nacional de Vigilância Sanitária/Diretoria Colegiada", orgaos)
    assert _em(
        "Ministério da Saúde/Agência Nacional de Vigilância Sanitária/Diretoria Colegiada",
        orgaos,
    )


def test_anvisa_fora_dos_orgaos_nao_entra_por_aninhamento():
    """Aninhada sob um ministério que também está fora, nada a fazer entrar."""
    assert not _em(
        "Ministério da Saúde/Agência Nacional de Vigilância Sanitária",
        ["Ministério da Fazenda"],
    )


def test_anvisa_sob_ministerio_no_escopo_entra_pelo_primeiro_nivel():
    """Sem a ANVISA em `orgaos`, ela entra porque o 1º nível é o Ministério."""
    assert _em("Ministério da Saúde/Agência Nacional de Vigilância Sanitária/Diretoria")


def test_subunidade_extra_so_vale_para_a_presidencia():
    """"Casa Civil" na lista não abre exceção para órgão fora de `orgaos`."""
    assert not _em("Ministério da Educação/Casa Civil")
