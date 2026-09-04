from pathlib import Path

import pytest

from radar.fontes.iofmg.pdf import texto_das_paginas
from radar.fontes.iofmg.segmenta import Bruto, segmentar

TIPOS = ["PORTARIA", "RESOLUÇÃO", "DECRETO", "DELIBERAÇÃO", "EXTRATO", "EDITAL", "ATO", "AVISO"]


@pytest.fixture
def paginas_03(dir_fixtures: Path):
    pdf = (dir_fixtures / "iofmg" / "caderno-2026-09-03-ses.pdf").read_bytes()
    return texto_das_paginas(pdf, 1, 2)


@pytest.fixture
def paginas_02(dir_fixtures: Path):
    pdf = (dir_fixtures / "iofmg" / "caderno-2026-09-02-ses.pdf").read_bytes()
    return texto_das_paginas(pdf, 1, 3)


def test_cabecalho_exige_numero_ou_data():
    paginas = [(1, "RESOLUÇÃO SES Nº 11.606, 02 DE SETEMBRO DE 2026.\nO Secretário resolve...")]
    achados = segmentar(paginas, TIPOS)
    assert len(achados) == 1
    assert achados[0].tipo == "RESOLUÇÃO"
    assert achados[0].numero == "11.606"


def test_rejeita_delibera_dois_pontos():
    """Falso positivo real medido na sondagem."""
    paginas = [(1, "Considerando a necessidade,\nDELIBERA:\nArt. 1º Fica aprovado.")]
    assert segmentar(paginas, TIPOS) == []


def test_rejeita_mencao_em_meio_de_frase():
    """Outro falso positivo real: 'Resolucoes que menciona.'"""
    paginas = [(1, "Altera as Resoluções que menciona.\nOutro texto qualquer.")]
    assert segmentar(paginas, TIPOS) == []


def test_captura_deliberacao_cib_sus():
    """Tipo ausente da regex do script antigo e central para captacao."""
    paginas = [(1, "DELIBERAÇÃO CIB-SUS/MG Nº 5.953, DE 1 DE SETEMBRO DE 2026\nAprova recurso.")]
    achados = segmentar(paginas, TIPOS)
    assert len(achados) == 1
    assert achados[0].tipo == "DELIBERAÇÃO"
    assert "CIB-SUS" in achados[0].titulo


def test_tipos_nao_configurados_sao_ignorados():
    paginas = [(1, "PORTARIA Nº 35, DE 25 DE AGOSTO DE 2026\nAltera algo.")]
    assert segmentar(paginas, ["RESOLUÇÃO"]) == []


def test_texto_vai_ate_o_proximo_cabecalho():
    paginas = [(
        1,
        "PORTARIA Nº 1, DE 1 DE SETEMBRO DE 2026\nPrimeiro conteudo.\n"
        "PORTARIA Nº 2, DE 2 DE SETEMBRO DE 2026\nSegundo conteudo.",
    )]
    achados = segmentar(paginas, TIPOS)
    assert len(achados) == 2
    assert "Primeiro conteudo" in achados[0].texto
    assert "Segundo conteudo" not in achados[0].texto
    assert "Segundo conteudo" in achados[1].texto


def test_registra_a_pagina_de_origem():
    paginas = [(16, "PORTARIA Nº 1, DE 1 DE SETEMBRO DE 2026\nConteudo.")]
    assert segmentar(paginas, TIPOS)[0].pagina == 16


def test_texto_nunca_e_vazio():
    paginas = [(1, "PORTARIA Nº 1, DE 1 DE SETEMBRO DE 2026\nConteudo relevante aqui.")]
    for bruto in segmentar(paginas, TIPOS):
        assert bruto.texto.strip()


def test_edicao_real_03_produz_publicacoes(paginas_03):
    achados = segmentar(paginas_03, TIPOS)
    assert len(achados) >= 5, f"segmentou apenas {len(achados)}"
    assert all(isinstance(a, Bruto) for a in achados)


def test_edicao_real_02_produz_publicacoes(paginas_02):
    achados = segmentar(paginas_02, TIPOS)
    assert len(achados) >= 5, f"segmentou apenas {len(achados)}"


def test_numero_completo_em_deliberacao_cib_sus(paginas_02):
    """Numero truncado e numero ERRADO: 4 deliberacoes distintas viram todas "5"."""
    cib = [a for a in segmentar(paginas_02, TIPOS) if "CIB-SUS" in a.titulo]
    assert cib, "as deliberacoes CIB-SUS precisam ser segmentadas"
    assert all(a.numero and "." in a.numero for a in cib), [a.numero for a in cib]
    assert len({a.numero for a in cib}) == len(cib), "os numeros devem ser distintos"


def test_edicao_real_nao_gera_falsos_positivos_conhecidos(paginas_02):
    titulos = [a.titulo.upper() for a in segmentar(paginas_02, TIPOS)]
    assert not any(t.startswith("DELIBERA:") for t in titulos)
    assert not any(t.startswith("DELIBERAÇÃO, CABERÁ") for t in titulos)


def test_maioria_dos_segmentos_tem_numero(paginas_02):
    """Proxy de qualidade: cabecalho de verdade quase sempre traz numero."""
    achados = segmentar(paginas_02, TIPOS)
    com_numero = [a for a in achados if a.numero]
    assert len(com_numero) / len(achados) >= 0.6


def test_segmentos_nao_se_sobrepoem(paginas_03):
    achados = segmentar(paginas_03, TIPOS)
    for anterior, seguinte in zip(achados, achados[1:]):
        assert seguinte.titulo not in anterior.texto


# ── C1: o token de tipo só casa em CAIXA ALTA ───────────────────────────────


def _producao(dir_fixtures: Path, dia: str, npaginas: int):
    """Páginas como o coletor as entrega ao segmentador: as duas pontas cortadas."""
    from radar.fontes.iofmg.pdf import truncar_antes_da_secao, truncar_na_proxima_secao

    pdf = (dir_fixtures / "iofmg" / f"caderno-{dia}-ses.pdf").read_bytes()
    paginas = texto_das_paginas(pdf, 1, npaginas)
    paginas = truncar_antes_da_secao(paginas, "Secretaria de Estado de Saúde")
    return truncar_na_proxima_secao(paginas, "Secretaria de Estado de Educação")


def test_citacao_em_caixa_mista_nao_vira_cabecalho():
    """A quebra de linha do PDF põe a citação no começo da linha; não é ato novo."""
    paginas = [(
        1,
        "RESOLUÇÃO SES Nº 11.606, 02 DE SETEMBRO DE 2026.\n"
        "Ficam mantidos os demais artigos e anexos dispostos na\n"
        "Resolução SES nº 8.994/2023, nº 8.686/2023 e nº 8.687/2023.\n"
        "Fábio Baccheretti Vitor, Secretário.",
    )]
    achados = segmentar(paginas, TIPOS)
    assert len(achados) == 1, [a.titulo for a in achados]
    assert achados[0].numero == "11.606"
    # O inteiro teor do ato de verdade não pode parar na citação.
    assert "Fábio Baccheretti Vitor" in achados[0].texto


def test_deliberacao_citada_em_caixa_mista_nao_vira_publicacao():
    paginas = [(
        1,
        "DELIBERAÇÃO CIB-SUS/MG Nº 5.956, DE 1 DE SETEMBRO DE 2026\n"
        "Aprova a alteração do inciso VII do art. 1º da\n"
        "Deliberação CIB-SUS/MG nº 5.696, de 09 de abril de 2026, que aprova\n"
        "o repasse de recurso.",
    )]
    achados = segmentar(paginas, TIPOS)
    assert [a.numero for a in achados] == ["5.956"]


def test_tipo_em_caixa_mista_no_inicio_da_linha_e_ignorado():
    paginas = [(1, "Portaria Presidencial nº 3.591, de 30 de julho de 2026.\nConteudo.")]
    assert segmentar(paginas, TIPOS) == []


def test_edicao_real_03_sem_publicacao_inventada(dir_fixtures: Path):
    """Medido: 5 segmentos antes da correção, 4 depois; o extra não existia."""
    achados = segmentar(_producao(dir_fixtures, "2026-09-03", 2), TIPOS)
    assert len(achados) == 4, [a.titulo for a in achados]
    assert not any("8.994" in a.titulo for a in achados)
    resolucao = [a for a in achados if a.numero == "11.606"][0]
    # Antes da correção o inteiro teor terminava em "...dispostos na".
    assert not resolucao.texto.rstrip().endswith("dispostos na")
    assert "8.994" in resolucao.texto, "a citação pertence ao corpo da 11.606"


def test_edicao_real_02_sem_publicacao_inventada(dir_fixtures: Path):
    """Medido: 16 segmentos antes; 13 depois de C1 e C2."""
    achados = segmentar(_producao(dir_fixtures, "2026-09-02", 3), TIPOS)
    assert len(achados) == 13, [a.titulo for a in achados]
    titulos = [a.titulo for a in achados]
    assert not any("5.696" in t for t in titulos)
    assert not any(t.startswith("Portaria") for t in titulos)


def test_todo_titulo_comeca_em_caixa_alta(dir_fixtures: Path):
    """Invariante da §7.4: cabeçalho de ato é caixa alta, sempre."""
    for dia, npaginas in (("2026-09-02", 3), ("2026-09-03", 2)):
        for achado in segmentar(_producao(dir_fixtures, dia, npaginas), TIPOS):
            primeira = achado.titulo.split()[0]
            assert primeira == primeira.upper(), achado.titulo
