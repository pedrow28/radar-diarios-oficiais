#!/usr/bin/env python3
"""
IOF MG Scraper — Extrai publicações da Secretaria de Estado de Saúde do Diário Oficial de MG.

Fluxo:
1. API do IOF MG por data → JSON com metadados + PDF Base64
2. Decodifica Base64 → envelope PKCS#7 assinado
3. Extrai PDF do envelope (openssl smime)
4. Extrai texto do PDF (pypdf)
5. Filtra páginas da SES-MG via sumário
6. Parseia publicações individuais
7. Retorna lista estruturada + texto bruto

Uso: python3 iof_mg_scraper.py [YYYY-MM-DD]
"""

import sys
import os
import re
import json
import base64
import tempfile
import subprocess
import requests
from datetime import datetime
from typing import List, Dict, Tuple

try:
    from pypdf import PdfReader
except ImportError:
    print("ERRO: pypdf não instalado. Instale: pip install pypdf")
    sys.exit(1)

API_URL = "https://www.jornalminasgerais.mg.gov.br/api/v1/Jornal/ObterEdicaoPorDataPublicacao"


def fetch_edition(date_str: str) -> Dict:
    """Busca edição do IOF MG para uma data."""
    url = f"{API_URL}?dataPublicacao={date_str}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def extract_pdf_from_pkcs7(pkcs7_bytes: bytes) -> bytes:
    """Extrai PDF de envelope PKCS#7/CMS usando openssl."""
    with tempfile.NamedTemporaryFile(suffix=".p7s", delete=False) as tmp_in:
        tmp_in.write(pkcs7_bytes)
        tmp_in.flush()
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path.replace(".p7s", ".pdf")

    try:
        result = subprocess.run(
            ["openssl", "smime", "-verify", "-in", tmp_in_path, "-inform", "DER",
             "-noverify", "-out", tmp_out_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(f"openssl falhou: {result.stderr}")

        with open(tmp_out_path, "rb") as f:
            return f.read()
    finally:
        for p in [tmp_in_path, tmp_out_path]:
            if os.path.exists(p):
                os.remove(p)


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extrai texto de todas as páginas do PDF."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        tmp_path = tmp.name

    try:
        reader = PdfReader(tmp_path)
        texts = []
        for i, page in enumerate(reader.pages):
            txt = page.extract_text()
            if txt:
                texts.append(f"\n--- Página {i+1} ---\n{txt}")
        return "\n".join(texts)
    finally:
        os.remove(tmp_path)


def extract_text_from_pages(pdf_bytes: bytes, start_page: int, end_page: int) -> str:
    """Extrai texto de um range de páginas (1-indexed)."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        tmp_path = tmp.name

    try:
        reader = PdfReader(tmp_path)
        texts = []
        for i in range(start_page - 1, min(end_page, len(reader.pages))):
            txt = reader.pages[i].extract_text()
            if txt:
                texts.append(f"\n--- Página {i+1} ---\n{txt}")
        return "\n".join(texts)
    finally:
        os.remove(tmp_path)


def find_section_pages(text: str, section_name: str) -> Tuple[int, int]:
    """
    Encontra páginas inicial e final de uma seção via sumário.
    Retorna (start_page, end_page) ou (0, 0) se não encontrar.
    """
    # Procura no sumário: "Secretaria de Estado de Saúde  .... 28"
    pattern = re.compile(
        rf'{re.escape(section_name)}\s+(?:\.\s*)+(\d+)',
        re.IGNORECASE
    )
    match = pattern.search(text)
    if not match:
        return 0, 0

    start_page = int(match.group(1))

    # Procura a próxima seção após a nossa para definir end_page
    # Padrão: nome da seção seguido de pontos e número de página
    all_sections = re.findall(
        r'([A-Z][A-Za-z\sÁÉÍÓÚÂÊÎÔÛÀÈÌÒÙÃÅÇÑáéíóúâêîôûàèìòùãåçñ,]+?)\s+(?:\.\s*)+(\d+)',
        text
    )

    end_page = None
    for name, page in all_sections:
        if section_name.lower() in name.lower():
            continue
        p = int(page)
        if p > start_page:
            if end_page is None or p < end_page:
                end_page = p
            break

    if end_page is None:
        # Não achou próxima seção — vai até o fim do documento
        end_page = 9999

    return start_page, end_page


def parse_publications_ses(text: str) -> List[Dict]:
    """
    Parseia publicações individuais do texto da SES-MG.
    Retorna lista de dicts com título, tipo, conteúdo.
    """
    pubs = []

    # Padrões de publicações
    # Portarias
    portarias = re.findall(
        r'(PORTARIA\s+[A-Z/\s\d]+,?\s+DE\s+\d+\s+DE\s+[A-Z]+\s+DE\s+\d{4})(.*?)(?=PORTARIA\s+[A-Z/\s\d]+,?\s+DE|\Z)',
        text, re.DOTALL | re.IGNORECASE
    )
    for title, content in portarias:
        pubs.append({
            "tipo": "Portaria",
            "titulo": title.strip(),
            "conteudo": content.strip()[:800],
            "secao": "Secretaria de Estado de Saúde"
        })

    # Decretos
    decretos = re.findall(
        r'(DECRETO\s+[A-Z\s]*Nº?\s*\d+,?\s+DE\s+\d+\s+DE\s+[A-Z]+\s+DE\s+\d{4})(.*?)(?=DECRETO\s+[A-Z\s]*Nº?|\Z)',
        text, re.DOTALL | re.IGNORECASE
    )
    for title, content in decretos:
        pubs.append({
            "tipo": "Decreto",
            "titulo": title.strip(),
            "conteudo": content.strip()[:800],
            "secao": "Secretaria de Estado de Saúde"
        })

    # Resoluções
    resolucoes = re.findall(
        r'(RESOLUÇÃO\s+[A-Z\s]*Nº?\s*\d+,?\s+DE\s+\d+\s+DE\s+[A-Z]+\s+DE\s+\d{4})(.*?)(?=RESOLUÇÃO\s+[A-Z\s]*Nº?|\Z)',
        text, re.DOTALL | re.IGNORECASE
    )
    for title, content in resolucoes:
        pubs.append({
            "tipo": "Resolução",
            "titulo": title.strip(),
            "conteudo": content.strip()[:800],
            "secao": "Secretaria de Estado de Saúde"
        })

    # Atos / Despachos / Nomeações / Exonerações
    atos = re.findall(
        r'((?:nomeia|exonera|despacha|designa|autoriza|concede|dispens[ea])[^.]*(?:MAS[PS]\s+\d+[\-\d]*).*?)(?=\n\s*(?:nomeia|exonera|despacha|designa|autoriza|concede|dispens[ea])[^.]*(?:MAS[PS]\s+\d+[\-\d]*)|\Z)',
        text, re.DOTALL | re.IGNORECASE
    )
    for content in atos:
        pubs.append({
            "tipo": "Ato de Pessoal",
            "titulo": content.strip()[:120],
            "conteudo": content.strip()[:800],
            "secao": "Secretaria de Estado de Saúde"
        })

    # Contratos / Termos Aditivos / Extratos
    contratos = re.findall(
        r'(EXTRATO\s+DE\s+(?:CONTRATO|TERMO\s+ADITIVO)[^\n]*)(.*?)(?=EXTRATO\s+DE\s+(?:CONTRATO|TERMO\s+ADITIVO)|\Z)',
        text, re.DOTALL | re.IGNORECASE
    )
    for title, content in contratos:
        pubs.append({
            "tipo": "Contrato",
            "titulo": title.strip(),
            "conteudo": content.strip()[:800],
            "secao": "Secretaria de Estado de Saúde"
        })

    return pubs


def classify_sus_relevance(pub: Dict) -> tuple[bool, str]:
    """
    Classifica se uma publicação é relacionada ao SUS e retorna (é_sus, categoria_impacto).
    Categorias: orçamentário, regulatório, pactuação, pessoal, contratual, programático, geral
    """
    text = (pub.get("conteudo", "") + " " + pub.get("titulo", "")).lower()

    # Palavras-chave SUS
    sus_keywords = [
        "sistema único de saúde", "sus", "teto mac", "macroalocação",
        "pactuação", "pacto", "bloco de financiamento", "financiamento",
        "custeio", "investimento", "repasse", "transferência",
        "atenção básica", "atenção especializada", "média complexidade",
        "alta complexidade", "urgência e emergência", "sadt",
        "hospitalar", "leito", "upas", "samu", "regulação",
        "cnes", "sigtap", "procedimento", "tabela sigtap",
        "programa", "vigilância sanitária", "vigilância epidemiológica",
        "imunização", "vacina", "medicamento", "insumo",
        "regional", "gerência regional", "macrorregional",
        "fhemig", "fundação hospitalar", "hospital regional",
        "conselho estadual de saúde", "ces", "conferência",
        "plano estadual de saúde", "diretrizes", "normativa",
        "alta complexidade hospitalar", "programa de melhoria",
    ]

    is_sus = any(kw in text for kw in sus_keywords)

    if not is_sus:
        return False, ""

    # Classificar impacto
    if any(k in text for k in ["teto mac", "macroalocação", "financiamento", "repasse", "bloco", "custeio", "investimento"]):
        return True, "orçamentário"
    if any(k in text for k in ["pactuação", "pacto", "diretriz", "normativa", "regulamentação", "regulação", "procedimento", "tabela"]):
        return True, "regulatório"
    if any(k in text for k in ["programa", "vigilância", "imunização", "vacina", "atenção básica", "atenção especializada"]):
        return True, "programático"
    if any(k in text for k in ["contrato", "licitação", "pregão", "dispensa", "termo aditivo"]):
        return True, "contratual"
    if "nomeia" in text or "exonera" in text or "designa" in text:
        return True, "pessoal"

    return True, "geral"


def extract_normativa_detail(pub: Dict) -> Dict:
    """Extrai detalhes estruturados de uma normativa (portaria/resolução/decreto)."""
    titulo = pub.get("titulo", "")
    conteudo = pub.get("conteudo", "")

    # Extrair número da normativa
    num_match = re.search(r'N[º°]\s*(\d+(?:\.\d+)*)', titulo, re.IGNORECASE)
    numero = num_match.group(1) if num_match else "N/A"

    # Extrair data da normativa (ex: "DE 15 DE MAIO DE 2026")
    data_match = re.search(r'DE\s+(\d+)\s+DE\s+([A-ZÇ]+)\s+DE\s+(\d{4})', titulo, re.IGNORECASE)
    data_norm = f"{data_match.group(1)} {data_match.group(2)} {data_match.group(3)}" if data_match else "N/A"

    # Resumo/ementa: primeira frase do conteúdo
    ementa = conteudo.strip().split(".")[0][:200] if conteudo else ""

    return {
        "tipo": pub.get("tipo", ""),
        "numero": numero,
        "data": data_norm,
        "ementa": ementa,
        "titulo": titulo,
    }


def generate_strategic_summary(publications: List[Dict]) -> str:
    """Gera resumo estratégico das publicações SES-MG com destaque para normativas SUS."""
    paragraphs = []

    # Classificar todas as publicações
    for pub in publications:
        is_sus, impacto = classify_sus_relevance(pub)
        pub["is_sus"] = is_sus
        pub["impacto"] = impacto

    portarias = [p for p in publications if p["tipo"] == "Portaria"]
    decretos = [p for p in publications if p["tipo"] == "Decreto"]
    resolucoes = [p for p in publications if p["tipo"] == "Resolução"]
    pessoal = [p for p in publications if p["tipo"] == "Ato de Pessoal"]
    contratos = [p for p in publications if p["tipo"] == "Contrato"]

    # ─── Destaque: Normativas SUS ───
    sus_normativas = [p for p in publications if p.get("is_sus")]

    if sus_normativas:
        paragraphs.append("<strong>🏥 NORMATIVAS SUS — DESTAQUE</strong>")
        paragraphs.append(f"<em>{len(sus_normativas)} publicação(ões) com impacto direto no SUS/Saúde Pública:</em>")

        # Agrupar por tipo
        sus_by_tipo = {}
        for p in sus_normativas:
            t = p.get("tipo", "Outro")
            sus_by_tipo.setdefault(t, []).append(p)

        for tipo, pubs in sorted(sus_by_tipo.items()):
            detail_lines = []
            for p in pubs:
                det = extract_normativa_detail(p)
                impacto = p.get("impacto", "geral")
                detail_lines.append(
                    f"• <strong>{det['tipo']} {det['numero']}</strong> ({det['data']}) — "
                    f"impacto <em>{impacto}</em>: {det['ementa'][:140]}..."
                )
            paragraphs.append(f"<br><strong>{tipo}s SUS ({len(pubs)}):</strong><br>" + "<br>".join(detail_lines))

        paragraphs.append("<br>")

    # ─── Resumo geral ───
    if decretos:
        paragraphs.append(
            f"<strong>📋 Decretos:</strong> {len(decretos)} decreto(s) publicado(s), potencial impacto orçamentário ou administrativo."
        )

    if portarias:
        teto = [p for p in portarias if "teto" in p["conteudo"].lower() or "execução" in p["conteudo"].lower()]
        medicamentos = [p for p in portarias if "medicamento" in p["conteudo"].lower()]
        prestadores = [p for p in portarias if "prestador" in p["conteudo"].lower()]
        mac = [p for p in portarias if any(k in p["conteudo"].lower() for k in ["mac", "macroalocação", "financiamento"])]

        desc = f"{len(portarias)} portaria(s)"
        if teto:
            desc += f", incluindo revisão de tetos de execução ({len(teto)})"
        if mac:
            desc += f", macroalocação/financiamento ({len(mac)})"
        if medicamentos:
            desc += f", aquisição de medicamentos ({len(medicamentos)})"
        if prestadores:
            desc += f", regulação de prestadores ({len(prestadores)})"
        paragraphs.append(f"<strong>📁 Portarias:</strong> {desc}.")

    if resolucoes:
        paragraphs.append(
            f"<strong>📜 Resoluções:</strong> {len(resolucoes)} resolução(ões) com impacto normativo."
        )

    if pessoal:
        paragraphs.append(
            f"<strong>👤 Atos de Pessoal:</strong> {len(pessoal)} nomeação(ções)/exoneração(ções)/designação(ções)."
        )

    if contratos:
        paragraphs.append(
            f"<strong>📋 Contratos:</strong> {len(contratos)} extrato(s) de contrato/termo aditivo publicado(s)."
        )

    if not paragraphs:
        paragraphs.append("<em>Nenhuma publicação identificada para análise estratégica.</em>")

    return "<br><br>".join(paragraphs)


def scrape_iof_mg(date_str: str = None) -> Dict:
    """
    Pipeline completo do IOF MG.
    Retorna dict com: publications, summary, raw_text, date, total_pages.
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    print(f"🔍 IOF MG | {date_str}")

    # 1. Fetch API
    data = fetch_edition(date_str)
    dados = data.get("dados")
    if not dados:
        print("   ⚠️ Sem dados para esta data.")
        return {"publications": [], "summary": "", "raw_text": "", "date": date_str, "total_pages": 0}

    # 2. Extrair PDF Base64
    acp = dados.get("arquivoCadernoPrincipal", {})
    pdf_b64 = acp.get("arquivo", "")
    if not pdf_b64:
        print("   ❌ Sem PDF Base64 no arquivoCadernoPrincipal")
        return {"publications": [], "summary": "", "raw_text": "", "date": date_str, "total_pages": 0}

    pkcs7_bytes = base64.b64decode(pdf_b64)
    print(f"   📄 PDF PKCS7: {len(pkcs7_bytes)} bytes")

    # 3. Extrair PDF do envelope
    pdf_bytes = extract_pdf_from_pkcs7(pkcs7_bytes)
    print(f"   ✅ PDF extraído: {len(pdf_bytes)} bytes")

    # 4. Extrair texto completo (primeira página para sumário)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        tmp_path = tmp.name

    try:
        reader = PdfReader(tmp_path)
        total_pages = len(reader.pages)
        print(f"   📄 Total de páginas: {total_pages}")

        # Extrai página 1 para sumário
        page1_text = reader.pages[0].extract_text() or ""

        # 5. Encontra páginas da SES-MG
        start_pg, end_pg = find_section_pages(page1_text, "Secretaria de Estado de Saúde")
        if start_pg == 0:
            print("   ⚠️ Secretaria de Estado de Saúde não encontrada no sumário.")
            return {"publications": [], "summary": "", "raw_text": "", "date": date_str, "total_pages": total_pages}

        print(f"   📚 SES-MG: páginas {start_pg} – {end_pg}")

        # 6. Extrai texto da seção SES-MG
        ses_text = ""
        for i in range(start_pg - 1, min(end_pg, total_pages)):
            txt = reader.pages[i].extract_text()
            if txt:
                ses_text += f"\n--- Página {i+1} ---\n{txt}"

        print(f"   📝 Texto SES-MG: {len(ses_text)} chars")

    finally:
        os.remove(tmp_path)

    # 7. Parseia publicações
    publications = parse_publications_ses(ses_text)
    print(f"   📊 Publicações parseadas: {len(publications)}")

    # 8. Gera resumo
    summary = generate_strategic_summary(publications)

    return {
        "publications": publications,
        "summary": summary,
        "raw_text": ses_text,
        "date": date_str,
        "total_pages": total_pages,
        "ses_pages": f"{start_pg}-{end_pg}"
    }


if __name__ == "__main__":
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    result = scrape_iof_mg(date_str)

    print(f"\n{'='*60}")
    print(f"📊 RESUMO ESTRATÉGICO SES-MG | {result['date']}")
    print("="*60)
    print(result["summary"])
    print(f"\n📊 Total de publicações: {len(result['publications'])}")
    for p in result["publications"][:10]:
        print(f"   [{p['tipo']}] {p['titulo'][:100]}")
