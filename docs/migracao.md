# Migração dos scripts antigos

Os 6 scripts na raiz continuam funcionando e **não devem ser removidos** antes
de uma semana de execução em paralelo.

## Correspondência

| script antigo | substituto |
|---|---|
| `dou_daily_playwright.py` | `radar coletar --fonte dou` |
| `dou_complete_scraper.py` | descartado (v1 legada, sem cron) |
| `briefing_publicacoes_oficiais.py` | coleta pelo `radar`; briefing passa ao Hermes |
| `iof_mg_scraper.py` | `radar coletar --fonte iofmg` (segmentação herdada daqui) |
| `iof-mg-standalone-engine.py` | `radar coletar --fonte iofmg` |
| `iof-mg-briefing-estrategico.py` | coleta pelo `radar`; briefing passa ao Hermes |

## Comparação em paralelo

Rode os dois por uma semana e compare as contagens:

```bash
radar coletar --data $(date +%F) --fonte dou
python3 dou_daily_playwright.py $(date +%d/%m/%Y)
```

Espere **divergência**, e ela é esperada em três pontos:

1. **A contagem do script antigo pode ser maior.** Ele não deduplica na
   paginação; parte do total pode ser o mesmo item contado duas vezes.
2. **A distribuição por seção muda.** O script antigo infere a seção por palavra
   no título; o novo lê `pubName`. A distribuição nova é a correta.
3. **Os links do IOF-MG mudam.** Os antigos usam o caderno fixo `326074` e
   apontam para a edição errada em qualquer data. Validado contra a API real
   em 2026-09-03: a edição do dia usa o caderno `330896`, nunca `326074` —
   todo link do `radar` para essa data carrega `idCadernoEdicaoSelecionado=330896`.

## O que não foi portado, de propósito

`classify_sus_relevance()` do `iof_mg_scraper.py` classificava relevância SUS
por palavra-chave. Ficou de fora porque o juízo de relevância passou a ser
responsabilidade do Hermes, que trabalha sobre o texto integral — informação que
a heurística antiga não tinha.

Se um dia for preciso um pré-filtro no código, ele volta como camada opcional
sobre `Publicacao`, nunca como campo do modelo.

## Nota sobre "domingo sem edição" (IOF-MG)

O código (`radar/core/http.py`, função `obter_bytes`) trata HTTP 401 da API do
IOF-MG como "sem edição" — essa regra veio de um comentário no script legado
`iof_mg_scraper.py` e nunca tinha sido confirmada contra a API real.

Validação em 2026-09-04, contra um domingo real (2026-08-30, confirmado como
domingo): a API respondeu **HTTP 200** com corpo `{"dados": null, "erros":
[]}`, não HTTP 401. Quem trata esse caso na prática é
`radar/fontes/iofmg/api.py::dados_de`, que levanta `SemEdicao` quando o campo
`dados` vem nulo — o caminho realmente percorrido em produção. O branch de 401
em `obter_bytes` continua no código como defesa (a API pode um dia devolver
401 de fato, por exemplo em bloqueio de acesso), mas não é o que a API faz
hoje para "sem edição". Resultado observado nesse domingo: `status=vazio` nas
duas fontes, exit code 0.
