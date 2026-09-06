"""O workflow diário, lido como código.

Um `.yml` de Actions só é executado em produção: não há como rodá-lo antes de
subir, e um erro ali aparece como boletim que não saiu - ou, pior, como segredo
no log público. Estes testes cobrem o que dá para afirmar sem um runner: a
forma do arquivo, os dois horários, os três segredos, as permissões mínimas e
as duas regras de higiene (nada de `echo` com segredo, nada de `::set-output`).

O que eles não cobrem, e nenhum teste local cobriria, é o comportamento do
runner. Isso fica com o `workflow_dispatch` e com a issue automática de falha.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "boletim-diario.yml"

# 09:30 e 12:00 no horário de Brasília, de segunda a sábado (o cron do GitHub é UTC).
CRONS = {"30 12 * * 1-6", "0 15 * * 1-6"}
SEGREDOS = {"INLABS_EMAIL", "INLABS_SENHA", "CLAUDE_CODE_OAUTH_TOKEN"}
PASSO_DO_FREIO = "freio"


@pytest.fixture(scope="module")
def texto() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(texto: str) -> dict[str, Any]:
    return yaml.safe_load(texto)


def gatilhos(workflow: dict[str, Any]) -> dict[str, Any]:
    """O bloco `on:` do workflow.

    Em YAML 1.1 - que é o que o PyYAML fala - `on` sem aspas é o booleano
    verdadeiro, não a string "on". O GitHub lê YAML 1.2 e enxerga a chave
    "on"; quem carrega o arquivo em Python precisa aceitar as duas formas, ou
    o teste falha por um detalhe de dialeto e não por um defeito do workflow.
    """
    return workflow.get("on", workflow.get(True))


def passos(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return workflow["jobs"]["boletim"]["steps"]


def test_o_arquivo_e_yaml_valido(workflow: dict[str, Any]) -> None:
    assert workflow["name"] == "Boletim diário"
    assert workflow["jobs"]["boletim"]["runs-on"] == "ubuntu-latest"


def test_os_dois_horarios_diarios(workflow: dict[str, Any]) -> None:
    agendados = {item["cron"] for item in gatilhos(workflow)["schedule"]}
    assert agendados == CRONS


def test_disparo_manual_aceita_data_e_forcar(workflow: dict[str, Any]) -> None:
    entradas = gatilhos(workflow)["workflow_dispatch"]["inputs"]
    assert entradas["data"]["type"] == "string"
    assert entradas["data"]["required"] is False
    assert entradas["forcar"]["type"] == "boolean"
    assert entradas["forcar"]["default"] is False


def test_permissoes_minimas(workflow: dict[str, Any]) -> None:
    permissoes = workflow["permissions"]
    # `contents` para commitar a edição, `pages`+`id-token` para o deploy,
    # `issues` para o passo que abre a issue quando o dia falha.
    assert permissoes["contents"] == "write"
    assert permissoes["pages"] == "write"
    assert permissoes["id-token"] == "write"
    assert permissoes["issues"] == "write"


def test_execucoes_nao_se_atropelam(workflow: dict[str, Any]) -> None:
    """Os dois crons do mesmo dia não podem rodar em paralelo: os dois escrevem
    em `site/` e dariam push por cima um do outro. E cancelar a execução em
    andamento seria pior - o boletim das 09:30 morreria na metade."""
    assert workflow["concurrency"] == {"group": "boletim", "cancel-in-progress": False}


def test_os_tres_segredos_e_apenas_eles(texto: str) -> None:
    referenciados = set(re.findall(r"secrets\.([A-Z_]+)", texto))
    assert referenciados == SEGREDOS


def test_nenhum_passo_imprime_segredo(workflow: dict[str, Any]) -> None:
    """`echo` e `secrets.` na mesma linha é segredo em log público."""
    for passo in passos(workflow):
        for numero, linha in enumerate(passo.get("run", "").splitlines(), start=1):
            if "secrets." in linha:
                assert "echo" not in linha, (
                    f"passo {passo.get('name')!r}, linha {numero}: {linha.strip()}"
                )


def test_toda_saida_lida_e_declarada_no_arquivo_de_outputs(
    texto: str, workflow: dict[str, Any]
) -> None:
    """`::set-output` saiu do Actions em 2023; e output lido tem de ser escrito.

    A segunda metade pega o erro real: `steps.freio.outputs.pulra` num `if`
    não é erro de sintaxe, é uma condição que vale sempre - o passo guardado
    passaria a rodar sempre, em silêncio.
    """
    assert "::set-output" not in texto
    declarados = {
        passo["id"]
        for passo in passos(workflow)
        if "id" in passo
        and ("$GITHUB_OUTPUT" in passo.get("run", "") or "uses" in passo)
    }
    lidos = set(re.findall(r"steps\.(\w+)\.outputs\.", texto))
    assert lidos <= declarados, f"outputs lidos sem quem os escreva: {lidos - declarados}"


def test_o_freio_guarda_todos_os_passos_seguintes(workflow: dict[str, Any]) -> None:
    """Com `PARAR` na raiz, nada depois do freio pode rodar.

    A única exceção é o passo que abre a issue: ele é `if: failure()`, e com o
    freio ativo o job termina verde, então ele não dispara de qualquer forma.
    """
    lista = passos(workflow)
    indice = next(i for i, p in enumerate(lista) if p.get("id") == PASSO_DO_FREIO)
    for passo in lista[indice + 1 :]:
        condicao = passo.get("if", "")
        if "failure()" in condicao:
            continue
        assert f"steps.{PASSO_DO_FREIO}.outputs.pular != 'true'" in condicao, (
            f"passo {passo.get('name')!r} roda mesmo com o freio ativo"
        )


def test_coleta_com_erro_derruba_o_job_antes_de_publicar(
    workflow: dict[str, Any],
) -> None:
    """Exit 2 do `radar` significa "não publicar": o passo precisa propagar."""
    coleta = next(p for p in passos(workflow) if p.get("id") == "coleta")
    assert "exit 2" in coleta["run"]
    assert coleta["env"]["INLABS_EMAIL"] == "${{ secrets.INLABS_EMAIL }}"


def test_boletim_vazio_nao_publica(workflow: dict[str, Any]) -> None:
    """Domingo e feriado saem 0 com `boletim: vazio`; não há o que subir."""
    boletim = next(p for p in passos(workflow) if p.get("id") == "boletim")
    assert "boletim: vazio" in boletim["run"]
    for passo in passos(workflow):
        usa = passo.get("uses", "")
        if usa.startswith(("actions/deploy-pages", "actions/upload-pages-artifact")):
            assert "steps.boletim.outputs.vazio != 'true'" in passo.get("if", ""), (
                f"passo {passo.get('name')!r} publica um dia vazio"
            )
