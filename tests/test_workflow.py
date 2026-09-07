"""Os dois workflows, lidos como código.

Um `.yml` de Actions só é executado em produção: não há como rodá-lo antes de
subir, e um erro ali aparece como boletim que não saiu - ou, pior, como segredo
no log público. Estes testes cobrem o que dá para afirmar sem um runner: a
forma do arquivo, os dois horários, os segredos, as permissões mínimas e
as duas regras de higiene (nada de `echo` com segredo, nada de `::set-output`).

Cobrem também o `testes.yml`, que é o único runner que roda a suíte antes do
merge, o `sonda-dou.yml`, que mede de graça se o portal do DOU responde a um
runner do GitHub, e o `PARAR`, que desliga a rotina quando está presente.

O que eles não cobrem, e nenhum teste local cobriria, é o comportamento do
runner. Isso fica com o `workflow_dispatch` e com a issue automática de falha.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
WORKFLOW = RAIZ / ".github" / "workflows" / "boletim-diario.yml"
CI = RAIZ / ".github" / "workflows" / "testes.yml"
SONDA = RAIZ / ".github" / "workflows" / "sonda-dou.yml"
FREIO = RAIZ / "PARAR"
FIXTURES_COLETA = RAIZ / "tests" / "fixtures" / "workflow"
BASH = shutil.which("bash")

# 09:30 e 12:00 no horário de Brasília, de segunda a sábado (o cron do GitHub é UTC).
CRONS = {"30 12 * * 1-6", "0 15 * * 1-6"}
# O único segredo sem o qual a rotina não roda: o modelo é chamado em toda
# execução. Os do INLABS são opcionais desde que o portal virou a fonte padrão.
SEGREDO_OBRIGATORIO = "CLAUDE_CODE_OAUTH_TOKEN"
SEGREDOS_OPCIONAIS = {"INLABS_EMAIL", "INLABS_SENHA"}
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


def test_o_unico_segredo_obrigatorio_e_o_do_modelo(texto: str) -> None:
    """Só o token do Claude Code é indispensável; os do INLABS são opcionais.

    A fonte padrão é o portal (`dou`), que não pede credencial. Os dois
    segredos do INLABS podem continuar no `env` do passo de coleta: um
    `${{ secrets.X }}` não configurado vira string vazia, e a `FonteINLABS` só
    é instanciada quando `inlabs` está na lista de fontes — a instância em
    `radar.cli._fontes` é preguiçosa. Nenhum outro segredo pode aparecer: um
    nome novo no YAML sem o segredo cadastrado é falha silenciosa.
    """
    referenciados = set(re.findall(r"secrets\.([A-Z_]+)", texto))
    assert SEGREDO_OBRIGATORIO in referenciados
    assert referenciados <= {SEGREDO_OBRIGATORIO, *SEGREDOS_OPCIONAIS}


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


def test_coleta_sem_nada_normalizado_derruba_o_job_antes_de_publicar(
    workflow: dict[str, Any],
) -> None:
    """Exit 2 com o disco vazio significa "não publicar": o passo propaga."""
    coleta = next(p for p in passos(workflow) if p.get("id") == "coleta")
    assert "exit 2" in coleta["run"]
    assert coleta["env"]["INLABS_EMAIL"] == "${{ secrets.INLABS_EMAIL }}"


def test_uma_fonte_fora_do_ar_ainda_publica_edicao_parcial(
    workflow: dict[str, Any],
) -> None:
    """Exit 2 do `radar` é o pior status entre as fontes, não "nada coletado".

    Com `dou` fora do ar e `iofmg` normal, o `radar` sai 2 mesmo tendo gravado
    `data/normalized/<data>/iofmg.json`. Abortar aí custaria a edição inteira
    por causa de uma fonte: o passo olha o disco antes de desistir e, achando
    normalizado, segue com `parcial=true` - a fonte que caiu entra no boletim
    como `ausente`, que é exatamente a ressalva que a edição parcial existe
    para carregar. Sem nenhum json, aí sim `exit 2`.
    """
    coleta = next(p for p in passos(workflow) if p.get("id") == "coleta")
    # Só os comandos: um `exit 2` citado dentro de um comentário não é o `exit
    # 2` que derruba o job, e compará-los faria o teste passar (ou falhar) por
    # prosa.
    linhas = [
        linha.strip()
        for linha in coleta["run"].splitlines()
        if linha.strip() and not linha.strip().startswith("#")
    ]

    # A checagem de disco precisa vir antes do `exit 2`, não depois.
    checagem = next(i for i, linha in enumerate(linhas) if "data/normalized/$DATA" in linha)
    aborto = next(i for i, linha in enumerate(linhas) if linha == "exit 2")
    assert checagem < aborto, "o passo desiste do dia antes de olhar o disco"

    assert 'echo "parcial=true" >> "$GITHUB_OUTPUT"' in linhas
    # Qual fonte caiu tem de aparecer no log: o `radar` imprime `<fonte>: erro`
    # em stdout, e stdout redirecionado a arquivo some se ninguém o mostrar.
    assert any(linha.startswith("cat ") for linha in linhas)


def test_coleta_declara_fontes_com_erro(workflow: dict[str, Any]) -> None:
    """A coleta precisa dizer quais fontes deram `erro`, não só que houve
    ressalva: `parcial=true` avisa a edição, mas sem o nome da fonte ninguém
    sabe, no dia, qual delas caiu."""
    coleta = next(p for p in passos(workflow) if p.get("id") == "coleta")
    assert 'echo "fontes_com_erro=$fontes_com_erro" >> "$GITHUB_OUTPUT"' in coleta["run"]
    assert "grep" in coleta["run"] and ": erro" in coleta["run"]


def _linha_fontes_com_erro(workflow: dict[str, Any]) -> str:
    coleta = next(p for p in passos(workflow) if p.get("id") == "coleta")
    return next(
        linha.strip()
        for linha in coleta["run"].splitlines()
        if linha.strip().startswith("fontes_com_erro=")
    )


@pytest.mark.skipif(BASH is None, reason="bash não está no PATH")
@pytest.mark.parametrize(
    ("fixture", "esperado"),
    [
        ("coleta-tudo-ok.txt", ""),
        ("coleta-dou-fora-do-ar.txt", "dou"),
        ("coleta-ambas-fora-do-ar.txt", "dou,iofmg"),
    ],
)
def test_fontes_com_erro_sobrevive_ao_dia_sem_nenhuma_fonte_caida(
    workflow: dict[str, Any], fixture: str, esperado: str
) -> None:
    """A linha real do passo `coleta`, rodada no bash de verdade.

    G12 (fix): num dia saudável o `grep` não acha `erro` em lugar nenhum e sai
    1; sob `set -e`/`pipefail`, uma atribuição `fontes_com_erro=$(grep | sed |
    tr | sed)` sem `|| true` mata o script ali - antes do `parcial=` e da
    checagem de `rc`. Um teste que só verificasse a presença das strings
    "grep" e "fontes_com_erro" no YAML não pegaria essa regressão, porque a
    string continua lá; só rodar a linha sob `bash -eo pipefail` de verdade,
    contra um stdout onde ninguém caiu, expõe o script morrendo. Por isso a
    linha é extraída do próprio arquivo do workflow, não reescrita aqui.
    """
    linha = _linha_fontes_com_erro(workflow)
    saida = FIXTURES_COLETA / fixture
    script = f"""
    set -eo pipefail
    saida="{saida.as_posix()}"
    {linha}
    printf '%s' "$fontes_com_erro"
    """
    resultado = subprocess.run(
        [BASH, "-c", script], capture_output=True, text=True, cwd=RAIZ
    )
    assert resultado.returncode == 0, (
        f"a linha derrubou o script (rc={resultado.returncode}): {resultado.stderr}"
    )
    assert resultado.stdout == esperado


def test_fonte_fora_do_ar_abre_issue_sem_esperar_o_dia_seguinte(
    workflow: dict[str, Any],
) -> None:
    """G12: uma fonte bloqueada (ex.: o portal do DOU recusando o runner) tem
    de virar issue no próprio dia, não só o aviso de "coleta parcial" dentro
    da edição publicada."""
    passo = next(
        p for p in passos(workflow) if "fontes_com_erro != ''" in p.get("if", "")
    )
    assert "steps.freio.outputs.pular != 'true'" in passo["if"], (
        "o passo roda mesmo com o freio ativo"
    )
    assert passo["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert passo["env"]["FONTES_COM_ERRO"] == "${{ steps.coleta.outputs.fontes_com_erro }}"
    assert "Coleta parcial em" in passo["run"]
    assert "fora do ar" in passo["run"]
    assert "$RUN_URL" in passo["run"]
    # Mesma proteção contra duplicata da issue de falha: procura por título
    # antes de criar.
    assert "gh issue list" in passo["run"]
    assert "gh issue create" in passo["run"]


def test_issue_de_fonte_fora_do_ar_nao_ecoa_segredo(workflow: dict[str, Any]) -> None:
    passo = next(
        p for p in passos(workflow) if "fontes_com_erro != ''" in p.get("if", "")
    )
    for numero, linha in enumerate(passo.get("run", "").splitlines(), start=1):
        if "secrets." in linha:
            assert "echo" not in linha, f"linha {numero}: {linha.strip()}"
    assert "GH_TOKEN" not in passo["run"], "o token não deve ser impresso no script"


def test_codigo_inesperado_derruba_o_job(workflow: dict[str, Any]) -> None:
    """Um rc que não seja 0, 1 ou 2 (ex.: 127, 137) não pode cair no `else` como
    sucesso silencioso: o passo precisa propagar esse código com `exit "$rc"`."""
    coleta = next(p for p in passos(workflow) if p.get("id") == "coleta")
    boletim = next(p for p in passos(workflow) if p.get("id") == "boletim")
    for passo in (coleta, boletim):
        assert 'exit "$rc"' in passo["run"], (
            f"passo {passo.get('name')!r} não propaga um código de saída inesperado"
        )


def test_boletim_vazio_nao_publica(workflow: dict[str, Any]) -> None:
    """Domingo e feriado saem com `boletim: vazio`; não há o que subir.

    O `grep` é no stdout, não no exit code, de propósito: o dia vazio com uma
    fonte que não chegou sai 1, e 1 é um código que o passo aceita e segue.
    """
    boletim = next(p for p in passos(workflow) if p.get("id") == "boletim")
    assert "boletim: vazio" in boletim["run"]
    for passo in passos(workflow):
        usa = passo.get("uses", "")
        if usa.startswith(("actions/deploy-pages", "actions/upload-pages-artifact")):
            assert "steps.boletim.outputs.vazio != 'true'" in passo.get("if", ""), (
                f"passo {passo.get('name')!r} publica um dia vazio"
            )


def test_a_lista_de_fontes_vem_do_config_e_nao_do_yaml(
    workflow: dict[str, Any],
) -> None:
    """`boletim.fontes` é a única fonte de verdade da lista de fontes.

    Escrita duas vezes - no YAML do config e no `--fonte` daqui -, ela diverge
    em silêncio, e o dia sai com a fonte esquecida em `ausente`. Foi o defeito
    que a `Carga.todas_ausentes` passou a pegar; este teste fecha a porta antes.
    """
    coleta = next(p for p in passos(workflow) if p.get("id") == "coleta")
    fontes = next(p for p in passos(workflow) if p.get("id") == "fontes")

    assert "config/config.yaml" in fontes["run"]
    assert "ConfigBoletim" in fontes["run"]
    assert 'echo "fontes=$fontes" >> "$GITHUB_OUTPUT"' in fontes["run"]

    assert coleta["env"]["FONTES"] == "${{ steps.fontes.outputs.fontes }}"
    assert '--fonte "$FONTES"' in coleta["run"]
    assert "inlabs" not in coleta["run"], "lista de fontes escrita à mão na coleta"


def test_o_freio_presente_diz_o_motivo_e_o_readme_diz_como_soltar() -> None:
    """O `PARAR` é opcional; o que não é opcional é ele se explicar.

    A versão anterior deste teste exigia que o arquivo existisse. Isso fazia da
    ação normal - soltar o freio depois da rodada real com o `claude` - uma
    quebra da suíte, e a saída óbvia para quem esbarrasse nela seria apagar o
    teste junto com o arquivo, perdendo de vez a garantia de que um freio
    presente diz por que está lá. Aqui a ausência passa: o freio é um estado
    legítimo do repositório, não um invariante.

    Com o arquivo presente, duas exigências. A primeira linha não pode ser
    vazia, porque é ela que o workflow imprime como `freio remoto ativo:` - uma
    linha em branco vira um job que se cala sem dizer por quê. E o README tem
    de ensinar a soltar, senão o freio vira permanente por desconhecimento.
    """
    if not FREIO.exists():
        return
    primeira = FREIO.read_text(encoding="utf-8").splitlines()[0].strip()
    assert primeira, "o freio não diz por que a rotina está parada"
    leiame = (RAIZ / "README.md").read_text(encoding="utf-8")
    assert "git rm PARAR" in leiame, "o README não ensina a soltar o freio"


# ── workflow de testes ──────────────────────────────────────────────────
@pytest.fixture(scope="module")
def ci() -> dict[str, Any]:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def test_a_suite_roda_em_push_e_em_pull_request(ci: dict[str, Any]) -> None:
    """Sem CI, o único runner do projeto era a rotina diária: quebra de template
    aparecia na manhã seguinte, como job vermelho do boletim."""
    disparos = ci.get("on", ci.get(True))
    assert "push" in disparos
    assert "pull_request" in disparos
    # Sem filtro de branch: um push que quebra a suíte precisa doer onde for.
    assert disparos["push"] is None
    assert disparos["pull_request"] is None


def test_a_ci_instala_os_extras_e_roda_o_pytest_com_w_error(ci: dict[str, Any]) -> None:
    passos_ci = ci["jobs"]["pytest"]["steps"]
    corridos = " ".join(passo.get("run", "") for passo in passos_ci)
    assert ci["jobs"]["pytest"]["runs-on"] == "ubuntu-latest"
    assert 'pip install -e ".[boletim,dev]"' in corridos
    assert "-W error" in corridos
    assert "python -m pytest" in corridos


def test_a_ci_so_le_o_repositorio(ci: dict[str, Any]) -> None:
    """Rodar teste não commita, não publica e não abre issue."""
    assert ci["permissions"] == {"contents": "read"}


def test_a_ci_usa_python_311_com_cache(ci: dict[str, Any]) -> None:
    setup = next(
        passo
        for passo in ci["jobs"]["pytest"]["steps"]
        if passo.get("uses", "").startswith("actions/setup-python")
    )
    assert setup["with"]["python-version"] == "3.11"
    assert setup["with"]["cache"] == "pip"
    assert setup["with"]["cache-dependency-path"] == "pyproject.toml"


# ── sonda do portal do DOU ──────────────────────────────────────────────
@pytest.fixture(scope="module")
def texto_sonda() -> str:
    return SONDA.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sonda(texto_sonda: str) -> dict[str, Any]:
    return yaml.safe_load(texto_sonda)


def passos_sonda(sonda: dict[str, Any]) -> list[dict[str, Any]]:
    return sonda["jobs"]["sonda"]["steps"]


def test_a_sonda_existe_e_e_um_job_curto(sonda: dict[str, Any]) -> None:
    """A pergunta que a sonda responde: o portal do DOU atende um runner?

    Ela existe porque a resposta não é sabida - o portal serviu cinco dias de
    IP residencial e recusou uma VPS - e porque descobrir por dentro da rotina
    diária custaria uma issue vermelha de manhã em vez de um clique.
    """
    assert sonda["jobs"]["sonda"]["runs-on"] == "ubuntu-latest"
    assert sonda["jobs"]["sonda"]["timeout-minutes"] == 10


def test_a_sonda_so_roda_quando_alguem_pede(sonda: dict[str, Any]) -> None:
    """Sem `schedule`: uma sonda agendada vira ruído diário sobre uma pergunta
    que só precisa ser respondida quando alguém está decidindo trocar a fonte.
    E sem gatilho de `push`, que a faria bater no portal a cada commit."""
    disparos = sonda.get("on", sonda.get(True))
    assert set(disparos) == {"workflow_dispatch"}
    entrada = disparos["workflow_dispatch"]["inputs"]["data"]
    assert entrada["type"] == "string"
    assert entrada["required"] is False


def test_a_sonda_so_le_o_repositorio_e_nao_usa_segredo(
    sonda: dict[str, Any], texto_sonda: str
) -> None:
    """A fonte `dou` não tem credencial: um segredo aqui só poderia vazar.

    E `contents: read` porque a sonda não commita, não publica e não abre
    issue - ela mede e escreve no resumo da execução.
    """
    assert sonda["permissions"] == {"contents": "read"}
    assert "secrets." not in texto_sonda


def test_a_sonda_coleta_so_o_dou(sonda: dict[str, Any]) -> None:
    """`--fonte dou` e nada mais: envolver o IOF-MG confundiria a medição."""
    corridos = " ".join(passo.get("run", "") for passo in passos_sonda(sonda))
    assert "--fonte dou" in corridos
    assert "iofmg" not in corridos
    assert "inlabs" not in corridos
    # O rc é o dado da medição; `set +e` é o que impede o `set -e` do runner de
    # matar o passo antes de alguém poder lê-lo.
    assert "set +e" in corridos
    assert "$GITHUB_STEP_SUMMARY" in corridos


def test_a_sonda_guarda_o_que_coletou(sonda: dict[str, Any]) -> None:
    """Um `dou.json` de verdade é a prova de que o runner passou; sem ele, a
    linha do resumo seria só uma palavra sem lastro. `ignore` porque não achar
    arquivo é um desfecho legítimo da sonda, não um aviso amarelo."""
    upload = next(
        p for p in passos_sonda(sonda) if p.get("uses", "").startswith("actions/upload-artifact")
    )
    assert upload["with"]["if-no-files-found"] == "ignore"
    assert upload["with"]["retention-days"] == 7


def test_a_sonda_usa_python_311_com_cache(sonda: dict[str, Any]) -> None:
    setup = next(
        p for p in passos_sonda(sonda) if p.get("uses", "").startswith("actions/setup-python")
    )
    assert setup["with"]["python-version"] == "3.11"
    assert setup["with"]["cache-dependency-path"] == "pyproject.toml"
