import json
from pathlib import Path

import pytest

from radar.core.erros import SemEdicao
from radar.fontes.iofmg.pdf import intervalo_da_secao, limpar, texto_das_paginas

CADERNO = {
    "id": 330896,
    "descricao": "Diário do Executivo",
    "secoes": [
        {"descricao": "Governo do Estado", "paginaInicial": 1},
        {"descricao": "Secretaria de Estado de Saúde", "paginaInicial": 16},
        {"descricao": "Secretaria de Estado de Educação", "paginaInicial": 17},
        {"descricao": "Editais e Avisos", "paginaInicial": 23},
    ],
}


def test_intervalo_vai_ate_a_proxima_secao():
    assert intervalo_da_secao(CADERNO, "Secretaria de Estado de Saúde", 53) == (16, 17)


def test_ultima_secao_vai_ate_o_fim_do_caderno():
    assert intervalo_da_secao(CADERNO, "Editais e Avisos", 53) == (23, 53)


def test_secoes_fora_de_ordem_sao_ordenadas():
    embaralhado = {"secoes": list(reversed(CADERNO["secoes"]))}
    assert intervalo_da_secao(embaralhado, "Secretaria de Estado de Saúde", 53) == (16, 17)


def test_secao_ausente_levanta_sem_edicao():
    with pytest.raises(SemEdicao):
        intervalo_da_secao(CADERNO, "Secretaria de Estado de Turismo", 53)


def test_secao_ausente_lista_as_disponiveis_na_mensagem():
    with pytest.raises(SemEdicao) as exc:
        intervalo_da_secao(CADERNO, "Inexistente", 53)
    assert "Governo do Estado" in str(exc.value)


def test_extrai_texto_das_paginas_reais(dir_fixtures: Path):
    """A fixture ja vem recortada nas paginas da SES-MG."""
    pdf = (dir_fixtures / "iofmg" / "caderno-2026-09-03-ses.pdf").read_bytes()
    paginas = texto_das_paginas(pdf, 1, 2)
    assert len(paginas) == 2
    assert all(isinstance(n, int) and isinstance(t, str) for n, t in paginas)
    assert sum(len(t) for _, t in paginas) > 10_000


def test_texto_contem_normativas_da_ses(dir_fixtures: Path):
    pdf = (dir_fixtures / "iofmg" / "caderno-2026-09-03-ses.pdf").read_bytes()
    tudo = "\n".join(t for _, t in texto_das_paginas(pdf, 1, 2))
    assert "RESOLUÇÃO SES" in tudo.upper()


def test_intervalo_alem_do_total_nao_estoura(dir_fixtures: Path):
    pdf = (dir_fixtures / "iofmg" / "caderno-2026-09-03-ses.pdf").read_bytes()
    assert len(texto_das_paginas(pdf, 1, 999)) == 2


def test_limpar_remove_cabecalho_recorrente():
    sujo = "MINAS GERAIS \tDiário do Executivo\t\n16 – quinta-feira, 03 DE Setembro DE 2026\nPORTARIA Nº 1"
    assert "PORTARIA Nº 1" in limpar(sujo)
    assert "Diário do Executivo" not in limpar(sujo)


def test_limpar_junta_palavra_hifenizada_na_quebra():
    assert "delegação" in limpar("dispõe sobre a delega-\nção de competência")


def test_limpar_preserva_hifen_legitimo():
    assert "CIB-SUS" in limpar("DELIBERAÇÃO CIB-SUS/MG Nº 5.953")


def test_limpar_refaz_separador_de_milhar_quebrado():
    """A extracao do PDF insere espaco depois do ponto de milhar."""
    assert "5.953" in limpar("DELIBERAÇÃO CIB-SUS/MG Nº 5. 953, DE 1 DE SETEMBRO")
    assert "R$ 168.895.626,43" in limpar("valor total anual de R$ 168. 895. 626,43")
    assert "1.130.647-9" in limpar("MASP 1. 130. 647-9")


def test_limpar_nao_junta_quando_nao_ha_tres_digitos():
    """So o padrao de milhar (exatamente 3 digitos) e normalizado."""
    assert limpar("no exercício de 2025. 30 servidores") == "no exercício de 2025. 30 servidores"


def test_limpar_nao_apaga_o_nome_do_estado_dentro_do_ato():
    """Regressao: sem ancora de linha, o nome das entidades e mutilado.

    "MINAS GERAIS" aparece 27 vezes dentro do corpo dos atos nas edicoes reais.
    """
    sujo = (
        "MINAS GERAIS \t\n"
        "Diário do Executivo\t\n"
        "A PRESIDENTE DA FUNDAÇÃO HOSPITALAR DO ESTADO DE MINAS GERAIS - FHEMIG resolve:\n"
    )
    limpo = limpar(sujo)
    assert "FUNDAÇÃO HOSPITALAR DO ESTADO DE MINAS GERAIS - FHEMIG" in limpo
    assert limpo.count("MINAS GERAIS") == 1, "só a ocorrência do corpo deve sobrar"
    assert "Diário do Executivo" not in limpo


def test_proxima_secao_e_a_seguinte_por_pagina():
    from radar.fontes.iofmg.pdf import proxima_secao

    assert proxima_secao(CADERNO, "Secretaria de Estado de Saúde") == (
        "Secretaria de Estado de Educação"
    )


def test_proxima_secao_da_ultima_e_none():
    from radar.fontes.iofmg.pdf import proxima_secao

    assert proxima_secao(CADERNO, "Editais e Avisos") is None


def test_trunca_pagina_de_fronteira_no_cabecalho_seguinte():
    """A ultima pagina traz o fim da secao alvo E o inicio da proxima."""
    from radar.fontes.iofmg.pdf import truncar_na_proxima_secao

    paginas = [
        (16, "PORTARIA SES Nº 1\nConteudo da saude."),
        (17, "Fim da saude.\nSecretaria de Estado de Educação\nPORTARIA SEE Nº 9\nConteudo da educacao."),
    ]
    cortadas = truncar_na_proxima_secao(paginas, "Secretaria de Estado de Educação")
    assert "Fim da saude." in cortadas[1][1]
    assert "PORTARIA SEE" not in cortadas[1][1]
    assert "Conteudo da educacao" not in cortadas[1][1]


def test_truncar_sem_proxima_secao_nao_altera_nada():
    from radar.fontes.iofmg.pdf import truncar_na_proxima_secao

    paginas = [(23, "EDITAL Nº 1\nConteudo.")]
    assert truncar_na_proxima_secao(paginas, None) == paginas


def test_truncar_ignora_paginas_que_nao_a_ultima():
    from radar.fontes.iofmg.pdf import truncar_na_proxima_secao

    paginas = [
        (16, "Secretaria de Estado de Educação mencionada de passagem.\nPORTARIA SES Nº 1"),
        (17, "Conteudo final."),
    ]
    cortadas = truncar_na_proxima_secao(paginas, "Secretaria de Estado de Educação")
    assert cortadas[0][1] == paginas[0][1], "só a última página é truncada"


# ── C2: a primeira página também é fronteira ────────────────────────────────


def test_truncar_antes_corta_o_orgao_anterior():
    from radar.fontes.iofmg.pdf import truncar_antes_da_secao

    paginas = [
        (47, "PORTARIA IPSEMG Nº 35\nConteudo do ipsemg.\nSecretaria de Estado de Saúde\nPORTARIA SES Nº 1"),
        (48, "Conteudo da saude."),
    ]
    cortadas = truncar_antes_da_secao(paginas, "Secretaria de Estado de Saúde")
    assert "PORTARIA IPSEMG" not in cortadas[0][1]
    assert cortadas[0][1].startswith("Secretaria de Estado de Saúde")
    assert "PORTARIA SES Nº 1" in cortadas[0][1]


def test_truncar_antes_so_mexe_na_primeira_pagina():
    from radar.fontes.iofmg.pdf import truncar_antes_da_secao

    paginas = [
        (47, "Secretaria de Estado de Saúde\nPORTARIA SES Nº 1"),
        (48, "Lixo antes\nSecretaria de Estado de Saúde\nDepois"),
    ]
    cortadas = truncar_antes_da_secao(paginas, "Secretaria de Estado de Saúde")
    assert cortadas[1][1] == paginas[1][1], "só a primeira página é truncada"


def test_truncar_antes_sem_cabecalho_nao_corta_nada():
    """Fallback seguro: perder conteúdo em silêncio é pior que a sobra."""
    from radar.fontes.iofmg.pdf import truncar_antes_da_secao

    paginas = [(47, "PORTARIA SES Nº 1\nConteudo.")]
    assert truncar_antes_da_secao(paginas, "Secretaria de Estado de Saúde") == paginas
    assert truncar_antes_da_secao(paginas, None) == paginas
    assert truncar_antes_da_secao([], "Secretaria de Estado de Saúde") == []


def test_cabecalho_quebrado_em_duas_linhas_e_encontrado():
    """A coluna estreita do PDF real parte o cabeçalho: 'Secretaria de \nEstado de Saúde'."""
    from radar.fontes.iofmg.pdf import truncar_antes_da_secao

    paginas = [(47, "Ato alheio.\nSecretaria de \nEstado de Saúde\nSecretário: Fulano\nPORTARIA Nº 1")]
    cortadas = truncar_antes_da_secao(paginas, "Secretaria de Estado de Saúde")
    assert "Ato alheio" not in cortadas[0][1]
    assert cortadas[0][1].startswith("Secretaria de")


def test_mencao_no_corpo_do_ato_nao_e_confundida_com_cabecalho():
    """Medido: a menção aparece no corpo antes do cabeçalho; um `find` cru mutila o órgão."""
    from radar.fontes.iofmg.pdf import truncar_antes_da_secao

    corpo = (
        "PORTARIA IPSEMG Nº 35\n"
        "no âmbito da Secretaria de Estado de Saúde;\n"
        "Secretaria de Estado de Saúde\n"
        "PORTARIA SES Nº 1"
    )
    cortadas = truncar_antes_da_secao([(47, corpo)], "Secretaria de Estado de Saúde")
    assert "no âmbito da" not in cortadas[0][1]
    assert "PORTARIA SES Nº 1" in cortadas[0][1]


def test_cabecalho_real_da_ses_e_localizado_na_primeira_pagina(dir_fixtures: Path):
    from radar.fontes.iofmg.pdf import posicao_do_cabecalho

    for dia, npaginas in (("2026-09-02", 3), ("2026-09-03", 2)):
        pdf = (dir_fixtures / "iofmg" / f"caderno-{dia}-ses.pdf").read_bytes()
        primeira = texto_das_paginas(pdf, 1, npaginas)[0][1]
        posicao = posicao_do_cabecalho(primeira, "Secretaria de Estado de Saúde")
        assert posicao is not None, dia
        assert 0 < posicao < len(primeira)
        assert "Secretário: Fábio Baccheretti Vitor" in primeira[posicao : posicao + 200]
