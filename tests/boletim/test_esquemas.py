import json

import pytest

from boletim.esquemas import (
    EDITORIAL_SCHEMA,
    ITEM_SCHEMA,
    LOTE_SCHEMA,
    reparar,
    validar,
)


def _item(**kw) -> dict:
    base = {
        "id": "abc123",
        "categoria": "A",
        "relevancia": 3,
        "resumo": "resumo curto",
        "por_que_importa": None,
        "valor_brl": None,
        "entes": [],
        "tags": [],
    }
    base.update(kw)
    return base


# ── reparar ─────────────────────────────────────────────────────────────
def test_reparar_remove_cerca_json():
    assert reparar('```json\n{"itens": []}\n```') == {"itens": []}


def test_reparar_remove_cerca_sem_linguagem():
    assert reparar('```\n{"a": 1}\n```') == {"a": 1}


def test_reparar_ignora_texto_antes_e_depois():
    bruto = 'Claro, aqui está:\n{"a": 1, "b": [2, 3]}\nEspero ter ajudado.'
    assert reparar(bruto) == {"a": 1, "b": [2, 3]}


def test_reparar_aceita_lista_no_topo():
    assert reparar('resposta: [{"a": 1}] fim') == [{"a": 1}]


def test_reparar_sem_json_algum_levanta_value_error():
    with pytest.raises(ValueError):
        reparar("desculpe, não consigo responder")


def test_reparar_json_quebrado_levanta_value_error():
    with pytest.raises(ValueError):
        reparar('{"a": 1,,}')


# ── validar: type ───────────────────────────────────────────────────────
def test_validar_aceita_item_correto():
    assert validar(_item(), ITEM_SCHEMA) == []


def test_validar_recusa_tipo_errado_no_campo():
    erros = validar(_item(resumo=42), ITEM_SCHEMA)
    assert len(erros) == 1
    assert "resumo" in erros[0]


def test_validar_aceita_uniao_de_tipos_com_null():
    assert validar(_item(valor_brl=1500.0), ITEM_SCHEMA) == []
    assert validar(_item(valor_brl=None), ITEM_SCHEMA) == []
    assert validar(_item(valor_brl="1500"), ITEM_SCHEMA) != []


def test_validar_nao_aceita_booleano_como_inteiro():
    assert validar(_item(relevancia=True), ITEM_SCHEMA) != []


def test_validar_aceita_inteiro_onde_pede_number():
    assert validar(_item(valor_brl=1500), ITEM_SCHEMA) == []


# ── validar: enum, required, additionalProperties ───────────────────────
def test_validar_recusa_categoria_fora_do_enum():
    erros = validar(_item(categoria="E"), ITEM_SCHEMA)
    assert len(erros) == 1
    assert "categoria" in erros[0]


def test_validar_acusa_campo_obrigatorio_ausente():
    incompleto = _item()
    del incompleto["resumo"]
    erros = validar(incompleto, ITEM_SCHEMA)
    assert len(erros) == 1
    assert "resumo" in erros[0]


def test_validar_recusa_campo_nao_previsto():
    erros = validar(_item(comentario="oi"), ITEM_SCHEMA)
    assert len(erros) == 1
    assert "comentario" in erros[0]


# ── validar: minimum/maximum, minItems/maxItems, items ──────────────────
def test_validar_respeita_o_minimo_da_relevancia():
    assert validar(_item(relevancia=0), ITEM_SCHEMA) == []
    assert validar(_item(relevancia=-1), ITEM_SCHEMA) != []


def test_validar_respeita_o_maximo_da_relevancia():
    assert validar(_item(relevancia=3), ITEM_SCHEMA) == []
    assert validar(_item(relevancia=4), ITEM_SCHEMA) != []


def test_validar_respeita_min_items_do_editorial():
    tres = {"titulo": "t", "em_30_segundos": ["a", "b", "c"], "intro": "i"}
    assert validar(tres, EDITORIAL_SCHEMA) == []
    dois = {"titulo": "t", "em_30_segundos": ["a", "b"], "intro": "i"}
    assert validar(dois, EDITORIAL_SCHEMA) != []


def test_validar_respeita_max_items_do_editorial():
    cinco = {"titulo": "t", "em_30_segundos": list("abcde"), "intro": "i"}
    assert validar(cinco, EDITORIAL_SCHEMA) == []
    seis = {"titulo": "t", "em_30_segundos": list("abcdef"), "intro": "i"}
    assert validar(seis, EDITORIAL_SCHEMA) != []


def test_validar_desce_nos_itens_do_array():
    erros = validar(_item(entes=["Manhuaçu", 7]), ITEM_SCHEMA)
    assert len(erros) == 1
    assert "entes[1]" in erros[0]


def test_validar_recusa_objeto_onde_pede_array():
    assert validar(_item(tags={"a": 1}), ITEM_SCHEMA) != []


def test_validar_acumula_varios_erros():
    assert len(validar(_item(categoria="E", relevancia=9), ITEM_SCHEMA)) == 2


def test_validar_recusa_raiz_que_nao_e_objeto():
    assert validar([1, 2], ITEM_SCHEMA) != []


# ── LOTE_SCHEMA contra a fixture real ───────────────────────────────────
def test_lote_schema_aceita_a_fixture(dir_fixtures):
    lote = json.loads(
        (dir_fixtures / "boletim" / "llm" / "lote1.json").read_text(encoding="utf-8")
    )
    assert validar(lote, LOTE_SCHEMA) == []
    assert len(lote["itens"]) == 7


def test_lote_schema_recusa_categoria_invalida():
    erros = validar({"itens": [_item(categoria="E")]}, LOTE_SCHEMA)
    assert len(erros) == 1
    assert "itens[0].categoria" in erros[0]


def test_lote_schema_exige_a_chave_itens():
    assert validar({}, LOTE_SCHEMA) != []


def test_editorial_schema_aceita_a_fixture(dir_fixtures):
    editorial = json.loads(
        (dir_fixtures / "boletim" / "llm" / "editorial.json").read_text(encoding="utf-8")
    )
    assert validar(editorial, EDITORIAL_SCHEMA) == []
