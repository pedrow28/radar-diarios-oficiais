#!/usr/bin/env python3
"""
Briefing Estratégico IOF-MG — Secretaria de Estado de Saúde
Pipeline completo: extração → contexto expandido → análise estratégica → vault + email

Uso:
    python3 iof_mg_briefing_estrategico.py --date 2026-05-20
    python3 iof_mg_briefing_estrategico.py  # hoje

Diferença do template standalone: gera briefing markdown estratégico (não lista mecânica)
e envia email HTML via Gmail API (OAuth).
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import fitz
import requests
import yaml

V1_BASE_URL = (
    "https://www.jornalminasgerais.mg.gov.br/api/v1/Jornal/ObterEdicaoPorDataPublicacao"
)

TERMOS_SAUDE = [
    "SECRETARIA DE ESTADO DE SAÚDE",
    "FUNDO ESTADUAL DE SAÚDE",
    "CONSELHO ESTADUAL DE SAÚDE",
    "SISTEMA ÚNICO DE SAÚDE",
    "FHEMIG",
    "FUNDAÇÃO HOSPITALAR",
    "GERÊNCIA REGIONAL DE SAÚDE",
    "RESOLUÇÃO SES/MG",
    "PORTARIA SES/MG",
    "PROCESSO ADMINISTRATIVO SANITÁRIO",
]

VAULT_DIR = Path("/root/mente")
BRIEFING_DIR = VAULT_DIR / "Briefings Diários" / "IOF-MG Saúde"

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"

SYSTEM_PROMPT_BRIEFING = """Você é um analista de inteligência em saúde pública e gestão governamental, trabalhando para a Thauma Consultoria. Sua função é transformar publicações do Diário Oficial de Minas Gerais em briefings estratégicos acionáveis.

REGRAS ABSOLUTAS:
1. NUNCA invente dados que não estejam no texto fornecido
2. NUNCA mencione "o texto não informa" — simplesmente omita
3. Sempre cite a página do Diário Oficial onde a informação aparece
4. Use linguagem estratégica, não descritiva pura
5. Destaque: o que MUDA, o que IMPACTA, o que EXIGE ação
6. Formato: markdown com seções claras, bullets, callouts

ESTRUTURA DO BRIEFING (sempre em português):
# 📰 Briefing IOF-MG Saúde — [DATA]

## 🎯 Síntese Executiva
2-3 parágrafos com o panorama geral do dia — o que foi publicado de relevante para a SES-MG/SUS.

## 🔥 Alertas Estratégicos
Publicações que exigem atenção imediata. Use formato:
> [!danger] 🔴 [Título do alerta]
> Descrição do risco/oportunidade. Página X.

## 📋 Destaques por Tema
Agrupe por tema (não por termo de busca):
- Gestão e Pessoas (nomeações, exonerações, delegações)
- Contratos e Convênios (aditivos, extratos, licitações)
- Regulação e Normas (portarias, resoluções, processos administrativos)
- Institucional (eleições, comissões, conselhos)

## 💡 Oportunidades de Negócio
Sinais de oportunidade para Thauma Consultoria (projetos, consultorias, gaps de gestão).

## 📝 Ações Recomendadas
Lista de 3-5 ações concretas com prazo sugerido.

## 🔗 Referências
Tabela com: Página | Tipo | Resumo | Link
"""


@dataclass
class Ocorrencia:
    page: int
    term: str
    snippet: str
    contexto: str
    page_url: str


@dataclass
class Report:
    publish_date: date
    ocorrencias: list[Ocorrencia] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)
    count: int = 0


class Config:
    def __init__(self, path: str | Path) -> None:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        self.terms = raw.get("search_terms", TERMOS_SAUDE)
        self.data_dir = Path(raw.get("data_dir", "./data"))
        self.log_dir = Path(raw.get("log_dir", "./logs"))
        self.search_db = Path(raw.get("search_db", "./data/diarios.db"))
        self.vault_dir = Path(raw.get("vault_dir", str(VAULT_DIR)))
        self.briefing_dir = Path(raw.get("briefing_dir", str(BRIEFING_DIR)))
        self.email = raw.get("email", {})
        self.output = raw.get("output", {})
        self.logging_cfg = raw.get("logging", {})
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        Path(self.search_db).parent.mkdir(parents=True, exist_ok=True)
        self.briefing_dir.mkdir(parents=True, exist_ok=True)

    def is_email_enabled(self) -> bool:
        return bool(self.email.get("enabled", False))


def setup_logging(cfg: Config) -> logging.Logger:
    level = cfg.logging_cfg.get("level", "INFO")
    fmt = cfg.logging_cfg.get("format", "%(asctime)s | %(levelname)-8s | %(message)s")
    log_file = cfg.log_dir / f"briefing_estrategico_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.log"
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO), format=fmt, handlers=handlers
    )
    return logging.getLogger("iof-mg")


def consulta_iof(publish_date: date) -> dict[str, Any] | None:
    params = urlencode({"dataPublicacao": publish_date.strftime("%Y-%m-%d")})
    url = f"{V1_BASE_URL}?{params}"
    try:
        response = requests.get(url, timeout=30)
    except requests.RequestException:
        return None
    if response.status_code == 401:
        return None
    if response.status_code != 200:
        return None
    return response.json()


def extract_pdf_base64(data: dict[str, Any]) -> str:
    dados = data.get("dados", {})
    arquivo_data = dados.get("arquivoCadernoPrincipal", {})
    return str(arquivo_data.get("arquivo", ""))


def extract_pages(pdf_bytes: bytes) -> list[tuple[int, str]]:
    pages = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page_num, page in enumerate(doc, start=1):
            pages.append((page_num, page.get_text()))
    return pages


def init_search_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    schema = """
    CREATE TABLE IF NOT EXISTS documentos (
        id INTEGER PRIMARY KEY, num_pagina INTEGER NOT NULL,
        conteudo TEXT NOT NULL, data_publicacao TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_data_pagina
        ON documentos(data_publicacao, num_pagina);
    CREATE VIRTUAL TABLE IF NOT EXISTS documentos_fts USING fts5(
        conteudo, content='documentos', content_rowid='id'
    );
    CREATE TRIGGER IF NOT EXISTS documentos_ai AFTER INSERT ON documentos BEGIN
      INSERT INTO documentos_fts(rowid, conteudo) VALUES (new.id, new.conteudo);
    END;
    CREATE TRIGGER IF NOT EXISTS documentos_ad AFTER DELETE ON documentos BEGIN
      INSERT INTO documentos_fts(documentos_fts, rowid) VALUES('delete', old.id);
    END;
    CREATE TRIGGER IF NOT EXISTS documentos_au AFTER UPDATE ON documentos BEGIN
      INSERT INTO documentos_fts(documentos_fts, rowid) VALUES('delete', old.id);
      INSERT INTO documentos_fts(rowid, conteudo) VALUES (new.id, new.conteudo);
    END;
    """
    conn.executescript(schema)
    conn.commit()
    return conn


def import_pages(conn: sqlite3.Connection, pages: list[tuple[int, str]], publish_date: date) -> None:
    query = "REPLACE INTO documentos (num_pagina, conteudo, data_publicacao) VALUES (?, ?, ?)"
    cursor = conn.cursor()
    date_str = publish_date.strftime("%Y-%m-%d")
    try:
        for num, text in pages:
            cursor.execute(query, (num, text, date_str))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def lookup_with_context(conn: sqlite3.Connection, publish_date: date, terms: list[str]) -> list[Ocorrencia]:
    ocorrencias = []
    date_str = publish_date.strftime("%Y-%m-%d")
    for term in terms:
        search_term = f'"{term}"'
        query = """
            SELECT doc.num_pagina, doc.conteudo,
                   snippet(documentos_fts, 0, '<b>', '</b>', '...', 32) AS trecho
            FROM documentos_fts
            INNER JOIN documentos doc ON documentos_fts.rowid = doc.id
            WHERE doc.data_publicacao = ? AND documentos_fts MATCH ?
        """
        cursor = conn.cursor()
        cursor.execute(query, (date_str, search_term))
        for row in cursor.fetchall():
            page_num = row["num_pagina"]
            full_text = row["conteudo"]
            snippet = row["trecho"]
            idx = full_text.upper().find(term.upper())
            if idx == -1:
                contexto = full_text[:800]
            else:
                start = max(0, idx - 400)
                end = min(len(full_text), idx + len(term) + 400)
                contexto = full_text[start:end]
            date_str_iso = publish_date.strftime("%Y-%m-%d")
            payload = {
                "dataPublicacaoSelecionada": f"{date_str_iso}T03:00:00.000Z",
                "idCadernoEdicaoSelecionado": 326074,
                "paginaSelecionada": page_num,
            }
            json_payload = json.dumps(payload, separators=(",", ":"))
            encoded = quote(json_payload)
            page_url = f"https://www.jornalminasgerais.mg.gov.br/edicao-do-dia?dados={encoded}"
            ocorrencias.append(Ocorrencia(
                page=page_num, term=term, snippet=snippet,
                contexto=contexto, page_url=page_url,
            ))
    return ocorrencias


def has_pages(conn: sqlite3.Connection, publish_date: date) -> bool:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM documentos WHERE data_publicacao = ?", (publish_date.strftime("%Y-%m-%d"),))
    return bool(cursor.fetchone()[0] > 0)


class LLMBriefingGenerator:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
        self.model_free = "meta-llama/llama-3.3-70b-instruct:free"

    def generate(self, report: Report) -> str:
        import time
        logger = logging.getLogger("iof-mg")

        if report.count == 0:
            return self._generate_empty_briefing(report)

        prompt = self._build_prompt(report)

        if self.api_key:
            logger.info("Tentando OpenRouter (%s)...", self.model_free)
            for attempt in range(1, 4):
                try:
                    result = self._call_openrouter(prompt)
                    if result:
                        logger.info("Briefing gerado via OpenRouter (%d chars)", len(result))
                        return result
                except requests.exceptions.HTTPError as exc:
                    if exc.response.status_code == 429:
                        wait = attempt * 5
                        logger.warning("Rate limit OpenRouter. Aguardando %ds...", wait)
                        time.sleep(wait)
                    else:
                        logger.error("Erro OpenRouter HTTP %d", exc.response.status_code)
                        break
                except Exception as exc:
                    logger.error("Falha OpenRouter: %s", exc)
                    break

        logger.warning("Usando fallback mecânico (LLMs indisponíveis)")
        return self._generate_fallback_briefing(report)

    def _call_openrouter(self, prompt: str) -> str | None:
        response = requests.post(
            self.openrouter_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://thaumaconsultoria.com.br",
                "X-Title": "IOF-MG Briefing Engine",
            },
            json={
                "model": self.model_free,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT_BRIEFING},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 3000,
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _build_prompt(self, report: Report) -> str:
        lines = [
            f"Data do Diário Oficial: {report.publish_date.strftime('%d/%m/%Y')}",
            f"Total de ocorrências: {report.count}",
            f"Termos monitorados: {', '.join(report.search_terms)}",
            "",
            "=== OCORRÊNCIAS DETALHADAS ===",
            "",
        ]
        by_term: dict[str, list[Ocorrencia]] = {}
        for occ in report.ocorrencias:
            by_term.setdefault(occ.term, []).append(occ)
        for term, occs in sorted(by_term.items()):
            lines.append(f"\n--- TERMOS: {term} ---")
            for occ in occs:
                lines.append(f"\nPágina {occ.page}:")
                lines.append(f"Contexto: {occ.contexto[:600]}")
                lines.append(f"Link: {occ.page_url}")
        return "\n".join(lines)

    @staticmethod
    def _generate_empty_briefing(report: Report) -> str:
        date_str = report.publish_date.strftime("%d/%m/%Y")
        return f"""# 📰 Briefing IOF-MG Saúde — {date_str}

## 🎯 Síntese Executiva
Nenhuma ocorrência encontrada para os termos monitorados nesta data ({date_str}).
Isso não significa ausência de publicações de saúde — apenas que os termos exatos configurados não apareceram no texto extraído.

**Recomendação:** Revisão manual da edição do dia.

*Gerado automaticamente em {datetime.now(UTC).strftime('%d/%m/%Y %H:%M')} UTC*
"""

    @staticmethod
    def _generate_fallback_briefing(report: Report) -> str:
        date_str = report.publish_date.strftime("%d/%m/%Y")
        lines = [f"# 📰 Briefing IOF-MG Saúde — {date_str}", "", "## 🔍 Destaques Encontrados", ""]
        by_term: dict[str, list[Ocorrencia]] = {}
        for occ in report.ocorrencias:
            by_term.setdefault(occ.term, []).append(occ)
        for term, occs in sorted(by_term.items()):
            lines.append(f"### {term}")
            for occ in occs:
                snippet = occ.snippet.replace("<b>", "**").replace("</b>", "**")
                lines.append(f"- **Página {occ.page}:** {snippet}")
                lines.append(f"  [🔗 Ver no Jornal MG]({occ.page_url})")
            lines.append("")
        lines.append("---")
        lines.append(f"*Gerado automaticamente em {datetime.now(UTC).strftime('%d/%m/%Y %H:%M')} UTC*")
        return "\n".join(lines)


class GmailSender:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.from_addr = cfg.get("from_address", "pedrowilliamrd@gmail.com")
        self.to_addrs = cfg.get("to_addresses", [])
        self.token_path = cfg.get("token_path", str(Path.home() / ".hermes" / "google_token.json"))

    def send(self, subject: str, html_body: str) -> bool:
        if not self.to_addrs:
            logging.getLogger("iof-mg").warning("Nenhum destinatário configurado")
            return False
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            from email.header import Header
            import base64

            creds = Credentials.from_authorized_user_file(self.token_path)
            service = build("gmail", "v1", credentials=creds)
            msg = MIMEMultipart("mixed")
            msg["Subject"] = Header(subject, "utf-8")
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(self.to_addrs)
            msg_body = MIMEMultipart("alternative")
            msg_body.attach(MIMEText(html_body, "html", "utf-8"))
            msg.attach(msg_body)
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            body = {"raw": raw}
            result = service.users().messages().send(userId="me", body=body).execute()
            logging.getLogger("iof-mg").info("Email enviado para %s | ID: %s", ", ".join(self.to_addrs), result.get("id"))
            return True
        except Exception as exc:
            logging.getLogger("iof-mg").error("Falha ao enviar email: %s", exc)
            return False


class BriefingSaver:
    def __init__(self, briefing_dir: Path) -> None:
        self.briefing_dir = briefing_dir

    def save(self, report: Report, content: str, strategic_briefing: str | None = None) -> Path:
        date_str = report.publish_date.strftime("%Y-%m-%d")
        filename = self.briefing_dir / f"{date_str}.md"
        if not content.startswith("---"):
            header = f"""---
title: "Briefing IOF-MG Saúde — {report.publish_date.strftime('%d/%m/%Y')}"
date: {date_str}
tags: [briefing, iof-mg, saúde, ses-mg, publicações-oficiais, estratégico]
tipo: briefing
fonte: Jornal Minas Gerais (IOF)
gerado_por: LLM
---

"""
            content = header + content
        # Inserir briefing estratégico se fornecido (ex: injetado após LLM)
        if strategic_briefing and "## 🎯 Briefing Estratégico" not in content:
            content = content.replace("## 📊 Resumo", f"## 🎯 Briefing Estratégico\n\n{strategic_briefing}\n\n---\n\n## 📊 Resumo")
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        return filename


def run(target_date: date | None = None) -> tuple[Report, str]:
    if target_date is None:
        target_date = datetime.now(UTC).date()

    logger = logging.getLogger("iof-mg")
    logger.info("=== Briefing Estratégico IOF-MG Saúde | Data: %s ===", target_date)

    cfg = Config(DEFAULT_CONFIG_PATH)
    setup_logging(cfg)
    conn = init_search_db(cfg.search_db)

    try:
        if not has_pages(conn, target_date):
            data = consulta_iof(target_date)
            if data is None:
                logger.info("Nenhum diário publicado em %s", target_date)
                report = Report(publish_date=target_date, search_terms=cfg.terms)
                content = LLMBriefingGenerator("")._generate_empty_briefing(report)
                path = BriefingSaver(cfg.briefing_dir).save(report, content)
                return report, str(path)

            pdf_b64 = extract_pdf_base64(data)
            if not pdf_b64:
                logger.error("PDF não encontrado")
                report = Report(publish_date=target_date, search_terms=cfg.terms)
                content = LLMBriefingGenerator("")._generate_empty_briefing(report)
                path = BriefingSaver(cfg.briefing_dir).save(report, content)
                return report, str(path)

            try:
                pdf_bytes = base64.b64decode(pdf_b64)
            except Exception as exc:
                logger.error("Falha ao decodificar Base64: %s", exc)
                report = Report(publish_date=target_date, search_terms=cfg.terms)
                content = LLMBriefingGenerator("")._generate_empty_briefing(report)
                path = BriefingSaver(cfg.briefing_dir).save(report, content)
                return report, str(path)

            pages = extract_pages(pdf_bytes)
            import_pages(conn, pages, target_date)
            logger.info("%d páginas extraídas", len(pages))
        else:
            logger.info("Diário de %s já indexado", target_date)

        ocorrencias = lookup_with_context(conn, target_date, cfg.terms)
        report = Report(
            publish_date=target_date,
            ocorrencias=ocorrencias,
            search_terms=cfg.terms,
            count=len(ocorrencias),
        )
        logger.info("%d ocorrências encontradas", report.count)

        # Gerar briefing via LLM (DEVE ser feito ANTES de salvar no vault)
        # Ver references/pipeline-order-vault-save.md para o incidente 10/06/2026
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        llm = LLMBriefingGenerator(api_key)
        briefing_md = llm.generate(report)

        # Salvar no vault (depois do LLM briefing)
        saver = BriefingSaver(cfg.briefing_dir)
        path = saver.save(report, briefing_md)
        logger.info("Briefing salvo: %s", path)

        # Enviar email
        if cfg.is_email_enabled():
            try:
                import markdown as md_lib
                html_body = md_lib.markdown(briefing_md, extensions=["tables", "fenced_code"])
                html_body = f"""<html><body style="font-family:Segoe UI,sans-serif;line-height:1.6;color:#333;max-width:700px;margin:0 auto;padding:20px;">{html_body}<hr><p style="font-size:12px;color:#666;text-align:center;">🤖 Gerado automaticamente pela Engine IOF-MG Saúde | Thauma Consultoria</p></body></html>"""
            except ImportError:
                html_body = f"<pre>{briefing_md}</pre>"
            subject = f"📰 Briefing IOF-MG Saúde — {target_date.strftime('%d/%m/%Y')}"
            GmailSender(cfg.email).send(subject, html_body)

        return report, str(path)

    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Briefing Estratégico IOF-MG Saúde")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--backtest", action="store_true", help="Não envia email")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.config.exists():
        print(f"Config não encontrado: {args.config}", file=sys.stderr)
        return 1

    cfg = Config(args.config)
    logger = setup_logging(cfg)

    if args.backtest:
        cfg.email["enabled"] = False

    report, path = run(args.date)
    print(f"\n{'='*60}")
    print(f"Briefing Estratégico IOF-MG Saúde")
    print(f"Data: {report.publish_date.strftime('%d/%m/%Y')}")
    print(f"Ocorrências: {report.count}")
    print(f"Arquivo: {path}")
    print(f"{'='*60}\n")
    logger.info("=== Briefing finalizado ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
