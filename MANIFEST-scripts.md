# Scripts do Radar de Diários Oficiais

Pedro, segue os 5 scripts Python do pipeline DOU + IOF MG.

## O que está anexado

| # | Arquivo | Tamanho | Função |
|---|---------|---------|--------|
| 1 | `briefing_publicacoes_oficiais.py` | 16K | Orquestrador DOU (scrape → LLM → email) |
| 2 | `dou_daily_playwright.py` | 21K | Scraper DOU via Playwright (100% das pubs) |
| 3 | `dou_complete_scraper.py` | 8K | v1 legada do scraper (substituída) |
| 4 | `iof_mg_scraper.py` | 17K | Scraper IOF MG (API + PKCS#7 + PDF) |
| 5 | `iof-mg-briefing-estrategico.py` | 22K | Engine IOF MG completa (FTS5 + LLM + vault) |
| 6 | `iof-mg-standalone-engine.py` | 17K | Engine IOF MG standalone (no_agent cron) |

**Total:** ~100K · 6 scripts · 2 pipelines (DOU + IOF MG)

## Onde estavam no disco

```
/root/.hermes/scripts/briefing_publicacoes_oficiais.py    ← orquestrador DOU
/root/.hermes/scripts/dou_daily_playwright.py             ← scraper DOU ativo
/root/.hermes/scripts/dou_complete_scraper.py             ← v1 legada
/root/.hermes/scripts/_obsoleto/iof_mg_scraper.py         ← IOF MG v1 (movida pra obsoleto)
/root/.hermes/skills/research/dou-saude-scraper/templates/iof-mg-briefing-estrategico.py
/root/.hermes/skills/research/dou-saude-scraper/templates/iof-mg-standalone-engine.py
```

## Dependências (requirements.txt inferido)

```
playwright>=1.40
requests>=2.31
pypdf>=4.0          # IOF MG v1
PyMuPDF>=1.23       # IOF MG engine (fitz)
python-dotenv>=1.0
PyYAML>=6.0
google-api-python-client>=2.100
markdown>=3.5
```

**Setup:**
```bash
pip install -r requirements.txt
playwright install chromium
```

## Observação importante

- O `briefing_publicacoes_oficiais.py` na raiz **só faz DOU**. O IOF MG virou engine standalone com cron separado.
- O `dou_complete_scraper.py` é v1 legada, não está em nenhum cron — pode ignorar ou comparar com a v2.
- O `iof_mg_scraper.py` foi marcado como obsoleto e substituído pelos 2 templates (briefing-estrategico + standalone).

Boa leitura!
— Virgílio
