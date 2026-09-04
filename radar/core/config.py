"""Configuração da aplicação. Comportamento no YAML, segredo no ambiente."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ConfigDOU:
    orgao: str = "Ministério da Saúde"
    delta: int = 75
    concorrencia: int = 5
    baixar_texto_integral: bool = True


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
        return cls(
            timezone=bruto.get("timezone", "America/Sao_Paulo"),
            dou=ConfigDOU(**fontes.get("dou", {})),
            iofmg=ConfigIOFMG(**fontes.get("iofmg", {})),
            inlabs=ConfigINLABS(**fontes.get("inlabs", {})),
            dir_dados=Path(armazenamento.get("dir_dados", "./data")),
            reter_bruto_dias=int(armazenamento.get("reter_bruto_dias", 30)),
            email=bruto.get("email", {}),
        )
