#!/usr/bin/env python3
"""
Engine IOF-MG — Monitor do Diário Oficial de Minas Gerais
Template standalone: zero Flask, zero web UI, zero infra externa.

Uso:
    python3 engine.py --date 2026-05-26
    python3 engine.py  # hoje
    python3 engine.py --config config.local.yaml --date 2026-05-20
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import logging
import os
import smtplib
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import requests
import yaml

# ─── Constantes ───
V1_BASE_URL = (
    "https://www.jornalminasgerais.mg.gov.br/api/v1/Jornal/ObterEdicaoPorDataPublicacao"
)


# ─── Data Classes ───
@dataclass
class Pagina:
    num_pagina: int
    conteudo: str
    data_publicacao: date


@dataclass
class Highlight:
    page: int
    content: str
    term: str
    page_url: str


@dataclass
class Report:
    publish_date: date
    highlights: list[Highlight] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)
    count: int = 0


# ─── Config ───
class Config:
    def __init__(self, path: str | Path) -> None:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self.terms: list[str] = raw.get("search_terms", [])
        self.data_dir = Path(raw.get("data_dir", "./data"))
        self.log_dir = Path(raw.get("log_dir", "./logs"))
        self.search_db = Path(raw.get("search_db", "./data/diarios.db"))
        self.email = raw.get("email", {})
        self.output = raw.get("output", {})
        self.logging_cfg = raw.get("logging", {})
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        Path(self.search_db).parent.mkdir(parents=True, exist_ok=True)
        csv_dir = Path(self.output.get("csv_dir", "./data/csv"))
        csv_dir.mkdir(parents=True, exist_ok=True)

    def is_email_enabled(self) -> bool:
        return bool(self.email.get("enabled", False))


# ─── Logging ───
def setup_logging(cfg: Config) -> logging.Logger:
    level = cfg.logging_cfg.get("level", "INFO")
    fmt = cfg.logging_cfg.get("format", "%(asctime)s | %(levelname)-8s | %(message)s")
    log_file = cfg.log_dir / f"engine_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.log"
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO), format=fmt, handlers=handlers
    )
    return logging.getLogger("iof-mg")


# ─── PDF Extractor (PyMuPDF — pure Python, no system deps) ───
class PDFExtractor:
    def extract_pages(self, pdf_bytes: bytes) -> list[Pagina]:
        import fitz  # PyMuPDF

        pages: list[Pagina] = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page_num, page in enumerate(doc, start=1):
                pages.append(
                    Pagina(
                        num_pagina=page_num,
                        conteudo=page.get_text(),
                        data_publicacao=date.today(),
                    )
                )
        return pages


# ─── API Client ───
class IOFClient:
    def consulta_por_data(self, publish_date: date) -> dict[str, Any] | None:
        params = urlencode({"dataPublicacao": publish_date.strftime("%Y-%m-%d")})
        url = f"{V1_BASE_URL}?{params}"
        logger = logging.getLogger("iof-mg")
        logger.info("Consultando IOF-MG: %s", publish_date.isoformat())
        try:
            response = requests.get(url, timeout=30)
        except requests.RequestException as exc:
            logger.error("Falha na requisição: %s", exc)
            return None
        if response.status_code == 401:
            logger.warning("Nenhum diário encontrado para %s", publish_date.isoformat())
            return None
        if response.status_code != 200:
            logger.error("HTTP %d: %s", response.status_code, response.text[:200])
            return None
        return response.json()

    def extract_pdf_base64(self, data: dict[str, Any]) -> str:
        dados = data.get("dados", {})
        arquivo_data = dados.get("arquivoCadernoPrincipal", {})
        return str(arquivo_data.get("arquivo", ""))


# ─── Search Engine (SQLite FTS5) ───
class SearchEngine:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
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
        self.conn.executescript(schema)
        self.conn.commit()

    def import_pages(self, pages: list[Pagina]) -> None:
        query = (
            "REPLACE INTO documentos (num_pagina, conteudo, data_publicacao) VALUES (?, ?, ?)"
        )
        cursor = self.conn.cursor()
        try:
            for page in pages:
                cursor.execute(
                    query,
                    (
                        page.num_pagina,
                        page.conteudo,
                        page.data_publicacao.strftime("%Y-%m-%d"),
                    ),
                )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def lookup(self, publish_date: date, terms: list[str]) -> Report:
        highlights: list[Highlight] = []
        date_str = publish_date.strftime("%Y-%m-%d")
        for term in terms:
            search_term = f'"{term}"'
            query = """
                SELECT doc.num_pagina,
                       snippet(documentos_fts, 0, '<b>', '</b>', '...', 32) AS trecho
                FROM documentos_fts
                INNER JOIN documentos doc ON documentos_fts.rowid = doc.id
                WHERE doc.data_publicacao = ? AND documentos_fts MATCH ?
            """
            cursor = self.conn.cursor()
            cursor.execute(query, (date_str, search_term))
            for row in cursor.fetchall():
                page_url = self._page_url(publish_date, row["num_pagina"])
                highlights.append(
                    Highlight(
                        page=row["num_pagina"],
                        content=row["trecho"],
                        term=term,
                        page_url=page_url,
                    )
                )
        return Report(
            publish_date=publish_date,
            highlights=highlights,
            search_terms=terms,
            count=len(highlights),
        )

    def has_pages(self, publish_date: date) -> bool:
        query = "SELECT COUNT(*) FROM documentos WHERE data_publicacao = ?"
        cursor = self.conn.cursor()
        cursor.execute(query, (publish_date.strftime("%Y-%m-%d"),))
        return bool(cursor.fetchone()[0] > 0)

    @staticmethod
    def _page_url(publish_date: date, page_num: int, notebook_id: int = 326074) -> str:
        date_str = publish_date.strftime("%Y-%m-%d")
        payload = {
            "dataPublicacaoSelecionada": f"{date_str}T03:00:00.000Z",
            "idCadernoEdicaoSelecionado": notebook_id,
            "paginaSelecionada": page_num,
        }
        encoded = quote(json.dumps(payload, separators=(",", ":")))
        return (
            "https://www.jornalminasgerais.mg.gov.br/edicao-do-dia?dados=" + encoded
        )

    def close(self) -> None:
        if self.conn:
            self.conn.close()

    def __enter__(self) -> SearchEngine:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ─── CSV Generator ───
class CSVGenerator:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def generate(self, report: Report) -> Path:
        date_str = report.publish_date.strftime("%Y-%m-%d")
        filename = self.output_dir / f"iof_mg_{date_str}.csv"
        with open(filename, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_ALL)
            writer.writerow(["Data Publicação", "Termo", "Página", "Conteúdo", "Link"])
            for hl in report.highlights:
                content = hl.content.replace("<b>", "").replace("</b>", "").strip()
                writer.writerow(
                    [
                        report.publish_date.strftime("%d/%m/%Y"),
                        hl.term,
                        hl.page,
                        content,
                        hl.page_url,
                    ]
                )
        return filename


# ─── Email Sender ───
class EmailSender:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.host = cfg.get("smtp_host", "localhost")
        self.port = int(cfg.get("smtp_port", 587))
        self.user = cfg.get("smtp_user", "")
        self.password = cfg.get("smtp_password", "")
        self.use_tls = bool(cfg.get("use_tls", True))
        self.from_addr = cfg.get("from_address", "notificador@local")
        self.to_addrs = cfg.get("to_addresses", [])
        self.subject_template = cfg.get(
            "subject_template", "[IOF-MG] {count} ocorrências em {date}"
        )
        self.attach_csv = bool(cfg.get("attach_csv", True))

    def send(self, report: Report, csv_path: Path | None = None) -> bool:
        if not self.to_addrs:
            logging.getLogger("iof-mg").warning("Nenhum destinatário configurado")
            return False
        subject = self.subject_template.format(
            count=report.count, date=report.publish_date.strftime("%d/%m/%Y")
        )
        msg = MIMEMultipart()
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)
        msg["Subject"] = subject
        msg.attach(MIMEText(self._build_text(report), "plain", "utf-8"))
        msg.attach(MIMEText(self._build_html(report), "html", "utf-8"))
        if self.attach_csv and csv_path and csv_path.exists():
            with open(csv_path, "rb") as f:
                attachment = MIMEApplication(f.read(), _subtype="csv")
            attachment.add_header(
                "Content-Disposition", "attachment", filename=csv_path.name
            )
            msg.attach(attachment)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                if self.use_tls:
                    server.starttls()
                if self.user and self.password:
                    server.login(self.user, self.password)
                server.sendmail(self.from_addr, self.to_addrs, msg.as_string())
            logging.getLogger("iof-mg").info(
                "Email enviado para %s", ", ".join(self.to_addrs)
            )
            return True
        except Exception as exc:
            logging.getLogger("iof-mg").error("Falha ao enviar email: %s", exc)
            return False

    @staticmethod
    def _build_text(report: Report) -> str:
        lines = [
            f"Diário Oficial de MG — {report.publish_date.strftime('%d/%m/%Y')}",
            f"Termos: {', '.join(report.search_terms)}",
            f"Ocorrências: {report.count}",
            "",
            "Destaques:",
        ]
        for hl in report.highlights:
            content = hl.content.replace("<b>", "").replace("</b>", "").strip()
            lines.append(f"  Página {hl.page} ({hl.term}): {content}")
            lines.append(f"  Link: {hl.page_url}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _build_html(report: Report) -> str:
        date_str = report.publish_date.strftime("%d/%m/%Y")
        html = f"""<html><body>
        <h2>Diário Oficial de MG — {date_str}</h2>
        <p><strong>Termos:</strong> {', '.join(report.search_terms)}</p>
        <p><strong>Ocorrências:</strong> {report.count}</p>
        <hr><ul>
        """
        for hl in report.highlights:
            content = hl.content.replace("<b>", "<strong>").replace("</b>", "</strong>")
            html += f"""
            <li><strong>Página {hl.page}</strong> — <em>{hl.term}</em><br>
                {content}<br><a href="{hl.page_url}">Ver no Jornal MG</a></li>
            """
        html += "</ul></body></html>"
        return html


# ─── Main Engine ───
class IOFMGEngine:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.logger = logging.getLogger("iof-mg")
        self.client = IOFClient()
        self.extractor = PDFExtractor()
        self.csv_gen = CSVGenerator(Path(cfg.output.get("csv_dir", "./data/csv")))

    def run(self, target_date: date | None = None) -> Report:
        if target_date is None:
            target_date = datetime.now(UTC).date()
        self.logger.info("=== Engine IOF-MG | Data: %s ===", target_date)
        with SearchEngine(self.cfg.search_db) as search:
            if search.has_pages(target_date):
                self.logger.info("Diário já indexado. Buscando termos...")
            else:
                data = self.client.consulta_por_data(target_date)
                if data is None:
                    return Report(publish_date=target_date, search_terms=self.cfg.terms)
                pdf_b64 = self.client.extract_pdf_base64(data)
                if not pdf_b64:
                    self.logger.error("PDF não encontrado")
                    return Report(publish_date=target_date, search_terms=self.cfg.terms)
                try:
                    pdf_bytes = base64.b64decode(pdf_b64)
                except Exception as exc:
                    self.logger.error("Falha ao decodificar Base64: %s", exc)
                    return Report(publish_date=target_date, search_terms=self.cfg.terms)
                pages = self.extractor.extract_pages(pdf_bytes)
                for p in pages:
                    p.data_publicacao = target_date
                self.logger.info("%d páginas extraídas", len(pages))
                search.import_pages(pages)
            report = search.lookup(target_date, self.cfg.terms)
            self.logger.info("%d ocorrências", report.count)
            csv_path: Path | None = None
            if self.cfg.output.get("save_csv", True) and report.count > 0:
                csv_path = self.csv_gen.generate(report)
                self.logger.info("CSV: %s", csv_path)
            if self.cfg.is_email_enabled() and report.count > 0:
                EmailSender(self.cfg.email).send(report, csv_path)
            return report


# ─── CLI ───
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Engine IOF-MG")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--backtest", action="store_true", help="Sem envio de email")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.config.exists():
        print(f"Config não encontrado: {args.config}", file=sys.stderr)
        return 1
    cfg = Config(args.config)
    setup_logging(cfg)
    report = IOFMGEngine(cfg).run(args.date)
    print(f"\n{'='*60}")
    print(f"IOF-MG | {report.publish_date.strftime('%d/%m/%Y')}")
    print(f"Termos: {', '.join(report.search_terms)}")
    print(f"Ocorrências: {report.count}")
    if report.count > 0:
        for hl in report.highlights:
            content = hl.content.replace("<b>", "").replace("</b>", "").strip()[:120]
            print(f"  Pg {hl.page:3d} | {hl.term:30s} | {content}...")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
