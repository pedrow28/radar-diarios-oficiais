"""Configuração da aplicação. Comportamento no YAML, segredo no ambiente."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from radar.core.log import configurar_log


def _orgaos_dou_padrao() -> list[str]:
    """Escopo decidido para o DOU. A ANVISA não entra na lista de propósito: no
    portal ela aparece dentro da hierarquia do Ministério da Saúde, e a busca
    por `orgPrin=Ministério da Saúde` já a traz junto."""
    return [
        "Ministério da Saúde",
        "Presidência da República",
        "Ministério da Fazenda",
        "Ministério do Planejamento e Orçamento",
    ]


@dataclass
class ConfigDOU:
    # `orgao` (singular) é a chave antiga, de quando a busca era de um órgão só.
    # Continua aceita: sozinha, vira `orgaos = [orgao]`. Com as duas no YAML,
    # `orgaos` manda — ver `Config.carregar`.
    orgao: str | None = None
    # `None` aqui significa "o YAML não disse nada", que é diferente de uma
    # lista vazia pedida de propósito; sem essa distinção não dava para saber
    # quando cair no `orgao` legado e quando cair no padrão.
    orgaos: list[str] | None = None
    # 2º nível exigido para capturar atos da "Presidência da República", que de
    # outro modo traria o Executivo inteiro. Ver `radar/fontes/escopo.py`.
    subunidades_extra: list[str] = field(default_factory=lambda: ["Casa Civil"])
    delta: int = 75
    concorrencia: int = 5
    baixar_texto_integral: bool = True

    def __post_init__(self) -> None:
        if self.orgaos is None:
            self.orgaos = [self.orgao] if self.orgao else _orgaos_dou_padrao()


@dataclass
class ConfigIOFMG:
    caderno: str = "Diário do Executivo"
    secao: str = "Secretaria de Estado de Saúde"
    tipos_publicacao: list[str] = field(default_factory=list)


def _orgaos_inlabs_padrao() -> list[str]:
    return [
        "Ministério da Saúde",
        "Agência Nacional de Vigilância Sanitária",
        "Presidência da República",
        "Ministério da Fazenda",
        "Ministério do Planejamento e Orçamento",
    ]


@dataclass
class ConfigINLABS:
    secoes: list[str] = field(default_factory=lambda: ["DO1"])
    orgaos: list[str] = field(default_factory=_orgaos_inlabs_padrao)
    # 2º nível exigido para capturar atos da "Presidência da República": o
    # INLABS publica a Casa Civil como subunidade dela, não como órgão à parte.
    subunidades_extra: list[str] = field(default_factory=lambda: ["Casa Civil"])


@dataclass
class Config:
    timezone: str = "America/Sao_Paulo"
    dou: ConfigDOU = field(default_factory=ConfigDOU)
    iofmg: ConfigIOFMG = field(default_factory=ConfigIOFMG)
    inlabs: ConfigINLABS = field(default_factory=ConfigINLABS)
    dir_dados: Path = Path("./data")
    reter_bruto_dias: int = 30
    email: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def carregar(cls, caminho: str | Path) -> Config:
        caminho = Path(caminho)
        if not caminho.exists():
            raise FileNotFoundError(f"Config não encontrado: {caminho}")
        bruto = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
        fontes = bruto.get("fontes", {})
        armazenamento = bruto.get("armazenamento", {})
        dou = fontes.get("dou", {}) or {}
        if "orgao" in dou and "orgaos" in dou:
            # Aviso, não erro: o YAML antigo continua carregando. Mas silêncio
            # aqui esconderia metade do escopo de quem editou a chave errada.
            configurar_log().warning(
                "config: `fontes.dou.orgao` está obsoleto e foi ignorado porque "
                "`fontes.dou.orgaos` também está definido (%s).",
                ", ".join(dou["orgaos"] or []),
            )
        return cls(
            timezone=bruto.get("timezone", "America/Sao_Paulo"),
            dou=ConfigDOU(**dou),
            iofmg=ConfigIOFMG(**fontes.get("iofmg", {})),
            inlabs=ConfigINLABS(**fontes.get("inlabs", {})),
            dir_dados=Path(armazenamento.get("dir_dados", "./data")),
            reter_bruto_dias=int(armazenamento.get("reter_bruto_dias", 30)),
            email=bruto.get("email", {}),
        )
