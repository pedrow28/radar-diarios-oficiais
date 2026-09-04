"""Persistência: artefatos brutos, JSON normalizado e índice de histórico."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from radar.core.modelos import Publicacao, Resultado

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS publicacoes (
    id TEXT PRIMARY KEY,
    fonte TEXT NOT NULL,
    data_publicacao TEXT NOT NULL,
    coletado_em TEXT NOT NULL,
    orgao TEXT,
    unidade TEXT,
    secao TEXT,
    pagina INTEGER,
    edicao TEXT,
    tipo TEXT,
    numero TEXT,
    titulo TEXT NOT NULL,
    ementa TEXT,
    texto TEXT NOT NULL,
    url TEXT,
    origem TEXT
);
CREATE INDEX IF NOT EXISTS idx_pub_data ON publicacoes(data_publicacao);
CREATE INDEX IF NOT EXISTS idx_pub_fonte ON publicacoes(fonte);

CREATE VIRTUAL TABLE IF NOT EXISTS publicacoes_fts USING fts5(
    titulo, texto, content='publicacoes', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS publicacoes_ai AFTER INSERT ON publicacoes BEGIN
  INSERT INTO publicacoes_fts(rowid, titulo, texto) VALUES (new.rowid, new.titulo, new.texto);
END;
CREATE TRIGGER IF NOT EXISTS publicacoes_ad AFTER DELETE ON publicacoes BEGIN
  INSERT INTO publicacoes_fts(publicacoes_fts, rowid, titulo, texto)
    VALUES('delete', old.rowid, old.titulo, old.texto);
END;
CREATE TRIGGER IF NOT EXISTS publicacoes_au AFTER UPDATE ON publicacoes BEGIN
  INSERT INTO publicacoes_fts(publicacoes_fts, rowid, titulo, texto)
    VALUES('delete', old.rowid, old.titulo, old.texto);
  INSERT INTO publicacoes_fts(rowid, titulo, texto) VALUES (new.rowid, new.titulo, new.texto);
END;
"""

_COLUNAS = (
    "id fonte data_publicacao coletado_em orgao unidade secao pagina edicao "
    "tipo numero titulo ementa texto url origem"
).split()


class Storage:
    """Guarda o bruto, o normalizado e o histórico consultável."""

    def __init__(self, dir_dados: str | Path) -> None:
        self.dir_dados = Path(dir_dados)
        self.dir_raw = self.dir_dados / "raw"
        self.dir_normalizado = self.dir_dados / "normalized"
        self.dir_dados.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.dir_dados / "radar.db")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_ESQUEMA)
        self.conn.commit()

    # ── artefatos brutos ────────────────────────────────────────────────
    def _caminho_raw(self, data: date, fonte: str, nome: str) -> Path:
        return self.dir_raw / data.isoformat() / fonte / nome

    def salvar_raw(self, data: date, fonte: str, nome: str, conteudo: bytes) -> Path:
        caminho = self._caminho_raw(data, fonte, nome)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(conteudo)
        return caminho

    def ler_raw(self, data: date, fonte: str, nome: str) -> bytes | None:
        caminho = self._caminho_raw(data, fonte, nome)
        return caminho.read_bytes() if caminho.exists() else None

    # ── saída normalizada ───────────────────────────────────────────────
    def salvar_normalizado(self, resultado: Resultado) -> Path:
        destino = self.dir_normalizado / resultado.data_publicacao.isoformat()
        destino.mkdir(parents=True, exist_ok=True)
        caminho = destino / f"{resultado.fonte}.json"
        caminho.write_text(
            json.dumps(resultado.para_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return caminho

    # ── histórico ───────────────────────────────────────────────────────
    def gravar(self, publicacoes: list[Publicacao]) -> int:
        """Insere ou atualiza por `id`. Reexecutar o mesmo dia converge."""
        colunas = ", ".join(_COLUNAS)
        marcadores = ", ".join("?" for _ in _COLUNAS)
        atualizacoes = ", ".join(f"{c}=excluded.{c}" for c in _COLUNAS if c != "id")
        sql = (
            f"INSERT INTO publicacoes ({colunas}) VALUES ({marcadores}) "
            f"ON CONFLICT(id) DO UPDATE SET {atualizacoes}"
        )
        linhas = [
            (
                p.id, p.fonte, p.data_publicacao.isoformat(),
                p.coletado_em.isoformat(), p.orgao, p.unidade, p.secao, p.pagina,
                p.edicao, p.tipo, p.numero, p.titulo, p.ementa, p.texto, p.url,
                json.dumps(p.origem, ensure_ascii=False),
            )
            for p in publicacoes
        ]
        self.conn.executemany(sql, linhas)
        self.conn.commit()
        return len(linhas)

    def consultar(self, termo: str, desde: date | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT p.* FROM publicacoes_fts f "
            "JOIN publicacoes p ON p.rowid = f.rowid "
            "WHERE publicacoes_fts MATCH ?"
        )
        parametros: list[Any] = [termo]
        if desde is not None:
            sql += " AND p.data_publicacao >= ?"
            parametros.append(desde.isoformat())
        sql += " ORDER BY p.data_publicacao DESC"
        return [dict(linha) for linha in self.conn.execute(sql, parametros).fetchall()]

    def fechar(self) -> None:
        self.conn.close()
