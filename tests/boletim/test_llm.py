import json
import logging
import shutil
import subprocess

import pytest

from boletim.llm import ClaudeCodeCLI, LLMFalso, LLMIndisponivel
from radar.core.log import configurar_log

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}}


class _Chamada:
    """Guarda o que o `subprocess.run` recebeu, para o teste inspecionar."""

    def __init__(self) -> None:
        self.argv: list[str] = []
        self.kwargs: dict = {}


@pytest.fixture
def cli(monkeypatch) -> ClaudeCodeCLI:
    monkeypatch.setattr(shutil, "which", lambda nome: f"C:/bin/{nome}.cmd")
    return ClaudeCodeCLI(modelo="claude-haiku-4-5", timeout_s=30, orcamento_usd=0.5)


def _responder(monkeypatch, stdout: str, *, returncode: int = 0) -> _Chamada:
    registro = _Chamada()

    def falso_run(argv, **kwargs):
        registro.argv = list(argv)
        registro.kwargs = kwargs
        return subprocess.CompletedProcess(argv, returncode, stdout, "")

    monkeypatch.setattr(subprocess, "run", falso_run)
    return registro


# ── ClaudeCodeCLI: montagem do comando ──────────────────────────────────
def test_argv_carrega_schema_modelo_e_desliga_ferramentas(cli, monkeypatch):
    registro = _responder(monkeypatch, json.dumps({"structured_output": {"a": 1}}))
    cli.completar_json("sistema", "usuario", SCHEMA, rotulo="lote-0")

    argv = registro.argv
    assert argv[0].endswith("claude.cmd")
    assert "-p" in argv
    assert argv[argv.index("--model") + 1] == "claude-haiku-4-5"
    assert argv[argv.index("--json-schema") + 1] == json.dumps(SCHEMA, ensure_ascii=False)
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--system-prompt") + 1] == "sistema"
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--max-budget-usd") + 1] == "0.5"
    assert "--no-session-persistence" in argv
    assert "--strict-mcp-config" in argv


def test_prompt_do_usuario_vai_por_stdin_e_nao_por_argumento(cli, monkeypatch):
    registro = _responder(monkeypatch, json.dumps({"structured_output": {"a": 1}}))
    cli.completar_json("sistema", "conteúdo do lote", SCHEMA, rotulo="lote-0")

    assert registro.kwargs["input"] == "conteúdo do lote"
    assert "conteúdo do lote" not in registro.argv
    assert registro.kwargs["timeout"] == 30
    assert registro.kwargs["shell"] is False
    assert registro.kwargs["cwd"]


def test_log_cita_o_rotulo_e_o_tamanho_mas_nunca_o_prompt(cli, monkeypatch, caplog):
    _responder(monkeypatch, json.dumps({"structured_output": {"a": 1}}))
    # O logger do radar não propaga para a raiz, então o handler do caplog
    # precisa ser pendurado nele para que o teste enxergue as linhas.
    logger = configurar_log()
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="radar"):
            cli.completar_json("sistema", "segredo do lote", SCHEMA, rotulo="lote-7")
    finally:
        logger.removeHandler(caplog.handler)

    registrado = caplog.text
    assert "lote-7" in registrado
    assert "15" in registrado
    assert "segredo do lote" not in registrado


# ── ClaudeCodeCLI: leitura da resposta ──────────────────────────────────
def test_structured_output_e_devolvido_como_veio(cli, monkeypatch):
    _responder(monkeypatch, json.dumps({"structured_output": {"a": 1}, "result": "ignore"}))
    assert cli.completar_json("s", "u", SCHEMA, rotulo="r") == {"a": 1}


def test_sem_structured_output_o_result_e_reparado(cli, monkeypatch):
    _responder(monkeypatch, json.dumps({"result": '```json\n{"a": 2}\n```'}))
    assert cli.completar_json("s", "u", SCHEMA, rotulo="r") == {"a": 2}


def test_is_error_vira_llm_indisponivel(cli, monkeypatch):
    _responder(monkeypatch, json.dumps({"is_error": True, "result": "orçamento estourado"}))
    with pytest.raises(LLMIndisponivel, match="orçamento estourado"):
        cli.completar_json("s", "u", SCHEMA, rotulo="r")


def test_returncode_diferente_de_zero_vira_llm_indisponivel(cli, monkeypatch):
    _responder(monkeypatch, "", returncode=1)
    with pytest.raises(LLMIndisponivel):
        cli.completar_json("s", "u", SCHEMA, rotulo="r")


def test_stdout_ilegivel_vira_llm_indisponivel(cli, monkeypatch):
    _responder(monkeypatch, "não sou json")
    with pytest.raises(LLMIndisponivel):
        cli.completar_json("s", "u", SCHEMA, rotulo="r")


def test_result_sem_json_vira_llm_indisponivel(cli, monkeypatch):
    _responder(monkeypatch, json.dumps({"result": "desculpe, não consigo"}))
    with pytest.raises(LLMIndisponivel):
        cli.completar_json("s", "u", SCHEMA, rotulo="r")


def _capturar(cli, caplog, stdout: str) -> str:
    logger = configurar_log()
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="radar"):
            with pytest.raises(LLMIndisponivel):
                cli.completar_json("sistema", "segredo do lote", SCHEMA, rotulo="lote-3")
    finally:
        logger.removeHandler(caplog.handler)
    return caplog.text


def test_stdout_ilegivel_registra_o_comeco_da_saida_no_log(cli, monkeypatch, caplog):
    """Sem ver a saída, "saída não é JSON" não diz o que aconteceu.

    A mensagem de erro sozinha não distingue um banner de atualização do CLI de
    uma recusa do modelo, e sem isso a próxima queda no meio do dia volta a ser
    investigada por adivinhação.
    """
    _responder(monkeypatch, "Claude Code v9 disponível. " + "x" * 500)
    registrado = _capturar(cli, caplog, "")

    assert "lote-3" in registrado
    assert "Claude Code v9 disponível." in registrado
    # 300 caracteres do stdout, e nada do prompt.
    assert "x" * 300 not in registrado
    assert "segredo do lote" not in registrado


def test_result_sem_json_registra_o_comeco_da_resposta_no_log(cli, monkeypatch, caplog):
    _responder(monkeypatch, json.dumps({"result": "desculpe, não consigo classificar"}))
    registrado = _capturar(cli, caplog, "")

    assert "desculpe, não consigo classificar" in registrado
    assert "segredo do lote" not in registrado


def test_timeout_vira_llm_indisponivel(cli, monkeypatch):
    def estoura(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 30)

    monkeypatch.setattr(subprocess, "run", estoura)
    with pytest.raises(LLMIndisponivel, match="30"):
        cli.completar_json("s", "u", SCHEMA, rotulo="r")


def test_erro_de_sistema_operacional_vira_llm_indisponivel(cli, monkeypatch):
    def falha(argv, **kwargs):
        raise OSError("Exec format error")

    monkeypatch.setattr(subprocess, "run", falha)
    with pytest.raises(LLMIndisponivel):
        cli.completar_json("s", "u", SCHEMA, rotulo="r")


def test_executavel_ausente_vira_llm_indisponivel(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda nome: None)
    with pytest.raises(LLMIndisponivel, match="não encontrado"):
        ClaudeCodeCLI(modelo="m").completar_json("s", "u", SCHEMA, rotulo="r")


# ── LLMFalso ────────────────────────────────────────────────────────────
def test_falso_devolve_a_resposta_do_rotulo():
    falso = LLMFalso({"lote-0": {"itens": []}})
    assert falso.completar_json("s", "u", SCHEMA, rotulo="lote-0") == {"itens": []}


def test_falso_repete_a_resposta_fixa_a_cada_chamada():
    falso = LLMFalso({"lote-0": {"itens": []}})
    for _ in range(3):
        assert falso.completar_json("s", "u", SCHEMA, rotulo="lote-0") == {"itens": []}
    assert len(falso.chamadas) == 3


def test_falso_consome_a_fila_na_ordem():
    falso = LLMFalso({"editorial": [{"n": 1}, {"n": 2}]})
    assert falso.completar_json("s", "u", SCHEMA, rotulo="editorial") == {"n": 1}
    assert falso.completar_json("s", "u", SCHEMA, rotulo="editorial") == {"n": 2}


def test_falso_com_fila_esgotada_fica_indisponivel():
    falso = LLMFalso({"editorial": [{"n": 1}]})
    falso.completar_json("s", "u", SCHEMA, rotulo="editorial")
    with pytest.raises(LLMIndisponivel):
        falso.completar_json("s", "u", SCHEMA, rotulo="editorial")


def test_falso_sem_resposta_para_o_rotulo_fica_indisponivel():
    with pytest.raises(LLMIndisponivel, match="lote-9"):
        LLMFalso({}).completar_json("s", "u", SCHEMA, rotulo="lote-9")


def test_falso_registra_rotulo_sistema_e_usuario():
    falso = LLMFalso({"lote-0": {"ok": True}})
    falso.completar_json("sistema", "usuario", SCHEMA, rotulo="lote-0")
    assert falso.chamadas == [("lote-0", "sistema", "usuario")]



def test_arquivo_deixado_aberto_pelo_cli_nao_derruba_a_chamada(cli, monkeypatch):
    """A limpeza do diretório de trabalho não pode virar falha da geração.

    Observado numa rodada real no Windows: o `claude` é um processo Node que
    ainda segura o diretório quando o `subprocess.run` retorna, e o
    `TemporaryDirectory` estourava `PermissionError [WinError 32]` na saída do
    `with` - depois de o modelo ter respondido. O dia inteiro saía com exit 2
    por causa de um diretório temporário. Aqui o dublê deixa um arquivo aberto
    dentro do `cwd`, que é o que o Windows recusa a apagar.
    """
    abertos = []

    def falso_run(argv, **kwargs):
        aberto = open(f"{kwargs['cwd']}/sessao.lock", "w", encoding="utf-8")
        aberto.write("segurando o diretório")
        abertos.append(aberto)  # vazamento proposital: o handle segue aberto
        return subprocess.CompletedProcess(argv, 0, json.dumps({"structured_output": {"a": 1}}), "")

    monkeypatch.setattr(subprocess, "run", falso_run)
    try:
        assert cli.completar_json("s", "u", SCHEMA, rotulo="lote-0") == {"a": 1}
    finally:
        for aberto in abertos:
            aberto.close()
