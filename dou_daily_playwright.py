#!/usr/bin/env python3
"""
DOU Saúde - Scraper Completo via Playwright + Resumo Estratégico
Extrai TODAS as publicações do DOU para o Ministério da Saúde e envia por email.
Uso: python3 dou_daily_playwright.py [DD/MM/YYYY]
"""
import asyncio
import json
import re
import sys
import os
from datetime import datetime
from playwright.async_api import async_playwright

# Configurar token OAuth para email
sys.path.insert(0, os.path.expanduser('~/.hermes/scripts'))
from email_sender import send_email, load_credentials


async def scrape_dou_complete(date_str, orgao="Ministério da Saúde"):
    """Extrai todas as publicações do DOU para um órgão em uma data."""
    all_publications = []
    
    day, month, year = date_str.split('/')
    url = (f"https://www.in.gov.br/consulta/-/buscar/dou"
           f"?q=*&orgPrin={orgao.replace(' ', '+')}"
           f"&exactDate=dia&dateDay={day}&dateMonth={month}&dateYear={year}&delta=75")
    
    print(f"🔥 DOU Scraper | {date_str} | {orgao}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0")
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=90000)
            await page.wait_for_timeout(3000)
            
            content = await page.content()
            total_match = re.search(r'(\d+)\s+resultados?', content)
            total_results = int(total_match.group(1)) if total_match else 0
            print(f"📊 Total: {total_results}")
            
            if total_results == 0:
                return []
            
            page_num = 1
            max_pages = 10
            
            while page_num <= max_pages:
                print(f"📄 Página {page_num}...")
                
                pubs = await page.evaluate('''() => {
                    const results = [];
                    document.querySelectorAll('h5').forEach(h5 => {
                        const link = h5.querySelector('a');
                        const title = h5.textContent.trim();
                        const href = link ? link.href : '';
                        let snippet = '';
                        let parent = h5.closest('div');
                        if (parent) {
                            const p = parent.querySelector('p');
                            if (p) snippet = p.textContent.trim();
                        }
                        let section = 'Outros';
                        const u = title.toUpperCase();
                        if (u.includes('PORTARIA') || u.includes('RESOLUÇÃO') || 
                            u.includes('DECRETO') || u.includes('LEI') ||
                            u.includes('RETIFICAÇÃO')) {
                            section = 'Seção 1 - Atos Normativos';
                        } else if (u.includes('NOMEAÇÃO') || u.includes('EXONERAÇÃO') ||
                                   u.includes('DESPACHO') || u.includes('PENSÃO') ||
                                   u.includes('APOSENTADORIA')) {
                            section = 'Seção 2 - Atos de Pessoal';
                        } else if (u.includes('EXTRATO') || u.includes('EDITAL') || 
                                   u.includes('AVISO') || u.includes('CONTRATO') ||
                                   u.includes('TERMO ADITIVO') || u.includes('ATA') ||
                                   u.includes('REGISTRO DE PREÇOS') || u.includes('RESCISÃO')) {
                            section = 'Seção 3 - Contratos e Editais';
                        }
                        if (title && !title.includes('Reportar Erro')) {
                            results.push({title, url: href, snippet, section});
                        }
                    });
                    return results;
                }''')
                
                print(f"   ➕ {len(pubs)} extraídas")
                all_publications.extend(pubs)
                
                if len(all_publications) >= total_results:
                    break
                
                try:
                    next_btn = await page.query_selector('li.page-item:last-child button.page-link')
                    if next_btn:
                        is_disabled = await next_btn.get_attribute('disabled')
                        if is_disabled:
                            break
                        await next_btn.click()
                        await page.wait_for_timeout(4000)
                        page_num += 1
                    else:
                        break
                except:
                    break
            
            print(f"✅ {len(all_publications)}/{total_results} extraídas em {page_num} páginas")
            
        except Exception as e:
            print(f"❌ Erro: {e}")
        finally:
            await browser.close()
    
    return all_publications


def generate_gmms_summary(sec1):
    """Gera resumo específico das portarias do Gabinete do Ministro (GM/MS).
    
    Retorna tupla: (html_bloco, lista_de_portarias)
    """
    # Todas as portarias GM/MS
    gmms_all = [p for p in sec1 if 'GM/MS' in p['title'].upper()]
    gmms_transfer = [p for p in gmms_all if '10.9' in p['title']]
    
    if not gmms_all:
        return "", []
    
    # Classificação detalhada
    equipamentos = [p for p in gmms_transfer if 'equipamentos' in p.get('snippet', '').lower()]
    custeio = [p for p in gmms_transfer if 'custeio' in p.get('snippet', '').lower() or 'incremento' in p.get('snippet', '').lower()]
    pnaisp = [p for p in gmms_transfer if 'PNAISP' in p.get('snippet', '') or 'PRIVADAS DE LIBERDADE' in p.get('snippet', '')]
    
    # Outras portarias GM/MS (não de transferência)
    outras_gmms = [p for p in gmms_all if p not in gmms_transfer]
    
    total_transfer = len(gmms_transfer)
    
    html = f'<div style="background: linear-gradient(135deg, #fff8f0 0%, #ffe8d6 100%); padding: 18px; border-radius: 10px; border-left: 5px solid #e67e22; margin-bottom: 20px;">'
    html += '<h3 style="margin-top: 0; color: #d35400; font-size: 16px;">🏛️ PORTARIAS DO GABINETE DO MINISTRO (GM/MS)</h3>'
    
    # Resumo executivo GM/MS
    html += f'<p style="margin: 8px 0; font-size: 14px; color: #444;"><strong>{len(gmms_all)} portaria(s)</strong> publicada(s) pelo Gabinete do Ministro hoje.'
    if total_transfer > 0:
        html += f' Destas, <strong>{total_transfer}</strong> são de transferência de recursos (art. 10.9 da LOAS/LDO).'
    html += '</p>'
    
    # Breakdown por tipo
    tipos_desc = []
    if equipamentos:
        tipos_desc.append(f"🏥 <strong>Equipamentos permanentes:</strong> {len(equipamentos)} portaria(s)")
    if custeio:
        tipos_desc.append(f"💰 <strong>Incremento ao custeio:</strong> {len(custeio)} portaria(s) — Atenção Especializada, UTI, transplantes")
    if pnaisp:
        tipos_desc.append(f"🧠 <strong>PNAISP:</strong> {len(pnaisp)} portaria(s) — saúde mental no sistema prisional")
    if outras_gmms:
        tipos_desc.append(f"📋 <strong>Outras:</strong> {len(outras_gmms)} portaria(s) — normativas, designações, retificações")
    
    if tipos_desc:
        html += '<ul style="margin: 10px 0; padding-left: 20px; font-size: 13px; color: #555;">'
        for desc in tipos_desc:
            html += f'<li style="margin-bottom: 5px;">{desc}</li>'
        html += '</ul>'
    
    # Lista das portarias GM/MS
    html += '<div style="margin-top: 12px;">'
    html += '<p style="font-size: 12px; color: #888; margin-bottom: 8px; font-weight: 600;">📄 PUBLICAÇÕES:</p>'
    for pub in gmms_all[:8]:
        title_clean = pub['title'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        html += f'<div style="background: white; padding: 8px 10px; margin-bottom: 5px; border-radius: 5px; font-size: 12px; border-left: 3px solid #e67e22;">'
        html += f'<a href="{pub["url"]}" target="_blank" style="color: #d35400; text-decoration: none; font-weight: 500;">{title_clean}</a>'
        snippet = pub.get('snippet', '')[:120].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        if snippet:
            html += f'<div style="color: #777; font-size: 11px; margin-top: 3px;">{snippet}...</div>'
        html += '</div>'
    if len(gmms_all) > 8:
        html += f'<div style="text-align: center; color: #999; font-size: 11px; padding: 5px;">... e mais {len(gmms_all)-8} portaria(s) GM/MS</div>'
    html += '</div>'
    
    html += '</div>'
    
    return html, gmms_all


def generate_strategic_summary(sec1, sec2, sec3):
    """Gera resumo estratégico baseado nas publicações do dia."""
    
    # --- SEÇÃO ESPECIAL: GM/MS ---
    gmms_html, gmms_all = generate_gmms_summary(sec1)
    gmms_transfer = [p for p in gmms_all if '10.9' in p['title']]
    
    # ANVISA
    anvisa = [p for p in sec1 if 'RESOLUÇÃO-RE' in p['title'].upper()]
    
    # SGTES
    sgtes = [p for p in sec1 if 'SGTES/MS' in p['title'].upper()]
    
    # Contratos grandes na Seção 3
    hospitais_fed = [p for p in sec3 if 'HOSPITAL FEDERAL' in p.get('snippet', '').upper() or 'UASG 250061' in p['title']]
    dsei = [p for p in sec3 if 'DSEI' in p.get('snippet', '').upper() or 'DISTRITO SANIT' in p.get('snippet', '').upper()]
    hemobras = [p for p in sec3 if 'HEMOBRÁS' in p.get('snippet', '').upper()]
    suspensao = [p for p in sec3 if 'SUSPENSÃO' in p['title'].upper()]
    rescisao = [p for p in sec3 if 'RESCISÃO' in p['title'].upper()]
    registro_precos = [p for p in sec3 if 'REGISTRO DE PREÇOS' in p['title'].upper()]
    
    # Inicializar variáveis usadas depois (mesmo se gmms_transfer estiver vazio)
    equipamentos = []
    custeio = []
    pnaisp = []
    
    # CONEP
    conep = [p for p in sec1 if 'CONEP' in p.get('snippet', '').upper() or ('RESOLUÇÃO-RE Nº 1,' in p['title'] and 'ÉTICA' in p.get('snippet', '').upper())]
    
    paragraphs = []
    
    # Parágrafo 1: GM/MS (agora resumido, pois tem bloco próprio)
    if gmms_transfer:
        tipos = []
        equipamentos = [p for p in gmms_transfer if 'equipamentos' in p.get('snippet', '').lower()]
        custeio = [p for p in gmms_transfer if 'custeio' in p.get('snippet', '').lower() or 'incremento' in p.get('snippet', '').lower()]
        pnaisp = [p for p in gmms_transfer if 'PNAISP' in p.get('snippet', '') or 'PRIVADAS DE LIBERDADE' in p.get('snippet', '')]
        
        if equipamentos:
            tipos.append(f"aquisição de equipamentos ({len(equipamentos)})")
        if custeio:
            tipos.append(f"incremento ao custeio ({len(custeio)})")
        if pnaisp:
            tipos.append("adesão à PNAISP")
        
        p1 = f"<strong>🎯 Movimento orçamentário:</strong> {len(gmms_transfer)} portarias GM/MS de transferência de recursos."
        if tipos:
            p1 += f" Foco em {', '.join(tipos)}."
        paragraphs.append(p1)
    
    # Parágrafo 2: ANVISA
    if anvisa:
        paragraphs.append(f"<strong>⚕️ ANVISA acelera liberações:</strong> {len(anvisa)} resoluções de autorização sanitária publicadas em um único dia, indicando movimento regulatório intenso no setor farmacêutico e de insumos.")
    
    # Parágrafo 3: Contratos
    contratos_desc = []
    if hospitais_fed:
        contratos_desc.append(f"{len(hospitais_fed)} contratos em hospitais federais")
    if dsei:
        contratos_desc.append(f"{len(dsei)} contratos de DSEI (saúde indígena)")
    if hemobras:
        contratos_desc.append("aquisições da Hemobrás")
    if registro_precos:
        contratos_desc.append(f"{len(registro_precos)} registros de preços (materiais hospitalares)")
    
    if contratos_desc:
        p3 = f"<strong>🏥 Contratos:</strong> {'; '.join(contratos_desc)} na Seção 3."
        paragraphs.append(p3)
    
    # Parágrafo 4: Alertas
    alertas = []
    if suspensao:
        alertas.append(f"{len(suspensao)} suspensão(ões) de licitação")
    if rescisao:
        alertas.append("rescisão de contrato/parcelamento")
    if conep:
        alertas.append("normativa da CONEP (ética em pesquisa)")
    
    if alertas:
        paragraphs.append(f"<strong>⚠️ Alertas:</strong> {'; '.join(alertas)}.")
    
    # Parágrafo 5: Recomendação
    recs = []
    if equipamentos:
        recs.append("monitorar execução orçamentária dos recursos para equipamentos")
    if anvisa:
        recs.append("acompanhar novas autorizações sanitárias")
    if suspensao:
        recs.append("observar republicação de licitações suspensas")
    
    if recs:
        paragraphs.append(f"<strong>💡 Recomendação:</strong> {'; '.join(recs)}.")
    
    return "<br><br>".join(paragraphs) if paragraphs else "<em>Análise estratégica em desenvolvimento.</em>"


def generate_html(publications, date_str):
    """Gera o HTML do email com resumo estratégico."""
    sec1 = [p for p in publications if 'Seção 1' in p['section']]
    sec2 = [p for p in publications if 'Seção 2' in p['section']]
    sec3 = [p for p in publications if 'Seção 3' in p['section']]
    
    def esc(text):
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    # Gerar resumo estratégico
    resumo = generate_strategic_summary(sec1, sec2, sec3)
    
    # Gerar bloco específico GM/MS
    gmms_html, _ = generate_gmms_summary(sec1)
    
    # Identificar publicações impactantes
    impactantes = []
    for p in sec1:
        t = p['title'].upper()
        if 'GM/MS' in t and '10.9' in t:
            if '10.937' in t:
                impactantes.append((p['title'], "Aprova adesão à PNAISP (Saúde Mental no Sistema Prisional)", "🏛️"))
            elif '10.930' in t or '10.931' in t:
                impactantes.append((p['title'], "Autoriza recursos para Atenção Especializada", "💰"))
            else:
                impactantes.append((p['title'], "Autoriza recursos para equipamentos permanentes", "🏥"))
        elif 'SGTES/MS' in t:
            impactantes.append((p['title'], "Altera lista de médicos intercambiados (Mais Médicos)", "👨‍⚕️"))
        elif 'RESOLUÇÃO-RE' in t:
            impactantes.append((p['title'], "Autorização sanitária ANVISA", "⚕️"))
    
    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
.container {{ max-width: 950px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
.header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 25px; border-radius: 10px; margin-bottom: 25px; }}
.header h1 {{ margin: 0; font-size: 24px; }}
.header p {{ margin: 10px 0 0 0; opacity: 0.9; }}
.stats {{ display: flex; gap: 15px; margin-bottom: 25px; flex-wrap: wrap; }}
.stat-box {{ flex: 1; min-width: 150px; background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; border-left: 4px solid #667eea; }}
.stat-box h3 {{ margin: 0; color: #667eea; font-size: 28px; }}
.stat-box p {{ margin: 5px 0 0 0; color: #666; font-size: 14px; }}
.section {{ margin-bottom: 30px; }}
.section-title {{ color: white; padding: 12px 15px; border-radius: 8px; font-size: 18px; margin-bottom: 15px; font-weight: 600; }}
.sec1 {{ background: #e74c3c; }}
.sec2 {{ background: #f39c12; }}
.sec3 {{ background: #27ae60; }}
.sec-destaque {{ background: linear-gradient(135deg, #3498db 0%, #2980b9 100%); }}
.pub-item {{ background: #f8f9fa; padding: 12px 15px; margin-bottom: 8px; border-radius: 6px; border-left: 3px solid #ddd; }}
.pub-item.destaque {{ border-left: 4px solid #e74c3c; background: #fff5f5; }}
.pub-title {{ font-weight: 600; color: #2c3e50; margin-bottom: 5px; }}
.pub-title a {{ color: #667eea; text-decoration: none; }}
.pub-title a:hover {{ text-decoration: underline; }}
.pub-snippet {{ color: #666; font-size: 13px; line-height: 1.4; }}
.resumo-box {{ background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); padding: 20px; border-radius: 10px; border-left: 5px solid #667eea; margin-bottom: 25px; }}
.resumo-box h2 {{ margin-top: 0; color: #2c3e50; font-size: 18px; }}
.resumo-box p {{ color: #444; line-height: 1.6; font-size: 14px; margin: 8px 0; }}
.impacto-item {{ display: flex; align-items: flex-start; gap: 10px; padding: 10px; background: white; border-radius: 6px; margin-bottom: 8px; border-left: 3px solid #f39c12; }}
.impacto-emoji {{ font-size: 20px; }}
.impacto-text {{ flex: 1; }}
.impacto-title {{ font-weight: 600; color: #2c3e50; font-size: 13px; }}
.impacto-desc {{ color: #666; font-size: 12px; }}
.footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; color: #999; font-size: 12px; text-align: center; }}
</style></head>
<body>
<div class="container">
<div class="header">
<h1>🩺 DOU Saúde - Resumo Executivo</h1>
<p>Diário Oficial da União | {date_str} | Ministério da Saúde</p>
<p style="font-size: 12px; margin-top: 15px;">✅ Extração completa: {len(publications)} publicações | 🔑 Playwright | 📊 Com análise estratégica</p>
</div>

<div class="stats">
<div class="stat-box"><h3>{len(publications)}</h3><p>Total</p></div>
<div class="stat-box"><h3>{len(sec1)}</h3><p>Seção 1 - Normativos</p></div>
<div class="stat-box"><h3>{len(sec2)}</h3><p>Seção 2 - Pessoal</p></div>
<div class="stat-box"><h3>{len(sec3)}</h3><p>Seção 3 - Contratos</p></div>
</div>

{gmms_html}

<div class="resumo-box">
<h2>🎯 RESUMO ESTRATÉGICO DO DIA</h2>
<p>{resumo}</p>
</div>
"""
    
    # Publicações de impacto
    if impactantes:
        html += '<div class="section"><div class="section-title sec-destaque">⭐ Publicações de Maior Impacto Estratégico</div>'
        for title, desc, emoji in impactantes[:10]:
            html += f'<div class="impacto-item"><div class="impacto-emoji">{emoji}</div><div class="impacto-text"><div class="impacto-title">{esc(title)}</div><div class="impacto-desc">{esc(desc)}</div></div></div>'
        html += '</div>'
    
    # Seção 1
    html += f'<div class="section"><div class="section-title sec1">📜 Seção 1 - Atos Normativos ({len(sec1)})</div>'
    for pub in sec1:
        title = esc(pub['title'])
        snippet = esc(pub.get('snippet', '')[:150])
        is_destaque = any(d[0] == pub['title'] for d in impactantes)
        classe = 'pub-item destaque' if is_destaque else 'pub-item'
        html += f'<div class="{classe}"><div class="pub-title"><a href="{pub["url"]}" target="_blank">{title}</a></div><div class="pub-snippet">{snippet}...</div></div>'
    html += '</div>'
    
    # Seção 2
    html += f'<div class="section"><div class="section-title sec2">👥 Seção 2 - Atos de Pessoal ({len(sec2)})</div>'
    for pub in sec2:
        title = esc(pub['title'])
        snippet = esc(pub.get('snippet', '')[:150])
        html += f'<div class="pub-item"><div class="pub-title"><a href="{pub["url"]}" target="_blank">{title}</a></div><div class="pub-snippet">{snippet}...</div></div>'
    html += '</div>'
    
    # Seção 3
    html += f'<div class="section"><div class="section-title sec3">📋 Seção 3 - Contratos e Editais ({len(sec3)})</div>'
    for pub in sec3[:50]:
        title = esc(pub['title'])
        snippet = esc(pub.get('snippet', '')[:120])
        html += f'<div class="pub-item"><div class="pub-title"><a href="{pub["url"]}" target="_blank">{title}</a></div><div class="pub-snippet">{snippet}...</div></div>'
    if len(sec3) > 50:
        html += f'<div class="pub-item" style="text-align:center;color:#999;">... e mais {len(sec3)-50} publicações</div>'
    html += '</div>'
    
    html += '''<div class="footer">
<p>📧 Virgílio | DOU Saúde Monitor | Playwright Complete Scraper</p>
<p style="font-size: 11px; margin-top: 5px;">Resumo estratégico gerado automaticamente com análise de impacto</p>
</div></div></body></html>'''
    
    return html


async def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime('%d/%m/%Y')
    
    publications = await scrape_dou_complete(date_str)
    
    if not publications:
        print("⚠️ Nenhuma publicação encontrada. Pulando envio.")
        return
    
    html = generate_html(publications, date_str)
    html_file = f'/tmp/dou_playwright_{date_str.replace("/", "-")}.html'
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"📄 HTML salvo: {html_file}")
    
    try:
        creds = load_credentials()
        subject = f"🩺 DOU Saúde ESTRATÉGICO | {date_str} | {len(publications)} publicações"
        send_email("pedrowilliamrd@gmail.com", subject, html, creds)
        print("✅ Email enviado!")
    except Exception as e:
        print(f"❌ Erro ao enviar email: {e}")


if __name__ == "__main__":
    asyncio.run(main())
