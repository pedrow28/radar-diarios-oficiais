# Radar de Diários Oficiais — Design

**Data:** 2026-09-04
**Status:** aprovado (seções 1–3)
**Substitui:** os 6 scripts avulsos descritos em `MANIFEST-scripts.md`

## 1. Contexto e objetivo

Existem hoje 6 scripts Python que coletam publicações do Diário Oficial da União
(Ministério da Saúde) e do Diário Oficial de Minas Gerais (Secretaria de Estado
de Saúde). São duas pipelines sem código, modelo de dado ou convenção em comum:
seis pontos de entrada, três modelos de dado, quatro implementações de envio de
e-mail e duas de config. Cada correção precisa ser aplicada em 2–4 lugares.

O consumidor mudou. A saída deixa de ser um e-mail para um humano e passa a ser
**dado estruturado para o agente Hermes**, que roda numa VPS. O Hermes avalia o
que é relevante para captação de recursos e repassa a um agente de marketing que
monta a newsletter diária.

**Objetivo:** um pacote único que colete as duas fontes, normalize para um modelo
comum e entregue JSON com texto integral, de forma idempotente e com falha
observável.

## 2. Escopo

**Dentro:**

- Coleta DOU (órgão: Ministério da Saúde) e IOF-MG (Secretaria de Estado de Saúde)
- Normalização para um modelo comum, com **texto integral** de cada publicação
- Persistência: JSON por dia/fonte + SQLite com FTS5 para histórico
- CLI operável por cron e por agente
- Envio de e-mail como comando opcional, fora do núcleo

**Fora (decisão explícita do usuário):**

- Juízo de relevância, score de captação, classificação SUS — **fica no Hermes**
- Geração da newsletter — fica no agente de marketing
- Ampliação para outros órgãos/secretarias — escopo travado em Saúde
- Web UI, API HTTP, Flask

## 3. Arquitetura

Pacote único, adaptadores por fonte, núcleo compartilhado.

```
radar/
  core/
    modelos.py     Publicacao, Resultado, Status
    config.py      carga de config.yaml + env
    datas.py       America/Sao_Paulo, dia útil
    http.py        sessão com retry/backoff, encoding explícito
    storage.py     raw/, normalized/, radar.db (UPSERT + FTS5)
    erros.py       SemEdicao, ExtracaoParcial, FonteIndisponivel
    log.py
  fontes/
    dou/           busca.py · texto.py · normaliza.py
    iofmg/         api.py · pkcs7.py · pdf.py · segmenta.py · normaliza.py
  notificacao/     email.py (opcional)
  cli.py
config/config.yaml · .env.example
tests/  fixtures/ (dados reais capturados em 2026-09-04)
pyproject.toml
```

Contrato de fonte:

```python
class Fonte(Protocol):
    nome: str
    def coletar(self, data: date) -> Resultado: ...
```

Cada fonte também é executável isolada: `python -m radar.fontes.dou --data ...`.

## 4. Modelo de dados

```python
@dataclass(frozen=True)
class Publicacao:
    # identidade
    id: str                    # sha256(fonte|data|url|titulo)[:16], estável
    fonte: Literal["dou", "iofmg"]
    data_publicacao: date
    coletado_em: datetime      # UTC

    # procedência
    orgao: str
    unidade: str | None
    secao: str | None          # DOU: "1"|"2"|"3" (de pubName). IOF-MG: sempre None
    pagina: int | None
    edicao: str | None

    # conteúdo
    tipo: str | None
    numero: str | None
    titulo: str
    ementa: str | None
    texto: str                 # TEXTO INTEGRAL
    url: str

    # rastreabilidade
    origem: dict
```

**Regras invioláveis:**

1. **Campo desconhecido é `None`, nunca inventado.** O código atual adivinha a
   seção do DOU por palavra no título — uma `PORTARIA` da Seção 3 vira "Seção 1".
   Campo vazio é informação; campo inventado é mentira que o agente consome como
   verdade.
2. **`texto` é o inteiro teor.** Julgar relevância por snippet truncado é a
   principal causa de erro do agente downstream.
3. **Nenhum campo de juízo** (`score`, `is_sus`, `impacto`). Fica no Hermes.

**Desambiguação de "seção".** O termo aparece com dois sentidos e eles não se
misturam. No DOU, *seção* é a divisão editorial do diário (Seção 1/2/3) e vai
para `Publicacao.secao`. No IOF-MG, o que a API chama de `secoes` é a divisão
por **órgão** ("Secretaria de Estado de Saúde") e vai para `Publicacao.orgao` —
o IOF-MG não tem o conceito de Seção 1/2/3, portanto `secao` é sempre `None`
nessa fonte.

## 5. Contrato de saída

`data/normalized/<AAAA-MM-DD>/<fonte>.json`:

```json
{
  "schema_versao": "1.0",
  "fonte": "dou",
  "data_publicacao": "2026-09-04",
  "coletado_em": "2026-09-04T12:07:41Z",
  "status": "ok",
  "escopo": { "orgao": "Ministério da Saúde" },
  "total": 142,
  "avisos": [],
  "publicacoes": []
}
```

| `status`  | significado                        | exit | ação do Hermes            |
|-----------|------------------------------------|------|---------------------------|
| `ok`      | coleta completa                    | 0    | processar                 |
| `vazio`   | não houve edição (feriado/domingo) | 0    | seguir sem alarme         |
| `parcial` | coletou, mas algo falhou           | 1    | processar **e** alertar   |
| `erro`    | coleta quebrou                     | 2    | **não** gerar newsletter  |

Hoje esses quatro casos são indistinguíveis: `consulta_iof()` devolve `None` para
timeout, HTTP 500 e domingo, logando "Nenhum diário publicado" nos três. Com o
agente rodando sozinho, isso é newsletter silenciosamente vazia em dia de queda
de rede. `avisos[]` carrega o detalhe legível de todo `parcial`.

## 6. Fonte DOU

### 6.1 Listagem (sem browser)

A página de busca do `in.gov.br` embute os resultados em
`<script id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params" type="application/json">`,
com `jsonArray` de `delta` itens. **Playwright é desnecessário para a listagem.**
Cada item traz:

| campo          | uso                                              |
|----------------|--------------------------------------------------|
| `pubName`      | `DO1`/`DO2`/`DO3` → `secao` **real**             |
| `artType`      | `tipo` real ("Portaria", "Extrato de Contrato")  |
| `hierarchyStr` | `orgao` + `unidade`                              |
| `urlTitle`     | monta a URL canônica                             |
| `classPK`      | identificador da matéria                         |
| `numberPage`, `editionNumber`, `pubDate` | metadados              |
| `content`      | **truncado em ~420 chars** — não serve como texto |

Toda a classificação por palavra-chave é removida: `secao` e `tipo` vêm da fonte.

**Encoding:** a página de busca declara `charset=UTF-8` **mas é ISO-8859-1**.
Decodificar pelo header declarado produz mojibake. Forçar `iso-8859-1` na busca.

**Paginação:** iterar páginas por parâmetro de URL até cobrir o total. Acumular
em dict por URL. Se o conjunto de URLs de uma página for idêntico ao da anterior,
a paginação travou → aborta com `parcial` e aviso. Nunca declarar sucesso por
`len(acumulado) >= total` sobre lista com duplicatas.

### 6.2 Texto integral

Cada publicação é buscada na sua página canônica
(`https://www.in.gov.br/web/dou/-/<urlTitle>`), que é **UTF-8** (diferente da
busca). O corpo está em `div.texto-dou`, com parágrafos classificados:
`identifica` (título), `ementa`, `dou-paragraph`, `assina`, `anexo`. Tabelas em
`dou-table`.

Verificado: 2.391 chars de texto integral contra 426 truncados na listagem,
incluindo valores monetários (`R$ 274.372,80`) — o dado que sustenta o juízo de
captação.

Concorrência limitada (padrão 5), backoff em 5xx/timeout. HTML bruto salvo em
`data/raw/`. Falha em N textos → `parcial` com os IDs nos `avisos`; nunca uma
publicação com `texto` vazio se passando por completa.

## 7. Fonte IOF-MG

### 7.1 API e envelope

`GET /api/v1/Jornal/ObterEdicaoPorDataPublicacao?dataPublicacao=AAAA-MM-DD`

O campo `dados.arquivoCadernoPrincipal.arquivo` é base64 de um **envelope
PKCS#7/CMS** (`MIAGCSqGSIb3DQEHAq…`), em **BER de comprimento indefinido**
(`30 80`), não DER estrito.

Desembrulhar com `asn1crypto` (Python puro, aceita BER indefinido), não com
`subprocess` do `openssl`: uma dependência de sistema a menos na VPS e erro
capturável.

> **Nota factual:** o PyMuPDF tolera o envelope e localiza o `%PDF` interno
> sozinho — as engines atuais que fazem `b64decode` direto para o `fitz`
> **funcionam**. A troca para `asn1crypto` é higiene (explícito e testável), não
> correção de bug. `cryptography.pkcs7` não serve: expõe os certificados, não o
> conteúdo encapsulado.

Detecção por magic bytes mantém robustez se a API mudar: `%PDF` → direto;
`0x30` → desembrulhar.

### 7.2 Índice de seções

A resposta da API já traz o sumário estruturado:

```json
"cadernos": [{ "id": 330896, "descricao": "Diário do Executivo",
  "secoes": [ {"descricao": "Secretaria de Estado de Saúde", "paginaInicial": 16},
              {"descricao": "Secretaria de Estado de Educação", "paginaInicial": 17} ]}]
```

Isso **substitui integralmente** o `find_section_pages()`, que lia só a página 1,
confiava no sumário via regex e tinha lógica de `end_page` que quebrava no
primeiro casamento ignorando a ordem real.

Recorte: da `paginaInicial` da seção alvo até a da próxima seção (ou
`totalPaginas` se for a última). Validado: 03/09 → pp. 16–17; 02/09 → pp. 47–49.

**A última página do intervalo contém o início da seção seguinte.** Truncar no
cabeçalho da próxima seção dentro da página.

### 7.3 ID do caderno (bug corrigido)

`cadernos[].id` vale **330896** em 03/09 e **330892** em 02/09 — muda a cada
edição. Os scripts atuais usam a constante `326074` para montar todos os links
"Ver no Jornal MG", em qualquer data: **todos os links já gerados apontam para a
edição errada.** O ID passa a vir da resposta. Não encontrado → o link não é
emitido e registra-se aviso. Link errado é pior que link ausente: o agente cita
na newsletter e ninguém percebe.

### 7.4 Segmentação

Recuperado do `iof_mg_scraper.py` (marcado obsoleto) como **segmentador**, sem o
`classify_sus_relevance` junto — que era juízo e saiu de escopo.

Quebrar o texto da seção em publicações discretas por cabeçalho normativo. A
lista de tipos é **configurável**, não fixa: a sondagem encontrou
`DELIBERAÇÃO CIB-SUS/MG`, ausente da regex original e justamente onde a Comissão
Intergestores Bipartite aloca recurso do SUS.

**Risco conhecido, maior do projeto:** detecção por linha produziu 66 candidatos
com falsos positivos claros (`"DELIBERA:"`, `"Resoluções que menciona."`). A
âncora precisa ser mais forte: caixa alta seguida de número e/ou data. Tratado
com testes de acerto sobre as duas edições reais, medindo, não no olho.

Limpeza necessária no texto do PDF: cabeçalhos/rodapés de página recorrentes
("MINAS GERAIS", "Diário do Executivo", data e número da página), hifenização de
quebra de linha, junção de linhas quebradas por coluna.

### 7.5 FTS5

Muda de papel. Hoje **é** o mecanismo de extração (busca literal de 10 termos,
devolve janela de 400 chars) e por isso limita o que existe. Passa a ser índice
de histórico sobre `texto` de todas as publicações segmentadas, para consulta
retroativa. A extração deixa de depender dele.

## 8. Núcleo

### 8.1 Armazenamento

```
data/
  raw/<data>/dou/busca-p1.html · pub-<classPK>.html
  raw/<data>/iofmg/edicao.json · caderno.pdf
  normalized/<data>/dou.json · iofmg.json
  radar.db
```

`raw/` torna a re-execução barata: reprocessar um dia após melhorar o segmentador
não refaz uma requisição. Retenção configurável (padrão 30 dias).

`radar.db`: tabela `publicacoes` com `id` como PK e `UPSERT` — rodar o mesmo dia
duas vezes converge para o mesmo estado, nunca duplica. FTS5 sobre `texto`.

### 8.2 Config

`config.yaml` para comportamento; segredos só por variável de ambiente. Nenhum
e-mail, chave ou caminho de usuário no código (hoje `pedrowilliamrd@gmail.com`
está fixo em 2 arquivos, além de `/root/mente`, `/root/.hermes` e `/tmp`).

```yaml
timezone: America/Sao_Paulo
fontes:
  dou:
    orgao: "Ministério da Saúde"
    delta: 75
    concorrencia: 5
    baixar_texto_integral: true
  iofmg:
    caderno: "Diário do Executivo"
    secao: "Secretaria de Estado de Saúde"
    tipos_publicacao: [PORTARIA, RESOLUÇÃO, DECRETO, DELIBERAÇÃO, EXTRATO, EDITAL, ATO, AVISO]
armazenamento:
  dir_dados: ./data
  reter_bruto_dias: 30
```

### 8.3 Datas e falhas

`America/Sao_Paulo` em todo lugar. O `datetime.now(UTC).date()` atual faz o cron
pedir a data de amanhã em qualquer execução após as 21h BRT.

Exceções tipadas mapeando direto no `status` da seção 5: `SemEdicao` → `vazio`;
`ExtracaoParcial` → `parcial`; `FonteIndisponivel` → `erro`.

## 9. CLI

```bash
radar coletar --data 2026-09-04 --fonte todas    # dou | iofmg | todas
radar coletar --data 2026-09-04 --forcar         # ignora cache raw
radar consultar "teto MAC" --desde 2026-06-01    # FTS5 no histórico
radar notificar --data 2026-09-04                # e-mail opcional
```

`--data` omitido = hoje em `America/Sao_Paulo`.

## 10. Testes

Fixtures reais capturadas em 2026-09-04, versionadas em `tests/fixtures/`
(4,2 MB). Todos os testes rodam **offline**.

| fixture | testa |
|---|---|
| `dou/busca-ms-2026-09-04.html` | parse do `jsonArray`, encoding ISO-8859-1, mapeamento `pubName`→`secao` |
| `dou/pub-portaria-gm-ms-12141.html` | extração de `texto-dou`, encoding UTF-8, `identifica`/`ementa` |
| `iofmg/envelope-pkcs7-2026-09-03.bin.gz` | desembrulho PKCS#7 em BER indefinido |
| `iofmg/edicao-*.meta.json` | índice de seções, recorte de páginas, `id` do caderno por data |
| `iofmg/caderno-*-ses.pdf` | segmentação e limpeza de texto |

Cobertura mínima obrigatória:

- **encoding ISO-8859-1 na busca do DOU** (regressão garantida se alguém
  "consertar" para usar o header declarado)
- paginação travada → `parcial`, nunca sucesso falso
- recorte da última seção do caderno (sem próxima seção)
- `id` do caderno vindo da resposta, jamais constante
- mapeamento exceção → `status` → exit code
- taxa de acerto da segmentação sobre as duas edições reais

## 11. Migração

| script atual | destino |
|---|---|
| `dou_daily_playwright.py` | `fontes/dou/` — Playwright descartado; lógica de seção descartada (substituída por `pubName`) |
| `dou_complete_scraper.py` | descartado (v1 legada) |
| `briefing_publicacoes_oficiais.py` | LLM e e-mail saem do núcleo; briefing vira responsabilidade do Hermes |
| `iof_mg_scraper.py` | `parse_publications_ses` → `fontes/iofmg/segmenta.py`; `classify_sus_relevance` **descartado** (juízo saiu de escopo) |
| `iof-mg-standalone-engine.py` | FTS5 e storage → `core/`; CSV e SMTP → `notificacao/` |
| `iof-mg-briefing-estrategico.py` | FTS5 duplicado descartado; vault e Gmail saem do núcleo |

Os scripts originais permanecem na raiz até a nova pipeline rodar em paralelo por
uma semana.

## 12. Bugs do código atual endereçados por este design

| # | bug | onde | resolução |
|---|-----|------|-----------|
| 1 | Sem dedup; `len>=total` declara sucesso com duplicatas | `dou_daily_playwright.py:90` | dict por URL + detecção de página repetida |
| 2 | `--backtest` ignorado: `run()` recria `Config`, descartando o do `main()` | `iof-mg-briefing-estrategico.py:450` | config carregada uma vez e injetada |
| 3 | `idCadernoEdicaoSelecionado` fixo em `326074` | `standalone:237`, `estrategico:245` | lido de `cadernos[].id` |
| 4 | Seção do DOU inventada por palavra no título | `dou_daily_playwright.py:66` | `pubName` da fonte |
| 5 | Erro permanente (404/401) retentado com backoff | `briefing_publicacoes_oficiais.py:89` | erro permanente não é retentado |
| 6 | `datetime.now(UTC).date()` em diário brasileiro | `estrategico:445`, `standalone:381` | `America/Sao_Paulo` |
| 7 | `setup_logging()` chamado 2×: log duplicado, 2 arquivos | `estrategico:451,539` | configurado uma vez |
| 8 | Rede, HTTP 500 e domingo indistinguíveis | `estrategico:147` | exceções tipadas → `status` |
| 9 | `except: break` pelado engole falha de paginação | `dou_daily_playwright.py:106` | saída por condição explícita |
| 10 | `pub["url"]` cru interpolado em `href` | `daily_playwright.py:385` | escape de todo campo scraped |
| 11 | Sem idempotência: rodar 2× = 2 e-mails/duplicatas | ambos os lados | `UPSERT` por `id` |
| 12 | `max_pages=10` arbitrário limita a 750 itens | `dou_daily_playwright.py:57` | teto derivado de `total/delta` |

## 13. Riscos

1. **Segmentação do IOF-MG** (alto) — falsos positivos de cabeçalho. Mitigação:
   âncora com número/data, medição sobre fixtures reais.
2. **Estrutura HTML do `in.gov.br` mudar** (médio) — o `jsonArray` é interno ao
   portal. Mitigação: teste de contrato que falha alto; fallback documentado
   para Playwright.
3. **Volume de requisições no estágio 2** (baixo) — ~142 publicações/dia a 5
   concorrentes. Mitigação: cache `raw/`, backoff, `parcial` em vez de falha total.
4. **Sobreposição de seção na página de fronteira** (baixo) — última página traz
   início da seção seguinte. Mitigação: truncar no cabeçalho seguinte.
