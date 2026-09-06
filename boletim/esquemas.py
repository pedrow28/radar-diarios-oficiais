"""Contrato de saída do LLM: os schemas, o conserto e a validação.

O `--json-schema` do Claude Code já obriga a forma na origem, mas confiar só
nele deixaria o boletim à mercê de uma mudança de versão do CLI: aqui a
resposta é validada de novo, do nosso lado, antes de virar `Item`.

A validação é escrita à mão de propósito. O subconjunto de JSON Schema que
estes três documentos usam cabe em cem linhas, e uma dependência a mais só
para isso encareceria o deploy na VPS sem comprar nada.
"""

from __future__ import annotations

import json
import re
from typing import Any

CATEGORIAS = ("A", "B", "C", "D", "X")

ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "categoria": {"type": "string", "enum": list(CATEGORIAS)},
        "relevancia": {"type": "integer", "minimum": 0, "maximum": 3},
        "resumo": {"type": "string"},
        "por_que_importa": {"type": ["string", "null"]},
        "valor_brl": {"type": ["number", "null"]},
        "entes": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "id",
        "categoria",
        "relevancia",
        "resumo",
        "por_que_importa",
        "valor_brl",
        "entes",
        "tags",
    ],
    "additionalProperties": False,
}

LOTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"itens": {"type": "array", "items": ITEM_SCHEMA}},
    "required": ["itens"],
    "additionalProperties": False,
}

EDITORIAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "em_30_segundos": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 5,
        },
        "intro": {"type": "string"},
    },
    "required": ["titulo", "em_30_segundos", "intro"],
    "additionalProperties": False,
}

_CERCA = re.compile(r"^\s*```[a-zA-Z]*\s*\n?|\n?\s*```\s*$")
_FECHAMENTO = {"{": "}", "[": "]"}


def reparar(texto: str) -> dict | list:
    """Extrai o JSON de uma resposta que veio embrulhada em conversa.

    Modelo instruído a devolver só JSON às vezes devolve cercas de markdown ou
    um "claro, aqui está" antes. Consertar isso é barato e evita jogar fora um
    lote inteiro por causa de três crases.
    """
    limpo = _CERCA.sub("", texto.strip()).strip()
    inicio = min(
        (p for p in (limpo.find("{"), limpo.find("[")) if p >= 0),
        default=-1,
    )
    if inicio < 0:
        raise ValueError("resposta sem JSON: nenhum '{' ou '[' encontrado")
    fim = limpo.rfind(_FECHAMENTO[limpo[inicio]])
    if fim <= inicio:
        raise ValueError("resposta com JSON truncado: fechamento não encontrado")
    try:
        return json.loads(limpo[inicio : fim + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"resposta não é JSON válido: {exc}") from exc


def validar(obj: Any, schema: dict[str, Any]) -> list[str]:
    """Erros do objeto contra o schema. Lista vazia significa válido.

    Devolve todos os erros, e não só o primeiro: quando o lote volta torto, a
    tentativa seguinte precisa saber tudo o que corrigir de uma vez.
    """
    erros: list[str] = []
    _validar(obj, schema, "", erros)
    return erros


def _validar(obj: Any, schema: dict[str, Any], caminho: str, erros: list[str]) -> None:
    onde = caminho or "raiz"
    tipos = schema.get("type")
    if tipos is not None and not _tipo_ok(obj, tipos):
        esperado = tipos if isinstance(tipos, str) else "/".join(tipos)
        erros.append(f"{onde}: esperado {esperado}, veio {_nome_do_tipo(obj)}")
        return

    if "enum" in schema and obj not in schema["enum"]:
        erros.append(f"{onde}: valor {obj!r} fora dos aceitos {schema['enum']}")

    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        minimo, maximo = schema.get("minimum"), schema.get("maximum")
        if minimo is not None and obj < minimo:
            erros.append(f"{onde}: {obj} abaixo do mínimo {minimo}")
        if maximo is not None and obj > maximo:
            erros.append(f"{onde}: {obj} acima do máximo {maximo}")

    if isinstance(obj, dict):
        _validar_objeto(obj, schema, caminho, erros)
    elif isinstance(obj, list):
        _validar_array(obj, schema, caminho, erros)


def _validar_objeto(
    obj: dict[str, Any], schema: dict[str, Any], caminho: str, erros: list[str]
) -> None:
    onde = caminho or "raiz"
    propriedades = schema.get("properties", {})
    for nome in schema.get("required", ()):
        if nome not in obj:
            erros.append(f"{onde}: campo obrigatório ausente: {nome}")
    if schema.get("additionalProperties") is False:
        for nome in obj:
            if nome not in propriedades:
                erros.append(f"{onde}: campo não previsto: {nome}")
    for nome, sub in propriedades.items():
        if nome in obj:
            _validar(obj[nome], sub, f"{caminho}.{nome}" if caminho else nome, erros)


def _validar_array(
    obj: list[Any], schema: dict[str, Any], caminho: str, erros: list[str]
) -> None:
    onde = caminho or "raiz"
    minimo, maximo = schema.get("minItems"), schema.get("maxItems")
    if minimo is not None and len(obj) < minimo:
        erros.append(f"{onde}: {len(obj)} itens, mínimo {minimo}")
    if maximo is not None and len(obj) > maximo:
        erros.append(f"{onde}: {len(obj)} itens, máximo {maximo}")
    sub = schema.get("items")
    if sub is None:
        return
    for indice, elemento in enumerate(obj):
        _validar(elemento, sub, f"{caminho}[{indice}]", erros)


def _tipo_ok(obj: Any, tipos: str | list[str]) -> bool:
    nomes = [tipos] if isinstance(tipos, str) else tipos
    return any(_do_tipo(obj, nome) for nome in nomes)


def _do_tipo(obj: Any, nome: str) -> bool:
    if nome == "null":
        return obj is None
    if nome == "string":
        return isinstance(obj, str)
    # `True` é `int` em Python, mas um booleano no lugar de `relevancia` é erro
    # de resposta, não um 1 legítimo.
    if nome == "integer":
        return isinstance(obj, int) and not isinstance(obj, bool)
    if nome == "number":
        return isinstance(obj, (int, float)) and not isinstance(obj, bool)
    if nome == "array":
        return isinstance(obj, list)
    if nome == "object":
        return isinstance(obj, dict)
    if nome == "boolean":
        return isinstance(obj, bool)
    raise ValueError(f"tipo desconhecido no schema: {nome}")


def _nome_do_tipo(obj: Any) -> str:
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "boolean"
    if isinstance(obj, str):
        return "string"
    if isinstance(obj, int):
        return "integer"
    if isinstance(obj, float):
        return "number"
    if isinstance(obj, list):
        return "array"
    if isinstance(obj, dict):
        return "object"
    return type(obj).__name__
