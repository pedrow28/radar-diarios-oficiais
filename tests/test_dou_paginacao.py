import json
from pathlib import Path

from radar.fontes.dou.busca import ID_BLOCO_JSON, decodificar_busca, percorrer_paginas


def _pagina(itens: list[dict], total: int) -> str:
    bloco = json.dumps({"jsonArray": itens})
    return (
        f"<html><p>{total} resultados</p>"
        f'<script id="{ID_BLOCO_JSON}" type="application/json">{bloco}</script>'
        f"</html>"
    )


def _itens(inicio: int, quantos: int) -> list[dict]:
    return [
        {"urlTitle": f"ato-{i}", "title": f"Ato {i}", "classPK": str(i),
         "score": 0, "displayDateSortable": 1788490800000}
        for i in range(inicio, inicio + quantos)
    ]


def test_percorre_todas_as_paginas_ate_o_total():
    paginas = {1: _pagina(_itens(0, 3), 5), 2: _pagina(_itens(3, 2), 5)}
    itens, avisos = percorrer_paginas(lambda n, c: paginas[n], delta=3)
    assert len(itens) == 5
    assert avisos == []


def test_cursor_da_pagina_anterior_e_repassado():
    """Sem o cursor a busca do DOU nunca avanca de pagina."""
    recebidos: list = []

    def buscar(n, cursor):
        recebidos.append(cursor)
        return _pagina(_itens((n - 1) * 3, 3), 6)

    percorrer_paginas(buscar, delta=3)
    assert recebidos[0] is None, "a primeira página não tem cursor"
    assert recebidos[1] is not None
    assert recebidos[1].id == "2", "cursor deve vir do último item da página 1"


def test_deduplica_por_url_title():
    """Item repetido na borda de duas paginas conta uma vez so."""
    paginas = {1: _pagina(_itens(0, 3), 4), 2: _pagina(_itens(2, 2), 4)}
    itens, _ = percorrer_paginas(lambda n, c: paginas[n], delta=3)
    assert len(itens) == 4
    assert len({i["urlTitle"] for i in itens}) == 4


def test_para_por_unicos_e_nao_por_posicao_bruta():
    """Regressao: contar posicao bruta em vez de unicos descarta item real.

    Paginas 1 e 2 se sobrepoem no item 2. Somando posicoes, 3+3 ja atinge o
    total 5 e o corte por posicao jogaria fora o item 4.
    """
    paginas = {1: _pagina(_itens(0, 3), 5), 2: _pagina(_itens(2, 3), 5)}
    itens, avisos = percorrer_paginas(lambda n, c: paginas[n], delta=3)
    assert len({i["urlTitle"] for i in itens}) == 5
    assert avisos == []


def test_pagina_repetida_interrompe_e_avisa_em_vez_de_mentir_sucesso():
    """O bug atual: pagina que nao avanca inflava o contador ate 'completo'."""
    repetida = _pagina(_itens(0, 3), 9)
    itens, avisos = percorrer_paginas(lambda n, c: repetida, delta=3)
    assert len(itens) == 3
    assert avisos, "paginação travada precisa gerar aviso"
    assert "repet" in avisos[0].lower() or "trav" in avisos[0].lower()


def test_avisa_quando_coletou_menos_que_o_total():
    paginas = {1: _pagina(_itens(0, 3), 10), 2: _pagina([], 10)}
    itens, avisos = percorrer_paginas(lambda n, c: paginas[n], delta=3)
    assert len(itens) == 3
    assert any("10" in a for a in avisos)


def test_pagina_vazia_encerra_sem_erro():
    paginas = {1: _pagina(_itens(0, 2), 2), 2: _pagina([], 2)}
    itens, avisos = percorrer_paginas(lambda n, c: paginas[n], delta=2)
    assert len(itens) == 2
    assert avisos == []


def test_sem_resultados_devolve_lista_vazia():
    itens, avisos = percorrer_paginas(lambda n, c: _pagina([], 0), delta=75)
    assert itens == []
    assert avisos == []


def test_teto_de_paginas_deriva_do_total_nao_de_constante():
    """Com 800 resultados e delta 75 sao 11 paginas; o limite antigo travava em 10."""
    chamadas: list[int] = []

    def buscar(n, cursor):
        chamadas.append(n)
        inicio = (n - 1) * 75
        return _pagina(_itens(inicio, min(75, 800 - inicio)), 800)

    itens, _ = percorrer_paginas(buscar, delta=75)
    assert len(itens) == 800
    assert max(chamadas) >= 11


def test_edicao_real_percorre_as_duas_paginas(dir_fixtures: Path):
    """Fixtures reais de 03/09/2026: 75 + 43 = 118, o total informado pela busca."""
    paginas = {
        1: decodificar_busca((dir_fixtures / "dou" / "busca-ms-2026-09-03-p1.html").read_bytes()),
        2: decodificar_busca((dir_fixtures / "dou" / "busca-ms-2026-09-03-p2.html").read_bytes()),
    }
    itens, avisos = percorrer_paginas(lambda n, c: paginas[n], delta=75)
    assert len(itens) == 118
    assert avisos == []
    assert len({i["urlTitle"] for i in itens}) == 118, "não pode haver duplicata"
    assert {i["pubName"] for i in itens} == {"DO1", "DO2", "DO3"}
