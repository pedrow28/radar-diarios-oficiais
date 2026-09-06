"""Publicação da edição no site estático servido pelo GitHub Pages.

O site é o destino do "ler a versão completa" do e-mail e o arquivo público do
boletim. Duas propriedades importam mais que qualquer outra: publicar a mesma
data duas vezes substitui a entrada em vez de duplicá-la, e o índice sai sempre
de `edicoes.json`, nunca de uma varredura da pasta - o dia que a varredura
perdesse sumiria do arquivo sem ninguém notar.

O `.nojekyll` na raiz não é detalhe: sem ele o Pages roda Jekyll e ignora todo
arquivo ou pasta que comece com underscore.
"""

from __future__ import annotations

import json
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any

from boletim.config import ConfigBoletim
from boletim.edicao import ROTULOS, Edicao
from boletim.render import render_index

ARQUIVO_EDICOES = "edicoes.json"
PASTA_EDICOES = "edicoes"
PASTA_ASSETS = "assets"


def publicar(edicao: Edicao, html_web: str, cfg: ConfigBoletim) -> Path:
    """Grava a página da edição, atualiza o arquivo e regenera o índice."""
    dir_site = Path(cfg.dir_site)
    pagina = dir_site / PASTA_EDICOES / f"{edicao.data.isoformat()}.html"
    pagina.parent.mkdir(parents=True, exist_ok=True)
    pagina.write_text(html_web, encoding="utf-8", newline="\n")

    entradas = _mesclar(_ler_edicoes(dir_site), _ficha(edicao))
    _gravar_edicoes(dir_site, entradas)
    _copiar_assets(dir_site)
    (dir_site / ".nojekyll").write_bytes(b"")
    _gravar_indice(dir_site, entradas, cfg)
    return pagina


def reconstruir_indice(cfg: ConfigBoletim) -> Path:
    """Regera `index.html` a partir de `edicoes.json`, sem tocar nas páginas."""
    dir_site = Path(cfg.dir_site)
    return _gravar_indice(dir_site, _ler_edicoes(dir_site), cfg)


def _ficha(edicao: Edicao) -> dict[str, Any]:
    """O que o índice precisa saber da edição, e só isso."""
    return {
        "data": edicao.data.isoformat(),
        "titulo": edicao.titulo,
        "url": f"{PASTA_EDICOES}/{edicao.data.isoformat()}.html",
        "contagens": {cat: len(edicao.secoes.get(cat, ())) for cat in ROTULOS},
        "parcial": edicao.parcial,
    }


def _ler_edicoes(dir_site: Path) -> list[dict[str, Any]]:
    arquivo = dir_site / ARQUIVO_EDICOES
    if not arquivo.exists():
        return []
    return json.loads(arquivo.read_text(encoding="utf-8"))


def _mesclar(
    entradas: list[dict[str, Any]], ficha: dict[str, Any]
) -> list[dict[str, Any]]:
    """Substitui a entrada da mesma data e devolve a lista da mais recente à mais antiga.

    Republicar um dia é o caso normal, não a exceção: o boletim é regerado
    quando uma fonte que faltou volta a responder.
    """
    restantes = [e for e in entradas if e["data"] != ficha["data"]]
    return sorted([*restantes, ficha], key=lambda e: e["data"], reverse=True)


def _gravar_edicoes(dir_site: Path, entradas: list[dict[str, Any]]) -> None:
    dir_site.mkdir(parents=True, exist_ok=True)
    (dir_site / ARQUIVO_EDICOES).write_text(
        json.dumps(entradas, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _gravar_indice(
    dir_site: Path, entradas: list[dict[str, Any]], cfg: ConfigBoletim
) -> Path:
    # A data volta a ser `date` aqui: o template a escreve por extenso, e
    # formatar data em Jinja a partir de string seria uma segunda gramática.
    para_render = [{**e, "data": date.fromisoformat(e["data"])} for e in entradas]
    dir_site.mkdir(parents=True, exist_ok=True)
    caminho = dir_site / "index.html"
    caminho.write_text(render_index(para_render, cfg), encoding="utf-8", newline="\n")
    return caminho


def _copiar_assets(dir_site: Path) -> None:
    """Copia os logos do pacote para o site, para o e-mail achá-los por URL."""
    destino = dir_site / PASTA_ASSETS
    destino.mkdir(parents=True, exist_ok=True)
    # Âncora no pacote `boletim`, e não em `boletim.assets`: a pasta de assets
    # entra na distribuição como `package_data`, não como subpacote.
    for arquivo in resources.files("boletim").joinpath(PASTA_ASSETS).iterdir():
        if arquivo.name.endswith(".png"):
            (destino / arquivo.name).write_bytes(arquivo.read_bytes())
