"""Gera os dois logos do e-mail a partir dos PNGs oficiais da marca.

Os originais têm ~3600px de largura e não entram no repositório: um e-mail que
carrega 50 KB de logo por envio paga isso em toda entrega, e a versão de 560px
já cobre o dobro da largura de exibição (140px) em tela retina.

O script fica fora do caminho do runtime e usa Pillow, que existe no Python do
sistema e por isso não entra nas dependências do projeto.

Uso:
    python boletim/assets/gerar_logos.py --origem <pasta com os PNGs oficiais>

A pasta de origem precisa conter `logo-navy-trim.png` e `logo-branco-trim.png`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

LARGURA = 560
DESTINO = Path(__file__).parent
ORIGENS = {"logo-navy.png": "logo-navy-trim.png", "logo-branco.png": "logo-branco-trim.png"}


def gerar(origem: Path) -> list[Path]:
    """Redimensiona cada logo para `LARGURA` e grava em `boletim/assets/`."""
    gerados: list[Path] = []
    for saida, entrada in ORIGENS.items():
        caminho = origem / entrada
        if not caminho.exists():
            raise FileNotFoundError(f"Logo de origem não encontrado: {caminho}")
        with Image.open(caminho) as imagem:
            # RGBA sempre: o logo é usado sobre `#FFFFFF` no claro e sobre o
            # fundo invertido do cliente no escuro, e um fundo branco chapado
            # apareceria como um retângulo no modo escuro.
            rgba = imagem.convert("RGBA")
            altura = round(rgba.height * LARGURA / rgba.width)
            reduzido = rgba.resize((LARGURA, altura), Image.LANCZOS)
        destino = DESTINO / saida
        reduzido.save(destino, format="PNG", optimize=True)
        gerados.append(destino)
    return gerados


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--origem",
        type=Path,
        required=True,
        help="pasta com logo-navy-trim.png e logo-branco-trim.png",
    )
    for caminho in gerar(parser.parse_args().origem):
        print(f"{caminho}: {caminho.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
