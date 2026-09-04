# Radar de Diários Oficiais

Coleta as publicações de saúde do Diário Oficial da União (Ministério da Saúde)
e do Diário Oficial de Minas Gerais (Secretaria de Estado de Saúde) e entrega
JSON normalizado com texto integral, para consumo por agente.

O juízo sobre o que é relevante **não** está aqui: este pacote entrega dado
limpo e completo. A avaliação de relevância para captação de recursos e a
redação da newsletter são responsabilidade dos agentes a jusante.

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp config/.env.example .env    # só necessário para `radar notificar`
```

Sem Playwright e sem `openssl` no sistema: a listagem do DOU vem de um JSON
embutido na página de busca e o PDF assinado do IOF-MG é desembrulhado em
Python puro.

**Sobre o comando `radar`:** ele só existe no `PATH` se a venv acima estiver
ativada (`source .venv/bin/activate` no Linux/macOS, `.venv\Scripts\activate`
no Windows) — é isso que registra `.venv/bin` (ou `.venv\Scripts`) no `PATH`
da sessão. Fora de uma venv ativa (por exemplo um `pip install --user`, como
neste ambiente de validação), `pip` instala o script mas avisa que o diretório
não está no `PATH`, e `radar --help` falha com "comando não encontrado". Nesse
caso, ou sem certeza de que o `PATH` está correto (é o caso do cron, veja
abaixo), use a forma equivalente por módulo, que sempre funciona:

```bash
python -m radar.cli --help
```

## Uso

```bash
radar coletar --data 2026-09-04 --fonte todas   # dou | iofmg | todas
radar coletar --forcar                          # ignora o cache de brutos
radar consultar "teto MAC" --desde 2026-06-01   # histórico indexado
```

Sem `--data`, usa hoje no fuso `America/Sao_Paulo`.

## Saída

```
data/
  raw/<data>/<fonte>/       artefatos originais (reprocessar sem rebaixar)
  normalized/<data>/<fonte>.json    ← o que o agente lê
  radar.db                  histórico com FTS5
```

Cada JSON segue o contrato da seção 5 da spec. O campo `status` é o que
distingue os quatro desfechos:

| `status`  | exit | significado                        | o agente deve       |
|-----------|------|-------------------------------------|----------------------|
| `ok`      | 0    | coleta completa                    | processar           |
| `vazio`   | 0    | não houve edição (feriado/domingo) | seguir sem alarme   |
| `parcial` | 1    | coletou, mas algo falhou           | processar e alertar |
| `erro`    | 2    | a coleta quebrou                   | **não** publicar    |

Com `--fonte todas`, o exit code é o pior status entre as fontes.

## Integração com o Hermes

```python
import json, subprocess
from pathlib import Path

data = "2026-09-04"
proc = subprocess.run(["radar", "coletar", "--data", data, "--fonte", "todas"])
if proc.returncode == 2:
    raise RuntimeError("coleta falhou; não gerar newsletter")

for arquivo in Path(f"data/normalized/{data}").glob("*.json"):
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    if dados["status"] == "vazio":
        continue
    for pub in dados["publicacoes"]:
        ...  # pub["texto"] traz o inteiro teor
```

## Cron na VPS

```cron
30 9 * * 1-6 cd /opt/radar && .venv/bin/radar coletar --fonte todas >> logs/cron.log 2>&1
```

O caminho explícito `.venv/bin/radar` (em vez de só `radar`) é proposital: o
cron não carrega o `PATH` interativo da venv, então depender do `PATH` para
achar o console script falharia. Se preferir não depender nem desse caminho
explícito, a forma por módulo é equivalente e um pouco mais portátil:

```cron
30 9 * * 1-6 cd /opt/radar && .venv/bin/python -m radar.cli coletar --fonte todas >> logs/cron.log 2>&1
```

O DOU e o IOF-MG publicam em dias úteis; sábado tem edição eventual. Domingo
retorna `vazio` com exit 0, o que não polui o log de erro — confirmado contra
a API real do IOF-MG (ver `docs/migracao.md` e o histórico de validação): a
resposta para um domingo é HTTP 200 com `{"dados": null}`, não HTTP 401.

## Testes

```bash
python -m pytest
```

Rodam offline, contra HTML e PDF reais em `tests/fixtures/`. Nenhum faz
requisição de rede.

## Configuração

`config/config.yaml` controla órgão, seção e tipos de publicação. Segredos só
por variável de ambiente — nada de e-mail ou chave no código.

## Documentos

- Design: `docs/superpowers/specs/2026-09-04-radar-diarios-oficiais-design.md`
- Migração dos scripts antigos: `docs/migracao.md`
