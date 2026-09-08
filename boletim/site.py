"""Publicação da edição no site estático servido pelo GitHub Pages.

O site é o destino do "ler a versão completa" do e-mail e o arquivo público do
boletim. Duas propriedades importam mais que qualquer outra: publicar a mesma
data duas vezes substitui a entrada em vez de duplicá-la, e o índice sai sempre
de `edicoes.json`, nunca de uma varredura da pasta - o dia que a varredura
perdesse sumiria do arquivo sem ninguém notar.

O `.nojekyll` na raiz não é detalhe: sem ele o Pages roda Jekyll e ignora todo
arquivo ou pasta que comece com underscore.

`publicar` lê e mescla `edicoes.json` e renderiza o índice antes de gravar
qualquer arquivo: um `edicoes.json` corrompido ou uma ficha sem `contagens`
tem de estourar ali, não depois da página já estar no ar.
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
EXTENSOES_ASSETS = (".png", ".css", ".jpg")


def publicar(edicao: Edicao, html_web: str, cfg: ConfigBoletim) -> Path:
    """Grava a página da edição, atualiza o arquivo e regenera o índice.

    Tudo que pode falhar - ler e mesclar `edicoes.json`, renderizar o índice -
    acontece antes da primeira gravação. Um `edicoes.json` corrompido ou uma
    ficha sem `contagens` estoura aqui, com o `site/` inteiro intocado; só
    depois desse ponto é que qualquer arquivo é escrito.
    """
    dir_site = Path(cfg.dir_site)
    arquivadas = [_completar(e, cfg) for e in _ler_edicoes(dir_site)]
    entradas = _mesclar(arquivadas, _ficha(edicao))
    indice_html = _renderizar_indice(entradas, cfg)

    pagina = dir_site / PASTA_EDICOES / f"{edicao.data.isoformat()}.html"
    pagina.parent.mkdir(parents=True, exist_ok=True)
    pagina.write_text(html_web, encoding="utf-8", newline="\n")

    _gravar_edicoes(dir_site, entradas)
    _copiar_assets(dir_site)
    (dir_site / ".nojekyll").write_bytes(b"")
    _gravar_indice_html(dir_site, indice_html)
    return pagina


def reconstruir_indice(cfg: ConfigBoletim) -> Path:
    """Regera `index.html` a partir de `edicoes.json`, sem tocar nas páginas.

    Também completa as fichas antigas: `valor_dia` e `total_relevante` nasceram
    depois das primeiras edições, e um `edicoes.json` gravado antes disso não os
    tem. Reconstruir é o comando que os traz de volta, lendo o `itens.json` do
    dia - sem ele o arquivo teria que ser regerado dia a dia só para preencher
    uma coluna.
    """
    dir_site = Path(cfg.dir_site)
    arquivadas = _ler_edicoes(dir_site)
    entradas = [_completar(e, cfg) for e in arquivadas]
    indice_html = _renderizar_indice(entradas, cfg)
    # Só reescreve o arquivo se ele ficou diferente: `reconstruir` num site sem
    # edição nenhuma não pode inventar um `edicoes.json` vazio.
    if entradas != arquivadas:
        _gravar_edicoes(dir_site, entradas)
    return _gravar_indice_html(dir_site, indice_html)


def valor_dia(edicao: Edicao) -> float | None:
    """A soma das cifras dos atos de captação, ou `None` quando não há nenhuma.

    Zero e "não declarado" são coisas diferentes e a página as trata diferente:
    um dia sem cifra deixa a coluna do dinheiro vazia, e não escreve `R$ 0,00`
    em cima de atos que movimentaram dinheiro sem dizer quanto.
    """
    valores = [i.valor_brl for i in edicao.secoes.get("A", ()) if i.valor_brl]
    return sum(valores) if valores else None


def _ficha(edicao: Edicao) -> dict[str, Any]:
    """O que o índice precisa saber da edição, e só isso."""
    return {
        "data": edicao.data.isoformat(),
        "titulo": edicao.titulo,
        "url": f"{PASTA_EDICOES}/{edicao.data.isoformat()}.html",
        "contagens": {cat: len(edicao.secoes.get(cat, ())) for cat in ROTULOS},
        "parcial": edicao.parcial,
        "valor_dia": valor_dia(edicao),
        "total_relevante": edicao.total_relevante(),
    }


def _completar(entrada: dict[str, Any], cfg: ConfigBoletim) -> dict[str, Any]:
    """Preenche os campos que a ficha antiga não tinha, sem mexer no que já tem.

    `total_relevante` sai das contagens, que toda ficha sempre teve.
    `valor_dia` só existe no `itens.json` do dia; quando a pasta de saída não
    tem mais aquele dia, a entrada fica com `None` - a coluna do dinheiro vazia
    é resposta honesta, um zero seria mentira.
    """
    if "valor_dia" in entrada and "total_relevante" in entrada:
        return entrada
    contagens = entrada["contagens"]
    completa = {
        **entrada,
        "total_relevante": entrada.get(
            "total_relevante", sum(contagens.get(cat, 0) for cat in ("A", "B", "C"))
        ),
    }
    completa.setdefault("valor_dia", _valor_dia_do_disco(entrada["data"], cfg))
    return completa


def _valor_dia_do_disco(data: str, cfg: ConfigBoletim) -> float | None:
    """Recalcula `valor_dia` a partir do `itens.json` gravado pelo `gerar`."""
    arquivo = Path(cfg.dir_saida) / data / "itens.json"
    if not arquivo.exists():
        return None
    ficha = json.loads(arquivo.read_text(encoding="utf-8"))
    valores = [
        item["valor_brl"]
        for item in ficha.get("itens", ())
        if item.get("categoria") == "A" and item.get("valor_brl")
    ]
    return sum(valores) if valores else None


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


def _renderizar_indice(entradas: list[dict[str, Any]], cfg: ConfigBoletim) -> str:
    """Só renderiza, não grava: é a parte que pode falhar antes de tocar disco."""
    # A data volta a ser `date` aqui: o template a escreve por extenso, e
    # formatar data em Jinja a partir de string seria uma segunda gramática.
    para_render = [{**e, "data": date.fromisoformat(e["data"])} for e in entradas]
    return render_index(para_render, cfg)


def _gravar_indice_html(dir_site: Path, indice_html: str) -> Path:
    dir_site.mkdir(parents=True, exist_ok=True)
    caminho = dir_site / "index.html"
    caminho.write_text(indice_html, encoding="utf-8", newline="\n")
    return caminho


def _copiar_assets(dir_site: Path) -> None:
    """Copia logo, folha de estilo e imagem-tema do pacote para o site.

    O CSS anda junto dos PNGs porque o site passou a ter folha externa: uma
    página publicada com um `site.css` de duas semanas atrás seria pior que uma
    página sem estilo nenhum, porque ninguém repara. A imagem-tema entra pela
    mesma porta e é opcional - sem ela a primeira dobra fica no navy sólido,
    que é o fundo do sistema, e não um buraco.
    """
    destino = dir_site / PASTA_ASSETS
    destino.mkdir(parents=True, exist_ok=True)
    # Âncora no pacote `boletim`, e não em `boletim.assets`: a pasta de assets
    # entra na distribuição como `package_data`, não como subpacote.
    for arquivo in resources.files("boletim").joinpath(PASTA_ASSETS).iterdir():
        if arquivo.name.endswith(EXTENSOES_ASSETS):
            (destino / arquivo.name).write_bytes(arquivo.read_bytes())
