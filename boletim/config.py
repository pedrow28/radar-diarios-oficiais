"""Configuração do boletim. Comportamento no YAML, segredo no ambiente."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import quote

import yaml


@dataclass
class ConfigCTA:
    whatsapp: str = "5531984483183"
    texto_botao: str = "Falar com a Thauma sobre IA para o SUS"
    mensagem: str = (
        "Olá, vi o Radar de captação de {data} e quero conversar sobre "
        "soluções de IA para saúde"
    )

    def url(self, data: date) -> str:
        """Link `wa.me` com a mensagem pronta, já codificada para URL."""
        texto = self.mensagem.format(data=data.strftime("%d/%m/%Y"))
        return f"https://wa.me/{self.whatsapp}?text={quote(texto, safe='')}"


@dataclass
class ConfigBoletim:
    modelo: str = "claude-haiku-4-5"
    lote: int = 12
    max_chars_texto: int = 3000
    max_itens_dia: int = 120
    tentativas_llm: int = 2
    timeout_llm_s: int = 180
    site_url: str = "https://pedrow28.github.io/radar-diarios-oficiais"
    cta: ConfigCTA = field(default_factory=ConfigCTA)
    fontes: list[str] = field(default_factory=lambda: ["inlabs", "iofmg"])
    dir_saida: Path = Path("./boletim/saida")
    dir_site: Path = Path("./site")
    dir_dados: Path = Path("./data")

    @classmethod
    def carregar(cls, caminho: str | Path) -> ConfigBoletim:
        caminho = Path(caminho)
        if not caminho.exists():
            raise FileNotFoundError(f"Config não encontrado: {caminho}")
        bruto = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
        bloco = bruto.get("boletim", {})
        # `dir_dados` é do topo do YAML: mesma chave que `radar.core.config.Config` usa.
        armazenamento = bruto.get("armazenamento", {})
        return cls(
            modelo=bloco.get("modelo", "claude-haiku-4-5"),
            lote=int(bloco.get("lote", 12)),
            max_chars_texto=int(bloco.get("max_chars_texto", 3000)),
            max_itens_dia=int(bloco.get("max_itens_dia", 120)),
            tentativas_llm=int(bloco.get("tentativas_llm", 2)),
            timeout_llm_s=int(bloco.get("timeout_llm_s", 180)),
            site_url=bloco.get("site_url", "https://pedrow28.github.io/radar-diarios-oficiais"),
            cta=ConfigCTA(**bloco.get("cta", {})),
            fontes=bloco.get("fontes", ["inlabs", "iofmg"]),
            dir_saida=Path(bloco.get("dir_saida", "./boletim/saida")),
            dir_site=Path(bloco.get("dir_site", "./site")),
            dir_dados=Path(armazenamento.get("dir_dados", "./data")),
        )
