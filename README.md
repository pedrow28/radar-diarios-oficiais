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
radar coletar --data 2026-09-04 --fonte todas   # dou | inlabs | iofmg | todas
radar coletar --fonte inlabs,iofmg              # lista separada por vírgula
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

## Fonte INLABS (opcional)

**O padrão é o portal.** `boletim.fontes` no `config/config.yaml` traz `dou` e
`iofmg`: a fonte `dou` raspa o portal público `in.gov.br` e não exige conta
nenhuma. Foi ela que sustentou os cinco dias da semana de validação real, a
partir de IP residencial. De IP de datacenter o portal pode não responder —
numa VPS deu HTTP 000 —, e se os runners do GitHub estiverem na mesma situação
a troca para o INLABS é uma linha de YAML. Antes de trocar, rode a **sonda do
portal** (seção "Rotina em nuvem"): ela responde de graça se o runner passa.

O INLABS é o caminho alternativo: o serviço oficial de distribuição do DOU da
Imprensa Nacional, um zip de XMLs por seção (`DO1`, `DO2`, `DO3` e as edições
extras `DO1E`…), com o inteiro teor de cada matéria. Exige conta gratuita em
<https://inlabs.in.gov.br/>.

**Ressalva honesta:** a fonte `inlabs` nunca rodou contra o serviço real. O que
existe de teste é contra fixture sintética, montada a partir da documentação do
formato. Ligá-la é uma troca a validar, não um caminho já percorrido.

Para trocar, edite `boletim.fontes` (`dou` → `inlabs`) e cadastre os dois
segredos. As credenciais vêm do ambiente, nunca do YAML:

```bash
export INLABS_EMAIL="voce@exemplo.org"
export INLABS_SENHA="sua-senha"
radar coletar --fonte inlabs,iofmg
```

O login é preguiçoso: reprocessar um dia que já está em `data/raw/<data>/inlabs/`
não pede credencial nenhuma. Sem edição publicada na data — domingo, feriado —
o serviço responde 404 e a coleta sai `vazio`, exit 0.

Quais órgãos entram é decisão do bloco `fontes.inlabs` do
`config/config.yaml`: `orgaos` casa o 1º nível de `artCategory`, e
`subunidades_extra` recorta a "Presidência da República", que de outro modo
traria o Executivo inteiro. A ANVISA é aceita em qualquer nível da hierarquia,
porque o serviço ora a publica como órgão de 1º nível, ora sob o Ministério da
Saúde.

## Boletim diário (newsletter)

O `radar` entrega dado limpo; o `boletim` é a camada que transforma esse dado
numa edição legível por um gestor. São três camadas encadeadas, cada uma com um
comando próprio:

| camada  | comando            | entrega                                    |
|---------|--------------------|--------------------------------------------|
| coleta  | `radar coletar`    | `data/normalized/<data>/<fonte>.json`      |
| boletim | `boletim gerar`    | `boletim/saida/<data>/` (e-mail, md, itens)|
| site    | `boletim site`     | `site/` estático para o GitHub Pages       |

Entre a coleta e o modelo há um prefiltro determinístico: descarta nomeação,
extrato de contrato e aviso de licitação por regex, e registra em
`prefiltro.json` qual regra descartou o quê. Só o que sobra vai ao LLM, em
lotes, para receber categoria, resumo e relevância. As categorias são cinco:

| categoria | o que entra                                                    |
|-----------|-----------------------------------------------------------------|
| A         | captação de recursos: habilitação, teto MAC, emenda, repasse    |
| B         | mudança de regra: critério, piso, prazo, tabela                 |
| C         | edital ou chamamento público                                    |
| D         | fato administrativo relevante, sem recurso e sem regra nova     |
| X         | irrelevante; fica em `itens.json`, fora da edição               |

### Rodar local

```bash
pip install -e ".[boletim,dev]"

boletim gerar --data 2026-09-03                 # coleta já feita; chama o modelo
boletim gerar --data 2026-09-03 --sem-site      # não publica no site/
boletim renderizar --data 2026-09-03            # refaz os arquivos, sem gastar LLM
boletim site                                    # reconstrói só o índice
```

Para ensaiar o pipeline inteiro sem rede, sem custo e sem modelo, use as
respostas gravadas nas fixtures:

```bash
boletim gerar --data 2026-09-03 --llm falso --respostas tests/fixtures/boletim/llm
```

Como o `radar`, o comando `boletim` só existe no `PATH` com a venv ativada; a
forma `python -m boletim.cli gerar ...` é equivalente e sempre funciona.

### Saída

```
boletim/saida/<data>/
  prefiltro.json   o que foi descartado e por qual regra
  itens.json       o julgamento do dia, incluindo os itens X
  edicao.md        a edição em markdown
  edicao.html      o e-mail pronto para enviar
site/
  index.html · edicoes/<data>.html · edicoes.json · assets/
```

`itens.json` é o que permite `boletim renderizar`: corrigir um template não
custa uma segunda chamada de modelo.

**`boletim/saida/` é versionada.** Ela não está no `.gitignore`: `boletim/saida/<data>`
é o registro auditável do julgamento que foi ao ar, e é o workflow que commita
a pasta do dia. A contrapartida é que rodar o boletim na sua máquina suja a
árvore. Duas formas de não commitar uma edição de teste:

```bash
boletim gerar --data 2026-09-03 --sem-site     # não mexe no site/
rm -rf boletim/saida/2026-09-03                # e apague a pasta do dia antes de commitar
```

ou, melhor para uso repetido, um `--config` próprio apontando `boletim.dir_saida`
e `boletim.dir_site` para fora do repositório:

```yaml
# ~/radar-local.yaml
boletim:
  dir_saida: /tmp/radar/saida
  dir_site: /tmp/radar/site
```

```bash
boletim gerar --data 2026-09-03 --config ~/radar-local.yaml
```

### Exit codes do `boletim`

| exit | saída no stdout      | significado                                  |
|------|----------------------|-----------------------------------------------|
| 0    | `boletim: N publicações…` | edição inteira                          |
| 0    | `boletim: vazio`     | não houve edição nos diários (feriado, domingo) |
| 1    | `boletim: vazio`     | idem, mas alguma fonte esperada não coletou: nada a publicar, rodada degradada |
| 1    | `boletim: … status=parcial` | edição saiu com ressalva: uma fonte faltou, ou algum item caiu no fallback D |
| 2    | `erro: …` (stderr)   | não saiu edição; nada deve ser publicado      |

O 1 é publicável de propósito: o prazo de um edital não espera o IOF-MG voltar.
O 2 nunca é: a rotina em nuvem derruba o job antes de tocar no site. Fonte
`ausente` nunca conta como dia vazio — com **todas** as fontes ausentes o
comando sai 2 (`erro: nenhuma fonte coletada em <data>`), porque nada a
classificar é coleta que não aconteceu, não domingo.

### O modelo

A classificação e a abertura da edição são feitas pelo **Claude Haiku**
(`boletim.modelo` no `config/config.yaml`), chamado pelo **Claude Code em modo
`-p`**, não pela API. Não há chave de API neste projeto: o que autentica é o
token da assinatura.

```bash
claude setup-token          # gera o token; guarde em CLAUDE_CODE_OAUTH_TOKEN
```

Na máquina onde o Claude Code já está logado, nada disso é necessário — o
`boletim` acha o CLI no `PATH` e usa a sessão existente. O token só é preciso
onde não há login interativo, como no GitHub Actions. **Cada execução consome a
cota da assinatura**, não um crédito de API à parte.

A chamada roda desarmada: sem ferramentas, sem MCP, sem sessão persistida, sem
herdar configuração do projeto, com teto de gasto e num diretório temporário. O
que entra no prompt é texto de diário oficial vindo da internet; se esse texto
contiver instruções, o pior desfecho é uma classificação errada.

### Identidade visual

A autoridade é o `DESIGN.md` da Thauma (documento interno, fora deste repo), não
o gosto de quem edita o template. O que ele impõe e está codificado aqui:
sentença em vez de Title Case, número em vez de adjetivo, hífen em vez de
travessão, nada de emoji nem de pergunta retórica — `boletim.edicao.validar_voz`
reprova o texto do modelo e pede correção antes de aceitar a abertura.

**Um botão por e-mail.** O botão é o WhatsApp; "ler a versão completa" e o
segundo contato são links de texto. O CTA é configurável em `boletim.cta` do
`config/config.yaml` (`whatsapp`, `texto_botao`, `mensagem`), e a mensagem
aceita `{data}`.

### Rotina em nuvem

O workflow `.github/workflows/boletim-diario.yml` roda a cadeia inteira e
publica no GitHub Pages. Setup único no repositório:

1. **Settings → Pages → Source: "GitHub Actions"**. Sem isso o `deploy-pages`
   falha com "Pages not enabled".
2. **Settings → Secrets and variables → Actions**, um segredo obrigatório:
   - `CLAUDE_CODE_OAUTH_TOKEN` — saída de `claude setup-token`.
3. Só se `boletim.fontes` incluir `inlabs`: `INLABS_EMAIL` e `INLABS_SENHA`,
   de uma conta gratuita em <https://inlabs.in.gov.br/>. Com a lista padrão
   (`dou`, `iofmg`) eles não são usados — os dois nomes continuam no `env` do
   passo de coleta, chegam vazios e nada os lê, porque a `FonteINLABS` só é
   instanciada quando `inlabs` está entre as fontes pedidas.
4. Nada mais: o `GITHUB_TOKEN` do próprio Actions cobre o commit, o deploy e a
   issue de falha.

**A rotina vem desligada.** O repositório traz o arquivo `PARAR` na raiz: o job
roda, imprime o motivo e pula tudo. É de propósito — a perna do LLM ainda não
executou nenhuma vez contra o `claude` real, e um cron diário estreando com uma
flag recusada pelo CLI viraria uma issue vermelha por dia. Para ligar, faça a
rodada que falta (`boletim gerar --data <data já coletada> --llm claude
--sem-site`, com o `claude` logado), confira o `itens.json` e o `edicao.html`, e
então apague o arquivo e commite:

```bash
git rm PARAR && git commit -m "boletim: liga a rotina diária" && git push
```

**Horários.** 09:30 e 12:00 no horário de Brasília, de segunda a sábado (no
arquivo eles aparecem como `30 12` e `0 15`, porque o cron do GitHub é UTC). A
execução das 12:00 é a rede de segurança de quando o diário ainda não estava
publicado às 09:30, e se anula sozinha quando `site/edicoes/<data>.html` já
existe.

**Disparo manual.** Actions → "Boletim diário" → "Run workflow", com duas
entradas: `data` (`AAAA-MM-DD`, padrão hoje em São Paulo) e `forcar` (regera
mesmo que a edição do dia já exista).

**Freio remoto.** Criar e commitar um arquivo `PARAR` na raiz da `main`
desliga a rotina: o job continua rodando, imprime `freio remoto ativo:` com a
primeira linha do arquivo — escreva ali o motivo — e pula todo o resto, sem
coletar, sem chamar o modelo e sem publicar. Remover o arquivo religa. É a
mesma convenção de freio remoto usada internamente na Thauma: desligar tem de
ser um commit que qualquer um vê e reverte, não uma mudança escondida em
Settings.

```bash
echo "IOF-MG mudou o layout do PDF; retomar depois do ajuste" > PARAR
git add PARAR && git commit -m "freio: pausa o boletim" && git push
```

**Quando falha.** O job abre uma issue intitulada `Boletim <data> falhou` com o
link da execução, e não duplica se já houver uma aberta com o mesmo título.
Exit 2 na coleta ou na geração derruba o job antes de qualquer publicação — e
qualquer código que não seja 0, 1 ou 2 (um 127, um 137) também derruba, em vez
de cair num `else` de sucesso silencioso. `boletim: vazio` termina o job sem
publicar nada.

**Fontes da coleta.** O `--fonte` do workflow é lido de `boletim.fontes` do
`config/config.yaml`, não escrito à mão no YAML do Actions: as duas listas
divergindo produziriam um dia inteiro de fonte `ausente`, que hoje é exit 2 e
antes era um "vazio" verde.

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
