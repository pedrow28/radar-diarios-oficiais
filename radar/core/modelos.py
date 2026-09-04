"""Modelo de dado comum às duas fontes."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from radar.core.erros import Status

SCHEMA_VERSAO = "1.0"


def gerar_id(fonte: str, data_publicacao: date, url: str, titulo: str) -> str:
    """Identificador estável de uma publicação.

    Estável entre execuções, para que reprocessar um dia faça UPSERT em vez de
    duplicar, e para que o agente possa marcar o que já processou.
    """
    semente = f"{fonte}|{data_publicacao.isoformat()}|{url}|{titulo}"
    return hashlib.sha256(semente.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Publicacao:
    id: str
    fonte: Literal["dou", "iofmg"]
    data_publicacao: date
    coletado_em: datetime

    orgao: str
    unidade: str | None
    secao: str | None
    pagina: int | None
    edicao: str | None

    tipo: str | None
    numero: str | None
    titulo: str
    ementa: str | None
    texto: str
    url: str

    origem: dict[str, Any] = field(default_factory=dict)

    def para_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["data_publicacao"] = self.data_publicacao.isoformat()
        d["coletado_em"] = _iso_utc(self.coletado_em)
        return d


@dataclass
class Resultado:
    fonte: str
    data_publicacao: date
    coletado_em: datetime
    status: Status
    escopo: dict[str, Any]
    publicacoes: list[Publicacao] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def para_dict(self) -> dict[str, Any]:
        return {
            "schema_versao": SCHEMA_VERSAO,
            "fonte": self.fonte,
            "data_publicacao": self.data_publicacao.isoformat(),
            "coletado_em": _iso_utc(self.coletado_em),
            "status": str(self.status),
            "escopo": self.escopo,
            "total": len(self.publicacoes),
            "avisos": self.avisos,
            "publicacoes": [p.para_dict() for p in self.publicacoes],
        }


def _iso_utc(momento: datetime) -> str:
    """Serializa em ISO-8601 com sufixo Z, sem microssegundos."""
    return momento.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
