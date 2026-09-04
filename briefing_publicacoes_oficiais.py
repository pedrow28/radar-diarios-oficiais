#!/usr/bin/env python3
"""
Briefing de Publicacoes Oficiais — DOU Saude (v2 limpo)

Formato do email:
- Corpo: resumo estrategico
- Anexo: lista completa de publicacoes em HTML

Uso: python3 briefing_publicacoes_oficiais.py [DD/MM/YYYY]
"""
import sys
import os
import asyncio
import json
from datetime import datetime

sys.path.insert(0, os.path.expanduser('~/.hermes/scripts'))

from email_sender import load_credentials, send_email
from dou_daily_playwright import scrape_dou_complete, generate_strategic_summary as generate_dou_summary, generate_gmms_summary

# Carregar API key do OpenRouter a partir do .env do Hermes
from dotenv import load_dotenv
load_dotenv(os.path.expanduser('~/.hermes/.env'))

OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'
# Fallback chain de modelos gratuitos do OpenRouter (ordenados por chance de sucesso + qualidade)
FREE_MODELS = [
    'nvidia/nemotron-3-super-120b-a12b:free',
    'moonshotai/kimi-k2.6:free',
    'qwen/qwen3-next-80b-a3b-instruct:free',
    'nousresearch/hermes-3-llama-3.1-405b:free',
    'google/gemma-4-31b-it:free',
    'openai/gpt-oss-20b:free',
    'meta-llama/llama-3.3-70b-instruct:free',
]


def call_openrouter_free(prompt: str, models: list = None, max_tokens: int = 900, retries_per_model: int = 2) -> str:
    """Chama a API do OpenRouter tentando múltiplos modelos gratuitos em sequência.
    
    Implementa retry com backoff para lidar com rate limits (429) comuns em modelos free.
    Retorna o texto ou lança exceção após esgotar todos os modelos e tentativas.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError('OPENROUTER_API_KEY não configurada. Verifique ~/.hermes/.env')

    models = models or FREE_MODELS
    headers = {
        'Authorization': f'Bearer {OPENROUTER_API_KEY}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://thaumaconsultoria.com.br',
        'X-Title': 'DOU-Briefing-Strategic',
    }
    system_msg = (
        'Você é um analista sênior de inteligência regulatória e estratégica no setor de saúde do Brasil. '
        'Escreve com precisão, clareza e tom executivo. Sempre responde em português do Brasil.'
    )

    import requests
    import time

    last_error = None
    for model in models:
        for attempt in range(1, retries_per_model + 1):
            try:
                payload = {
                    'model': model,
                    'messages': [
                        {'role': 'system', 'content': system_msg},
                        {'role': 'user', 'content': prompt}
                    ],
                    'max_tokens': max_tokens,
                    'temperature': 0.35,
                }
                resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
                if resp.status_code == 429:
                    wait = 4 * (2 ** (attempt - 1))
                    print(f'      ⏳ [{model}] Rate limit (429). Aguardando {wait}s (tentativa {attempt+1}/{retries_per_model})...')
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if 'choices' not in data or not data['choices']:
                    raise RuntimeError(f'Resposta inesperada da API: {json.dumps(data)[:200]}')
                print(f'      ✅ Briefing gerado via {model}')
                return data['choices'][0]['message']['content'].strip()
            except requests.exceptions.RequestException as e:
                last_error = e
                wait = 4 * (2 ** (attempt - 1))
                print(f'      ⏳ [{model}] Erro de rede ({e}). Tentativa {attempt+1}/{retries_per_model} em {wait}s...')
                time.sleep(wait)
        print(f'   ⚠️ Modelo {model} esgotado. Tentando próximo...')

    raise RuntimeError(f'Falha após tentar {len(models)} modelos: {last_error}')


def generate_llm_briefing(publications: list, date_str: str) -> str:
    """Gera um briefing estratégico em texto corrido via LLM gratuito do OpenRouter.
    
    Seleciona as publicações mais relevantes (Seção 1 + destaques Seção 3) para
    manter o prompt enxuto e evitar estourar o contexto do modelo free.
    """
    # Separar por seção
    sec1 = [p for p in publications if 'Seção 1' in p['section']]
    sec2 = [p for p in publications if 'Seção 2' in p['section']]
    sec3 = [p for p in publications if 'Seção 3' in p['section']]

    # Selecionar as mais relevantes para o prompt
    # Seção 1: todas (normativos são sempre estratégicos)
    # Seção 3: apenas as que parecem ter valor estratégico (não extratos genéricos de baixo valor)
    sec3_relevantes = [
        p for p in sec3
        if any(k in p['title'].upper() for k in [
            'EDITAL', 'REGISTRO DE PREÇOS', 'RESCISÃO', 'SUSPENSÃO',
            'TERMO ADITIVO', 'CONVÊNIO', 'ACORDO', 'PORTARIA'
        ])
    ][:20]  # limitar

    # Montar lista condensada
    lines = []
    lines.append(f'DATA: {date_str}')
    lines.append(f'TOTAL DE PUBLICAÇÕES: {len(publications)} (Seção 1: {len(sec1)} | Seção 2: {len(sec2)} | Seção 3: {len(sec3)})')
    lines.append('')

    if sec1:
        lines.append('--- SEÇÃO 1 — ATOS NORMATIVOS ---')
        for p in sec1[:25]:  # limitar para não estourar contexto
            snippet = (p.get('snippet', '') or '')[:140]
            lines.append(f'• {p["title"]} | {snippet}')
        if len(sec1) > 25:
            lines.append(f'... e mais {len(sec1)-25} publicações normativas.')
        lines.append('')

    if sec2:
        lines.append('--- SEÇÃO 2 — ATOS DE PESSOAL ---')
        for p in sec2[:10]:
            lines.append(f'• {p["title"]}')
        if len(sec2) > 10:
            lines.append(f'... e mais {len(sec2)-10} publicações de pessoal.')
        lines.append('')

    if sec3_relevantes:
        lines.append('--- SEÇÃO 3 — CONTRATOS E EDITAIS (RELEVANTES) ---')
        for p in sec3_relevantes:
            snippet = (p.get('snippet', '') or '')[:120]
            lines.append(f'• {p["title"]} | {snippet}')
        lines.append('')

    raw_data = '\n'.join(lines)

    prompt = f"""Com base nas publicações do Diário Oficial da União (DOU) do Ministério da Saúde de {date_str}, elabore um **BRIEFING ESTRATÉGICO** em português, em **texto corrido bem formatado**, com parágrafos fluidos e conectados.

DADOS BRUTOS:
{raw_data}

INSTRUÇÕES DE ESTILO E CONTEÚDO:
1. **Resuma o dia** em 3 a 5 parágrafos curtos e diretos. Cada parágrafo deve ter uma ideia central clara.
2. **Aponte questões estratégicas**: movimentos orçamentários, mudanças regulatórias da ANVISA, contratos relevantes, alertas de suspensão/rescisão, normativas do Gabinete do Ministro (GM/MS), programas como PNAISP ou Mais Médicos.
3. **Não use listas ou bullet points**. O texto deve fluir como um relatório executivo.
4. **Destaque o que realmente importa** para quem acompanha o setor de saúde (gestores hospitalares, consultoria, indústria farmacêutica, prestadores de serviço).
5. **Finalize com uma recomendação prática** em uma frase ou duas.
6. Se não houver nada de grande relevância estratégica, diga isso de forma elegante e breve.

FORMATO: Apenas o texto do briefing, sem introduções como "Aqui está o briefing" ou assinaturas."""

    try:
        briefing = call_openrouter_free(prompt, max_tokens=900)
        # Limpar possíveis artefatos de markdown
        briefing = briefing.replace('**', '')
        return briefing
    except Exception as e:
        print(f'   ⚠️ LLM briefing falhou ({e}). Usando fallback heurístico.')
        # Fallback para o resumo heurístico existente
        fallback = generate_dou_summary(sec1, sec2, sec3)
        # Converter HTML do fallback em texto simples (remover tags <br> etc)
        import re
        fallback_text = re.sub(r'<br\s*/?>', '\n', fallback)
        fallback_text = re.sub(r'<[^>]+>', '', fallback_text)
        return fallback_text.strip() or 'Análise estratégica em desenvolvimento.'


def generate_dou_html_attachment(publications, date_str):
    """Gera HTML com lista completa de publicacoes DOU (anexo)."""
    sec1 = [p for p in publications if 'Seção 1' in p['section']]
    sec2 = [p for p in publications if 'Seção 2' in p['section']]
    sec3 = [p for p in publications if 'Seção 3' in p['section']]

    def esc(text):
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
.container {{ max-width: 950px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
.header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 25px; border-radius: 10px; margin-bottom: 25px; }}
.header h1 {{ margin: 0; font-size: 24px; }}
.section-title {{ color: white; padding: 12px 15px; border-radius: 8px; font-size: 18px; margin-bottom: 15px; font-weight: 600; }}
.sec1 {{ background: #e74c3c; }}
.sec2 {{ background: #f39c12; }}
.sec3 {{ background: #27ae60; }}
.pub-item {{ background: #f8f9fa; padding: 12px 15px; margin-bottom: 8px; border-radius: 6px; border-left: 3px solid #ddd; }}
.pub-item.destaque {{ border-left: 4px solid #e74c3c; background: #fff5f5; }}
.pub-title {{ font-weight: 600; color: #2c3e50; margin-bottom: 5px; }}
.pub-title a {{ color: #667eea; text-decoration: none; }}
.pub-snippet {{ color: #666; font-size: 13px; line-height: 1.4; }}
.stats {{ display: flex; gap: 15px; margin-bottom: 25px; flex-wrap: wrap; }}
.stat-box {{ flex: 1; min-width: 150px; background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; border-left: 4px solid #667eea; }}
.stat-box h3 {{ margin: 0; color: #667eea; font-size: 28px; }}
.stat-box p {{ margin: 5px 0 0 0; color: #666; font-size: 14px; }}
.footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; color: #999; font-size: 12px; text-align: center; }}
</style></head>
<body>
<div class="container">
<div class="header">
<h1>🩺 DOU Saude — Lista Completa de Publicacoes</h1>
<p>Diario Oficial da Uniao | {date_str} | Ministerio da Saude</p>
</div>
<div class="stats">
<div class="stat-box"><h3>{len(publications)}</h3><p>Total</p></div>
<div class="stat-box"><h3>{len(sec1)}</h3><p>Secao 1 - Normativos</p></div>
<div class="stat-box"><h3>{len(sec2)}</h3><p>Secao 2 - Pessoal</p></div>
<div class="stat-box"><h3>{len(sec3)}</h3><p>Secao 3 - Contratos</p></div>
</div>
"""

    for sec_name, sec_pubs, sec_class in [
        ("Secao 1 - Atos Normativos", sec1, "sec1"),
        ("Secao 2 - Atos de Pessoal", sec2, "sec2"),
        ("Secao 3 - Contratos e Editais", sec3, "sec3"),
    ]:
        html += f'<div class="section"><div class="section-title {sec_class}">{sec_name} ({len(sec_pubs)})</div>'
        for pub in sec_pubs:
            title = esc(pub['title'])
            snippet = esc(pub.get('snippet', '')[:200])
            html += f'<div class="pub-item"><div class="pub-title"><a href="{pub["url"]}" target="_blank">{title}</a></div><div class="pub-snippet">{snippet}...</div></div>'
        html += '</div>'

    html += '''<div class="footer">
<p>📧 Virgilio | DOU Saude Monitor | Lista completa de publicacoes</p>
</div></div></body></html>'''

    return html


def generate_email_body(dou_briefing_text, dou_count, gmms_html, date_str):
    """Gera o corpo do email com briefing estratégico em texto corrido (LLM)."""
    # Converter quebras de linha do briefing em parágrafos HTML
    paragraphs = dou_briefing_text.split('\n')
    briefing_html = ''
    for para in paragraphs:
        para = para.strip()
        if para:
            briefing_html += f'<p style="margin: 10px 0; color: #333; line-height: 1.7;">{para}</p>\n'

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
.container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
.header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 25px; border-radius: 10px; margin-bottom: 25px; text-align: center; }}
.header h1 {{ margin: 0; font-size: 22px; }}
.header p {{ margin: 8px 0 0 0; opacity: 0.9; font-size: 14px; }}
.section {{ margin-bottom: 25px; padding: 20px; border-radius: 10px; background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); border-left: 5px solid #667eea; }}
.section h2 {{ margin-top: 0; font-size: 18px; color: #2c3e50; }}
.section p {{ color: #444; line-height: 1.6; font-size: 14px; margin: 8px 0; }}
.stats {{ display: flex; gap: 15px; margin-bottom: 20px; flex-wrap: wrap; justify-content: center; }}
.stat-box {{ flex: 1; min-width: 120px; background: white; padding: 15px; border-radius: 8px; text-align: center; border-left: 4px solid #667eea; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.stat-box h3 {{ margin: 0; color: #667eea; font-size: 24px; }}
.stat-box p {{ margin: 5px 0 0 0; color: #666; font-size: 13px; }}
.note {{ background: #fffbeb; border-left: 4px solid #f59e0b; padding: 12px 15px; border-radius: 6px; margin-top: 20px; font-size: 13px; color: #92400e; }}
.footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; color: #999; font-size: 12px; text-align: center; }}
.briefing-body {{ font-size: 15px; line-height: 1.7; color: #2c3e50; }}
</style></head>
<body>
<div class="container">
<div class="header">
<h1>📩 Briefing DOU Saúde</h1>
<p>Briefing Estratégico | {date_str}</p>
</div>

<div class="stats">
<div class="stat-box"><h3>{dou_count}</h3><p>Publicações DOU</p></div>
</div>

{gmms_html}

<div class="section">
<h2>🎯 Briefing Estratégico — DOU Saúde</h2>
<div class="briefing-body">
{briefing_html}
</div>
</div>

<div class="note">
<strong>📎 Anexo:</strong> A lista completa de publicações está disponível no anexo deste email.<br>
• <em>dou_lista_completa.html</em> — todas as publicações do Ministério da Saúde no DOU
</div>

<div class="footer">
<p>🤖 Virgílio | Briefing DOU Saúde</p>
<p style="font-size: 11px; margin-top: 5px;">Briefing gerado via análise LLM (OpenRouter) com fallback heurístico</p>
</div>
</div>
</body></html>"""


async def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime('%d/%m/%Y')
    print(f"🚀 Briefing DOU Saúde | {date_str}")
    print("=" * 60)

    # 1. Scrape DOU
    print("\n[1/3] Scraping DOU Saúde...")
    dou_publications = await scrape_dou_complete(date_str)
    gmms_html, _ = generate_gmms_summary([p for p in dou_publications if 'Seção 1' in p['section']])
    print(f"   ✅ DOU: {len(dou_publications)} publicações")

    # 2. Gerar briefing estratégico via LLM (com fallback heurístico)
    print("\n[2/3] Gerando briefing estratégico via LLM...")
    dou_briefing = generate_llm_briefing(dou_publications, date_str)
    preview = dou_briefing.replace('\n', ' ')[:120]
    print(f"   📝 Preview: {preview}...")

    # 3. Gerar anexo HTML + corpo do email
    print("\n[3/3] Montando email com anexo...")
    dou_html = generate_dou_html_attachment(dou_publications, date_str)
    dou_attach_path = f"/tmp/dou_lista_completa_{date_str.replace('/', '-')}.html"
    with open(dou_attach_path, "w", encoding="utf-8") as f:
        f.write(dou_html)

    email_body = generate_email_body(dou_briefing, len(dou_publications), gmms_html, date_str)

    # 4. Enviar email
    print("\n📩 Enviando email...")
    try:
        creds = load_credentials()
        subject = f"🩺 DOU Saúde ESTRATÉGICO | {date_str} | {len(dou_publications)} publicações"
        attachments = [
            {"path": dou_attach_path, "filename": "dou_lista_completa.html", "mimetype": "text/html"},
        ]
        send_email("pedrowilliamrd@gmail.com", subject, email_body, creds, attachments)
        print("✅ Email enviado com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao enviar email: {e}")
        debug_path = f"/tmp/briefing_dou_{date_str.replace('/', '-')}.html"
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(email_body)
        print(f"   📄 Corpo salvo em: {debug_path}")

    # Limpar temporário
    if os.path.exists(dou_attach_path):
        os.remove(dou_attach_path)

    print("\n✅ Briefing concluído.")


if __name__ == "__main__":
    asyncio.run(main())
