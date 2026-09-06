# Boletim diário — Design

**Data:** 2026-09-04
**Status:** implementado (camada `boletim/` + `.github/workflows/boletim-diario.yml`)
**Depende de:** `2026-09-04-radar-diarios-oficiais-design.md` (a camada de coleta)

## 1. Objetivo

O `radar` entrega JSON normalizado com o inteiro teor das publicações de saúde do
DOU e do Diário Oficial de Minas Gerais. Ninguém lê JSON de manhã. O `boletim` é
a camada que transforma esse dado numa **edição diária legível por um gestor de
hospital filantrópico, Santa Casa ou secretaria municipal**: o que mudou de
dinheiro e de regra ontem, com órgão, número e valor, em ordem de importância.

O design do `radar` mandou o juízo de relevância para fora do pacote de coleta.
Este documento é o lugar para onde ele foi.

## 2. Escopo

**Dentro:**

- Prefiltro determinístico sobre as publicações do dia, auditável e reversível
- Classificação por LLM em cinco categorias, com resumo e relevância por item
- Abertura da edição (título, "em 30 segundos", intro) escrita pelo LLM
- Renderização em e-mail HTML, markdown e página web
- Site estático para GitHub Pages, com índice de edições
- Rotina diária em GitHub Actions, com freio, e publicação no Pages

**Fora:**

- **Disparo para lista de assinantes — fase 2.** O `edicao.html` sai pronto para
  enviar; quem envia, para quem e com qual provedor não está decidido. Não há
  base de contatos, descadastro nem métrica de abertura neste projeto.
- Segmentação de conteúdo por leitor (todo mundo recebe a mesma edição)
- Ampliação para outros estados ou outras áreas além de saúde
- Web UI, API HTTP, painel

## 3. Arquitetura

Três camadas encadeadas, cada uma com comando próprio e artefato em disco. A
fronteira entre elas é sempre um arquivo, não uma chamada: qualquer etapa pode
ser refeita sozinha.

```
radar coletar   →  data/normalized/<data>/<fonte>.json
boletim gerar   →  boletim/saida/<data>/{prefiltro,itens}.json + edicao.{md,html}
                →  site/edicoes/<data>.html + site/edicoes.json + site/index.html
```

```
boletim/
  carga.py       lê o normalizado do radar; fonte sem arquivo vira "ausente"
  prefiltro.py   regex de descarte e de retenção forte; devolve o motivo
  prompts.py     os dois prompts (classificação e editorial) + montagem do lote
  esquemas.py    JSON Schema das duas respostas + validação + reparo
  llm.py         porta LLM; ClaudeCodeCLI (claude -p) e LLMFalso (fixtures)
  classifica.py  lote → itens, com reconciliação por id e bisseção
  edicao.py      Item/Edicao, ordenação por seção, validar_voz, fallbacks
  render.py      Jinja: e-mail, página, markdown, índice
  site.py        publica a edição e regenera o índice a partir de edicoes.json
  cli.py         gerar | renderizar | site
```

**Prefiltro antes do modelo.** Mandar 122 publicações inteiras ao LLM custa caro
e dilui o julgamento em nomeações e extratos de contrato. O prefiltro descarta
por regex (`nomeia`, `extrato de contrato`, `aviso de licitação`…), mas a
**retenção forte vence o descarte**: uma portaria que nomeia o gestor *e* habilita
leitos é, para quem capta recurso, uma habilitação. Cada descarte fica em
`prefiltro.json` com a regra que o causou — uma regra ruim é encontrável.

**Três defesas contra o modelo**, na ordem em que custam: validação do JSON
Schema, reconciliação por `id` (o id encabeça cada bloco do prompt; sem ele a
correspondência vira adivinhação) e bisseção do lote, porque o mais comum é um
único ato gigante estourar o contexto e levar junto os vizinhos.

**O modelo é o Claude Haiku, chamado pelo Claude Code em modo `-p`**, não pela
API: a assinatura já está na máquina e não há chave de API para guardar. A
chamada roda desarmada — sem ferramentas, sem MCP, sem sessão persistida, sem
herdar configuração do projeto, com teto de gasto e num diretório temporário como
`cwd`. O que entra no prompt é texto de diário oficial vindo da internet; se
esse texto contiver instruções, o pior desfecho possível é uma classificação
errada, nunca uma escrita em disco ou uma chamada de rede.

## 4. Taxonomia

| categoria | rótulo na edição       | critério                                                     |
|-----------|------------------------|--------------------------------------------------------------|
| A         | Captação de recursos   | habilitação/credenciamento, teto MAC ou AC, limite financeiro, incremento, emenda parlamentar, repasse fundo a fundo, deliberação CIB-SUS/MG que aloca recurso a município ou hospital nominal |
| B         | Mudança de regra       | portaria, resolução ou RDC que altera critério, piso, prazo, requisito ou tabela |
| C         | Editais e chamamentos  | edital ou chamamento público                                 |
| D         | Outros atos            | fato administrativo relevante ao setor, sem recurso e sem regra nova |
| X         | —                      | irrelevante; fica em `itens.json`, fora da edição             |

Duas regras de desempate no prompt: na dúvida entre D e X, use X; **qualquer
alocação nominal de recurso a um município ou hospital é A**, mesmo que o ato
trate também de outro assunto.

`relevancia` é 3 quando afeta diretamente a captação de um hospital ou município
de Minas, 2 quando afeta o SUS nacionalmente, 1 quando é contexto, 0 só para X.
Em A o desempate na ordenação é o valor em reais: entre duas habilitações
igualmente relevantes, quem lê quer ver primeiro a que move mais dinheiro.

## 5. Regras invioláveis

1. **Nada de juízo no `radar`.** A coleta não sabe o que é relevante. Se um
   campo de score aparecer em `radar/`, a fronteira ruiu.
2. **Nunca inventar.** Os fatos do item (órgão, tipo, número, data, página, URL)
   vêm sempre da publicação coletada; do modelo vem apenas categoria, resumo,
   relevância, valor, entes e tags. Todo número escrito tem de constar do texto
   fornecido.
3. **Item nenhum desaparece.** Resposta ruim do modelo não some com a publicação:
   ela vira **fallback D**, marcada (`fallback: true`), e o dia inteiro fica
   `parcial`. Quem lê precisa saber que o ato existiu, mesmo quando o modelo não
   opinou sobre ele.
4. **Um portador de luz por e-mail.** Um botão só, o do WhatsApp. "Ler a versão
   completa" e o segundo contato são links de texto.
5. **Hífen, nunca travessão.** Mais: sentença em vez de Title Case, número em vez
   de adjetivo, sem emoji e sem pergunta retórica. `validar_voz` reprova o texto
   do modelo, devolve *todos* os erros de uma vez como instrução de correção e dá
   uma segunda chance; reprovado duas vezes, a abertura sai determinística. A
   autoridade da voz é o `DESIGN.md` da Thauma, não o template.
6. **Segredos só em variável de ambiente.** `INLABS_EMAIL`, `INLABS_SENHA` e
   `CLAUDE_CODE_OAUTH_TOKEN` nunca entram no YAML, no código ou no log. O
   workflow não tem um `echo` com `secrets.` em lugar nenhum, e há teste para
   isso.
7. **Renderizar antes de gravar.** `gerar` monta e-mail, página e markdown em
   memória antes do primeiro arquivo; `site.publicar` lê e mescla `edicoes.json`
   e renderiza o índice antes de tocar em `site/`. Template quebrado ou
   `edicoes.json` corrompido falha com tudo intacto, nunca com meia edição no ar.

## 6. Contrato de exit codes

O mesmo contrato do `radar`, e pela mesma razão: quem chama decide pelo código.

| exit | stdout                       | significado                                   | a rotina        |
|------|------------------------------|-----------------------------------------------|-----------------|
| 0    | `boletim: N publicações…`    | edição inteira                                | publica         |
| 0    | `boletim: vazio`             | nenhuma fonte com conteúdo (feriado, domingo) | não publica, job verde |
| 1    | `boletim: … status=parcial`  | fonte ausente/parcial, ou item em fallback D  | publica com ressalva |
| 2    | `erro: …` (stderr)           | não saiu edição                               | derruba o job antes de publicar |

O `main` do CLI captura toda exceção e devolve 2 de propósito: uma exceção que
escapasse sairia com 1, e 1 significa "publicou com ressalva" — uma quebra total
seria lida como edição aproveitável.

O LLM fora do ar **antes** do primeiro lote é falha total (2). Depois do primeiro
lote é parcial (1): o resto do dia vira fallback D e a edição sai.

## 7. Rotina em nuvem

`.github/workflows/boletim-diario.yml`, dois horários por dia (09:30 e 12:00 BRT,
escritos em UTC), segunda a sábado. A execução das 12:00 é a rede de segurança de
quando o diário ainda não estava publicado às 09:30, e se anula sozinha quando
`site/edicoes/<data>.html` já existe — `forcar` no disparo manual ignora essa
checagem.

Sequência: freio → data → Python e Node → `radar coletar --fonte inlabs,iofmg` →
artefato do normalizado (90 dias) → `boletim gerar` → commit → `deploy-pages`.
Exit 2 em qualquer das duas execuções derruba o job antes do commit;
`boletim: vazio` pula commit e publicação. `concurrency` sem cancelamento: os
dois horários escrevem no mesmo `site/` e o segundo espera o primeiro.

**Freio remoto:** um arquivo `PARAR` na raiz da `main` (primeira linha = motivo)
faz o job imprimir o motivo e pular tudo, terminando verde. Remover religa. É a
convenção `00-Governanca/PARAR.md` do cérebro corporativo da Thauma: desligar tem
de ser um commit que qualquer um vê e reverte, não uma mudança escondida em
Settings.

**Alarme:** falha abre uma issue `Boletim <data> falhou` com o link da execução,
sem duplicar se já houver uma aberta. Numa rotina diária, o pior desfecho é a
falha silenciosa — ninguém abre a aba Actions todo dia.

**A fonte em nuvem é o INLABS, não o portal.** O `in.gov.br` bloqueia IP de
datacenter; o INLABS atende. `--fonte dou` continua existindo para uso local.

## 8. Riscos

1. **Custo e cota do modelo** (médio) — cada execução consome a cota da
   assinatura, e um dia grande são 8 a 10 chamadas de Haiku. Mitigação: prefiltro
   antes do LLM, `max_itens_dia`, `--max-budget-usd` na chamada, lote de 12.
2. **Classificação errada** (médio) — Haiku confunde D com X e ocasionalmente
   promove a A um ato que só cita dinheiro. Mitigação: exemplos e regras de
   desempate no prompt; `prefiltro.json` e os itens X preservados em
   `itens.json` tornam o erro auditável; cada erro observado vira uma linha nova
   em `prompts.py`, cujo histórico é o histórico do critério editorial.
3. **Número inventado no resumo** (alto se ocorrer) — é o defeito que destrói a
   confiança do gestor. Mitigação: a instrução "todo número que você escrever tem
   de constar do texto fornecido", os valores já extraídos por regex e oferecidos
   no prompt ("Valores detectados"), e os fatos duros vindo sempre da publicação,
   nunca do modelo.
4. **Token da assinatura no Actions** (médio) — é credencial de assinatura, não
   de API. Mitigação: segredo do repositório, nunca ecoado; freio `PARAR` para
   desligar a rotina em minutos.
5. **E-mail em cliente hostil** (baixo) — Outlook ignora `max-width`, Gmail
   reescreve cor. Mitigação: tabela, coluna única, estilo inline, comentário
   condicional MSO, e teste que proíbe `width="600"` fora dele.
