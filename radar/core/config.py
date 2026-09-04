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


@dataclass
class Config:
    timezone: str = "America/Sao_Paulo"
    dou: ConfigDOU = field(default_factory=ConfigDOU)
    iofmg: ConfigIOFMG = field(default_factory=ConfigIOFMG)
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
            dir_dados=Path(armazenamento.get("dir_dados", "./data")),
            reter_bruto_dias=int(armazenamento.get("reter_bruto_dias", 30)),
            email=bruto.get("email", {}),
        )
