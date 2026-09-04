"""Acesso ao LLM. Uma porta (`LLM`) e duas implementações: o CLI e o falso.

O modelo é chamado pelo próprio Claude Code em modo `-p`, e não pela API: a
assinatura já está na máquina, não há chave de API para guardar na VPS e o
`--json-schema` obriga a forma da resposta na origem.

A chamada roda desarmada de propósito — sem ferramentas, sem MCP, sem sessão
persistida, sem herdar configuração do projeto e com teto de gasto. O que entra
é texto de diário oficial vindo da internet; se esse texto contiver instruções,
o pior que pode acontecer é uma classificação errada, nunca uma escrita em
disco ou uma chamada de rede.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any, Protocol

from boletim.esquemas import reparar
from radar.core.log import configurar_log


class LLMIndisponivel(RuntimeError):
    """O modelo não respondeu, ou respondeu algo que não dá para aproveitar."""


class LLM(Protocol):
    def completar_json(
        self, sistema: str, usuario: str, schema: dict, *, rotulo: str
    ) -> dict: ...


@dataclass
class ClaudeCodeCLI:
    """Chama `claude -p` e devolve a resposta já em JSON."""

    modelo: str
    timeout_s: int = 180
    orcamento_usd: float = 1.0
    executavel: str = "claude"

    def completar_json(
        self, sistema: str, usuario: str, schema: dict, *, rotulo: str
    ) -> dict:
        logger = configurar_log()
        # No Windows o `claude` é um `.cmd`, que só é encontrado por `which`.
        # Resolver aqui permite manter `shell=False` — com `shell=True` o
        # conteúdo do diário passaria pelo interpretador de comandos.
        caminho = shutil.which(self.executavel)
        if caminho is None:
            raise LLMIndisponivel("claude CLI não encontrado")

        argv = [
            caminho,
            "-p",
            "--model", self.modelo,
            "--output-format", "json",
            "--json-schema", json.dumps(schema, ensure_ascii=False),
            "--system-prompt", sistema,
            "--tools", "",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--max-budget-usd", str(self.orcamento_usd),
        ]
        # O prompt nunca vai para o log: são milhares de caracteres de diário
        # por chamada, e o log é lido por humano.
        logger.info("llm %s: %d caracteres no prompt", rotulo, len(usuario))

        # Diretório temporário como `cwd`: assim o CLI não enxerga o repositório
        # nem escreve nada nele. O contexto apaga o diretório mesmo se a chamada
        # estourar o tempo.
        with tempfile.TemporaryDirectory(prefix="boletim-llm-") as trabalho:
            try:
                processo = subprocess.run(
                    argv,
                    input=usuario,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=self.timeout_s,
                    cwd=trabalho,
                    env={**os.environ},
                    shell=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise LLMIndisponivel(
                    f"llm {rotulo}: sem resposta em {self.timeout_s}s"
                ) from exc
            except OSError as exc:
                raise LLMIndisponivel(f"llm {rotulo}: falha ao executar: {exc}") from exc

        return self._ler(processo, rotulo)

    def _ler(self, processo: subprocess.CompletedProcess, rotulo: str) -> dict:
        resultado: dict[str, Any] | None = None
        try:
            lido = json.loads(processo.stdout)
            resultado = lido if isinstance(lido, dict) else None
        except (json.JSONDecodeError, TypeError):
            resultado = None

        if processo.returncode != 0 or (resultado or {}).get("is_error"):
            raise LLMIndisponivel(
                f"llm {rotulo}: {_mensagem_de_erro(processo, resultado)}"
            )
        if resultado is None:
            raise LLMIndisponivel(f"llm {rotulo}: saída não é JSON")
        if "structured_output" in resultado:
            return resultado["structured_output"]
        try:
            reparado = reparar(resultado["result"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMIndisponivel(f"llm {rotulo}: resposta sem JSON aproveitável") from exc
        if not isinstance(reparado, dict):
            raise LLMIndisponivel(f"llm {rotulo}: resposta não é um objeto JSON")
        return reparado


def _mensagem_de_erro(
    processo: subprocess.CompletedProcess, resultado: dict[str, Any] | None
) -> str:
    """Motivo curto da falha. Truncado: stderr de CLI vem com rastro inteiro."""
    for texto in ((resultado or {}).get("result"), processo.stderr, processo.stdout):
        if isinstance(texto, str) and texto.strip():
            return texto.strip()[:200]
    return f"saiu com código {processo.returncode}"


@dataclass
class LLMFalso:
    """Dublê do LLM nos testes: respostas fixas por rótulo, sem rede.

    Um dict é a resposta fixa daquele rótulo, repetida a cada chamada; uma
    lista é uma fila, uma resposta por chamada — é assim que se escreve
    "errou na primeira, acertou na segunda" sem simular o modelo.
    """

    respostas: dict[str, dict | list[dict]]
    chamadas: list[tuple[str, str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Cópia das filas: consumir a lista do teste faria um segundo uso da
        # mesma fixture começar já esgotado.
        self.respostas = {
            rotulo: list(v) if isinstance(v, list) else v
            for rotulo, v in self.respostas.items()
        }

    def completar_json(
        self, sistema: str, usuario: str, schema: dict, *, rotulo: str
    ) -> dict:
        self.chamadas.append((rotulo, sistema, usuario))
        if rotulo not in self.respostas:
            raise LLMIndisponivel(f"llm falso: sem resposta para o rótulo {rotulo}")
        resposta = self.respostas[rotulo]
        if isinstance(resposta, dict):
            return resposta
        if not resposta:
            raise LLMIndisponivel(f"llm falso: fila esgotada para o rótulo {rotulo}")
        return resposta.pop(0)
