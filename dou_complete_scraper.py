#!/usr/bin/env python3
"""
DOU Complete Scraper - Playwright
Extrai TODAS as publicações do DOU usando delta=75 + navegação por páginas
"""
import asyncio
import json
import re
import sys
from datetime import datetime
from playwright.async_api import async_playwright

async def scrape_dou_complete(date_str, orgao="Ministério da Saúde"):
    """
    Extrai todas as publicações do DOU para um órgão em uma data específica.
    date_str: DD/MM/YYYY
    """
    all_publications = []
    
    day, month, year = date_str.split('/')
    
    # Usar delta=75 (máximo que funciona bem)
    url = (f"https://www.in.gov.br/consulta/-/buscar/dou"
           f"?q=*&orgPrin={orgao.replace(' ', '+')}"
           f"&exactDate=dia&dateDay={day}&dateMonth={month}&dateYear={year}&delta=75")
    
    print(f"🔥 Iniciando extração completa do DOU")
    print(f"   Data: {date_str}")
    print(f"   Órgão: {orgao}")
    print(f"   URL: {url}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=90000)
            print("\n✅ Página carregada")
            
            # Aguardar carregamento inicial
            await page.wait_for_timeout(3000)
            
            # Extrair total de resultados
            page_content = await page.content()
            total_match = re.search(r'(\d+)\s+resultados?', page_content)
            total_results = int(total_match.group(1)) if total_match else 0
            print(f"📊 Total de publicações no DOU: {total_results}")
            
            if total_results == 0:
                print("⚠️ Nenhuma publicação encontrada")
                return []
            
            page_num = 1
            max_pages = 10  # Limite de segurança
            
            while page_num <= max_pages:
                print(f"\n📄 Processando página {page_num}...")
                
                # Extrair publicações da página atual
                publications = await page.evaluate('''() => {
                    const results = [];
                    const items = document.querySelectorAll('h5');
                    items.forEach(h5 => {
                        const link = h5.querySelector('a');
                        const title = h5.textContent.trim();
                        const href = link ? link.href : '';
                        
                        let snippet = '';
                        let parent = h5.closest('div');
                        if (parent) {
                            const para = parent.querySelector('p');
                            if (para) snippet = para.textContent.trim();
                        }
                        
                        let section = 'Outros';
                        const upperTitle = title.toUpperCase();
                        if (upperTitle.includes('PORTARIA') || upperTitle.includes('RESOLUÇÃO') || 
                            upperTitle.includes('DECRETO') || upperTitle.includes('LEI') ||
                            upperTitle.includes('RETIFICAÇÃO')) {
                            section = 'Seção 1 - Atos Normativos';
                        } else if (upperTitle.includes('NOMEAÇÃO') || upperTitle.includes('EXONERAÇÃO') ||
                                   upperTitle.includes('DESPACHO') || upperTitle.includes('ATO DE PESSOAL') ||
                                   upperTitle.includes('PENSÃO') || upperTitle.includes('APOSENTADORIA')) {
                            section = 'Seção 2 - Atos de Pessoal';
                        } else if (upperTitle.includes('EXTRATO') || upperTitle.includes('EDITAL') || 
                                   upperTitle.includes('AVISO') || upperTitle.includes('CONTRATO') ||
                                   upperTitle.includes('TERMO ADITIVO') || upperTitle.includes('ATA') ||
                                   upperTitle.includes('REGISTRO DE PREÇOS') || upperTitle.includes('RESCISÃO')) {
                            section = 'Seção 3 - Contratos e Editais';
                        }
                        
                        if (title && !title.includes('Reportar Erro')) {
                            results.push({title, url: href, snippet, section});
                        }
                    });
                    return results;
                }''')
                
                print(f"   ➕ {len(publications)} publicações extraídas")
                all_publications.extend(publications)
                
                # Verificar se já pegamos tudo
                if len(all_publications) >= total_results:
                    print(f"   ✅ Todas as {total_results} publicações extraídas!")
                    break
                
                # Tentar clicar no botão "Próximo" de paginação
                try:
                    # Procurar botão de próxima página
                    next_button = await page.query_selector('li.page-item button.page-link:has-text("Próximo")')
                    if not next_button:
                        next_button = await page.query_selector('button.page-link:has-text(">")')
                    if not next_button:
                        # Tentar encontrar por classe
                        next_button = await page.query_selector('li.page-item:last-child button.page-link')
                    
                    if next_button:
                        await next_button.click()
                        await page.wait_for_timeout(4000)  # Esperar carregar
                        page_num += 1
                    else:
                        print("   ✅ Última página alcançada")
                        break
                        
                except Exception as e:
                    print(f"   ⚠️ Não foi possível avançar: {e}")
                    break
            
            print(f"\n🎉 Extração completa!")
            print(f"   Total de páginas navegadas: {page_num}")
            print(f"   Total de publicações extraídas: {len(all_publications)}")
            
        except Exception as e:
            print(f"\n❌ Erro: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()
    
    return all_publications


async def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else "24/04/2026"
    orgao = sys.argv[2] if len(sys.argv) > 2 else "Ministério da Saúde"
    
    publications = await scrape_dou_complete(date_str, orgao)
    
    # Salvar resultado
    output = {
        'date': date_str,
        'orgao': orgao,
        'total': len(publications),
        'extracted_at': datetime.now().isoformat(),
        'publications': publications
    }
    
    output_file = f'/tmp/dou_complete_{date_str.replace("/", "-")}.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 Resultado salvo em: {output_file}")
    
    # Resumo por seção
    sec1 = [p for p in publications if 'Seção 1' in p['section']]
    sec2 = [p for p in publications if 'Seção 2' in p['section']]
    sec3 = [p for p in publications if 'Seção 3' in p['section']]
    
    print(f"\n📊 Resumo por seção:")
    print(f"   Seção 1 (Normativos): {len(sec1)}")
    print(f"   Seção 2 (Pessoal): {len(sec2)}")
    print(f"   Seção 3 (Contratos): {len(sec3)}")
    
    # Mostrar amostra da Seção 1
    if sec1:
        print(f"\n📜 Amostra Seção 1:")
        for p in sec1[:10]:
            print(f"   - {p['title'][:80]}")
    
    # Mostrar amostra da Seção 2
    if sec2:
        print(f"\n👥 Amostra Seção 2:")
        for p in sec2[:5]:
            print(f"   - {p['title'][:80]}")


if __name__ == "__main__":
    asyncio.run(main())
