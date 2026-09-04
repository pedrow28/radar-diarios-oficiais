# Radar de Diários Oficiais — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir o pacote `radar`, que coleta as publicações de saúde do DOU e do IOF-MG e as entrega como JSON normalizado com texto integral para o agente Hermes.

**Architecture:** Pacote único com núcleo compartilhado (`radar/core/`) e um adaptador por fonte (`radar/fontes/dou/`, `radar/fontes/iofmg/`), cada um implementando `coletar(data) -> Resultado`. O DOU é coletado por HTTP simples lendo o `jsonArray` embutido na busca (sem browser) mais uma segunda passada pelo inteiro teor de cada publicação. O IOF-MG vem da API oficial, com o PDF desembrulhado de um envelope PKCS#7 e recortado pelo índice de seções que a própria API fornece. Persistência em JSON por dia/fonte mais SQLite com FTS5 para histórico.

**Tech Stack:** Python 3.11+, `requests`, `PyMuPDF` (fitz), `asn1crypto`, `PyYAML`, `pytest`. Sem Playwright. Sem dependência de `openssl` no sistema.

**Spec:** `docs/superpowers/specs/2026-09-04-radar-diarios-oficiais-design.md`

## Global Constraints

Estes valores vêm da spec e valem para **todas** as tasks:

- **Idioma do código:** identificadores, mensagens de log e docstrings em português do Brasil, seguindo o padrão dos scripts existentes.
- **Timezone:** `America/Sao_Paulo` em toda resolução de "hoje". Nunca `datetime.now(UTC).date()` para decidir data de edição.
- **Campo desconhecido é `None`**, nunca inventado. Proibido inferir `secao`, `tipo` ou `numero` por palavra-chave no título.
- **`Publicacao.texto` é o inteiro teor.** Nunca um snippet truncado.
- **Nenhum campo de juízo** (`score`, `is_sus`, `impacto`, `relevancia`). O juízo é do Hermes.
- **Sem segredo no código.** E-mail, chaves e caminhos de usuário vêm de `config.yaml` ou variável de ambiente.
- **Encoding do DOU:** UTF-8 nas duas páginas, header declarado correto (verificado contra o site). `decodificar_busca` tenta UTF-8 e só cai em ISO-8859-1 se os bytes não forem UTF-8 válido.
- **ID do caderno IOF-MG** sempre lido de `cadernos[].id`. Nunca constante.
- **Toda exceção de coleta** é `SemEdicao`, `ExtracaoParcial` ou `FonteIndisponivel`. Nada de `except:` pelado.
- **Testes rodam offline**, contra as fixtures em `tests/fixtures/`. Nenhum teste faz requisição de rede.
- Rodar tudo com `python -m pytest`. Comandos `git commit` usam o trailer já adotado no repo.

---

### Task 1: Scaffold do projeto

**Files:**
- Create: `pyproject.toml`
- Create: `radar/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_scaffold.py`

**Interfaces:**
- Consumes: nada
- Produces: pacote `radar` importável; fixture pytest `dir_fixtures: Path` apontando para `tests/fixtures/`.

- [ ] **Step 1: Write the failing test**

`tests/test_scaffold.py`:

```python
from pathlib import Path

import radar


def test_pacote_importavel():
    assert radar.__version__


def test_fixtures_presentes(dir_fixtures: Path):
    assert (dir_fixtures / "dou" / "busca-ms-2026-09-03-p1.html").exists()
    assert (dir_fixtures / "dou" / "busca-ms-2026-09-03-p2.html").exists()
    assert (dir_fixtures / "dou" / "pub-portaria-gm-ms-12141.html").exists()
    assert (dir_fixtures / "iofmg" / "edicao-2026-09-03.meta.json").exists()
    assert (dir_fixtures / "iofmg" / "caderno-2026-09-03-ses.pdf").exists()
    assert (dir_fixtures / "iofmg" / "envelope-pkcs7-2026-09-03.bin.gz").exists()
```

`tests/conftest.py`:

```python
from pathlib import Path

import pytest


@pytest.fixture
def dir_fixtures() -> Path:
    return Path(__file__).parent / "fixtures"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scaffold.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar'`

- [ ] **Step 3: Write minimal implementation**

`radar/__init__.py`:

```python
"""Radar de Diários Oficiais — coleta DOU e IOF-MG para consumo por agente."""

__version__ = "0.1.0"
```

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "radar-diarios"
version = "0.1.0"
description = "Coleta normalizada do DOU e do Diário Oficial de MG para consumo por agente"
requires-python = ">=3.11"
dependencies = [
    "requests>=2.31",
    "PyMuPDF>=1.24",
    "asn1crypto>=1.5",
    "PyYAML>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
radar = "radar.cli:executar"

[tool.setuptools.packages.find]
include = ["radar*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pip install -e ".[dev]"` e depois `python -m pytest tests/test_scaffold.py -v`
Expected: PASS (2 testes)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml radar/__init__.py tests/conftest.py tests/test_scaffold.py
git commit -m "feat: scaffold do pacote radar com fixtures de teste"
```

---

### Task 2: Erros, Status e modelos de dados

**Files:**
- Create: `radar/core/__init__.py`
- Create: `radar/core/erros.py`
- Create: `radar/core/modelos.py`
- Create: `tests/test_modelos.py`

**Interfaces:**
- Consumes: nada
- Produces:
  - `Status` (StrEnum): `OK`, `VAZIO`, `PARCIAL`, `ERRO`
  - `ErroRadar`, `SemEdicao(ErroRadar)`, `FonteIndisponivel(ErroRadar)`, `ExtracaoParcial(ErroRadar)` com `.avisos: list[str]`
  - `status_para_exit(status: Status) -> int`
  - `gerar_id(fonte: str, data_publicacao: date, url: str, titulo: str) -> str`
  - `Publicacao` (frozen dataclass) e `Resultado` com `.para_dict() -> dict`

- [ ] **Step 1: Write the failing test**

`tests/test_modelos.py`:

```python
from datetime import date, datetime, timezone

import pytest

from radar.core.erros import (
    ExtracaoParcial,
    FonteIndisponivel,
    SemEdicao,
    Status,
    status_para_exit,
)
from radar.core.modelos import Publicacao, Resultado, gerar_id


def _pub(**kw) -> Publicacao:
    base = dict(
        fonte="dou",
        data_publicacao=date(2026, 9, 4),
        coletado_em=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
        orgao="Ministério da Saúde",
        unidade="Gabinete do Ministro",
        secao="1",
        pagina=None,
        edicao="168",
        tipo="Portaria",
        numero="12.141",
        titulo="Portaria GM/MS Nº 12.141",
        ementa="Renova qualificação.",
        texto="Texto integral da portaria.",
        url="https://www.in.gov.br/web/dou/-/x",
        origem={"metodo": "teste"},
    )
    base.update(kw)
    base["id"] = gerar_id(base["fonte"], base["data_publicacao"], base["url"], base["titulo"])
    return Publicacao(**base)


def test_status_mapeia_para_exit_code():
    assert status_para_exit(Status.OK) == 0
    assert status_para_exit(Status.VAZIO) == 0
    assert status_para_exit(Status.PARCIAL) == 1
    assert status_para_exit(Status.ERRO) == 2


def test_id_e_estavel_e_deterministico():
    a = gerar_id("dou", date(2026, 9, 4), "https://x/1", "Portaria 1")
    b = gerar_id("dou", date(2026, 9, 4), "https://x/1", "Portaria 1")
    assert a == b and len(a) == 16


def test_id_muda_quando_a_url_muda():
    a = gerar_id("dou", date(2026, 9, 4), "https://x/1", "Portaria 1")
    b = gerar_id("dou", date(2026, 9, 4), "https://x/2", "Portaria 1")
    assert a != b


def test_publicacao_e_imutavel():
    pub = _pub()
    with pytest.raises(Exception):
        pub.titulo = "outro"


def test_resultado_serializa_para_dict_com_contrato_da_spec():
    pub = _pub()
    r = Resultado(
        fonte="dou",
        data_publicacao=date(2026, 9, 4),
        coletado_em=datetime(2026, 9, 4, 12, 7, 41, tzinfo=timezone.utc),
        status=Status.OK,
        escopo={"orgao": "Ministério da Saúde"},
        publicacoes=[pub],
        avisos=[],
    )
    d = r.para_dict()
    assert d["schema_versao"] == "1.0"
    assert d["fonte"] == "dou"
    assert d["data_publicacao"] == "2026-09-04"
    assert d["coletado_em"] == "2026-09-04T12:07:41Z"
    assert d["status"] == "ok"
    assert d["total"] == 1
    assert d["avisos"] == []
    assert d["publicacoes"][0]["texto"] == "Texto integral da portaria."
    assert d["publicacoes"][0]["data_publicacao"] == "2026-09-04"


def test_resultado_total_acompanha_a_lista():
    r = Resultado(
        fonte="dou",
        data_publicacao=date(2026, 9, 4),
        coletado_em=datetime(2026, 9, 4, tzinfo=timezone.utc),
        status=Status.VAZIO,
        escopo={},
        publicacoes=[],
        avisos=["sem edição"],
    )
    assert r.para_dict()["total"] == 0


def test_extracao_parcial_carrega_avisos():
    exc = ExtracaoParcial("paginação travou", avisos=["página 3 repetida"])
    assert exc.avisos == ["página 3 repetida"]
    assert isinstance(exc, Exception)


def test_hierarquia_de_erros():
    from radar.core.erros import ErroRadar

    assert issubclass(SemEdicao, ErroRadar)
    assert issubclass(FonteIndisponivel, ErroRadar)
    assert issubclass(ExtracaoParcial, ErroRadar)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_modelos.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.core'`

- [ ] **Step 3: Write minimal implementation**

`radar/core/__init__.py`:

```python
"""Núcleo compartilhado entre as fontes."""
```

`radar/core/erros.py`:

```python
"""Erros tipados e o status de coleta que cada um produz.

O contrato com o agente consumidor depende desta distinção: sem ela, queda de
rede, HTTP 500 e domingo sem edição ficam indistinguíveis.
"""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    OK = "ok"
    VAZIO = "vazio"
    PARCIAL = "parcial"
    ERRO = "erro"


_EXIT_POR_STATUS = {
    Status.OK: 0,
    Status.VAZIO: 0,
    Status.PARCIAL: 1,
    Status.ERRO: 2,
}


def status_para_exit(status: Status) -> int:
    """Converte o status em exit code, para o agente decidir pelo código."""
    return _EXIT_POR_STATUS[status]


class ErroRadar(Exception):
    """Base de todos os erros de coleta."""


class SemEdicao(ErroRadar):
    """Não houve edição publicada nesta data (feriado, domingo, 401 da API)."""


class FonteIndisponivel(ErroRadar):
    """A fonte não respondeu ou respondeu com erro de servidor."""


class ExtracaoParcial(ErroRadar):
    """Coletou, mas parte do conteúdo não pôde ser obtida."""

    def __init__(self, mensagem: str, avisos: list[str] | None = None) -> None:
        super().__init__(mensagem)
        self.avisos = avisos or []
```

`radar/core/modelos.py`:

```python
"""Modelo de dado comum às duas fontes."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from radar.core.erros import Status

SCHEMA_VERSAO = "1.0"


def gerar_id(fonte: str, data_publicacao: date, url: str, titulo: str) -> str:
    """Identificador estável de uma publicação.

    Estável entre execuções, para que reprocessar um dia faça UPSERT em vez de
    duplicar, e para que o agente possa marcar o que já processou.
    """
    semente = f"{fonte}|{data_publicacao.isoformat()}|{url}|{titulo}"
    return hashlib.sha256(semente.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Publicacao:
    id: str
    fonte: Literal["dou", "iofmg"]
    data_publicacao: date
    coletado_em: datetime

    orgao: str
    unidade: str | None
    secao: str | None
    pagina: int | None
    edicao: str | None

    tipo: str | None
    numero: str | None
    titulo: str
    ementa: str | None
    texto: str
    url: str

    origem: dict[str, Any] = field(default_factory=dict)

    def para_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["data_publicacao"] = self.data_publicacao.isoformat()
        d["coletado_em"] = _iso_utc(self.coletado_em)
        return d


@dataclass
class Resultado:
    fonte: str
    data_publicacao: date
    coletado_em: datetime
    status: Status
    escopo: dict[str, Any]
    publicacoes: list[Publicacao] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def para_dict(self) -> dict[str, Any]:
        return {
            "schema_versao": SCHEMA_VERSAO,
            "fonte": self.fonte,
            "data_publicacao": self.data_publicacao.isoformat(),
            "coletado_em": _iso_utc(self.coletado_em),
            "status": str(self.status),
            "escopo": self.escopo,
            "total": len(self.publicacoes),
            "avisos": self.avisos,
            "publicacoes": [p.para_dict() for p in self.publicacoes],
        }


def _iso_utc(momento: datetime) -> str:
    """Serializa em ISO-8601 com sufixo Z, sem microssegundos."""
    return momento.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_modelos.py -v`
Expected: PASS (8 testes)

- [ ] **Step 5: Commit**

```bash
git add radar/core/__init__.py radar/core/erros.py radar/core/modelos.py tests/test_modelos.py
git commit -m "feat: modelo Publicacao/Resultado e erros tipados com status"
```

---

### Task 3: Datas em America/Sao_Paulo

Corrige o bug 6 da spec: `datetime.now(UTC).date()` faz o cron pedir a data de amanhã em qualquer execução após as 21h BRT.

**Files:**
- Create: `radar/core/datas.py`
- Create: `tests/test_datas.py`

**Interfaces:**
- Consumes: nada
- Produces: `TZ_BR: ZoneInfo`, `hoje() -> date`, `agora_utc() -> datetime`, `parse_data(texto: str) -> date`

- [ ] **Step 1: Write the failing test**

`tests/test_datas.py`:

```python
from datetime import date, datetime, timezone

import pytest

from radar.core.datas import TZ_BR, agora_utc, hoje, parse_data


def test_hoje_usa_fuso_de_sao_paulo_e_nao_utc(monkeypatch):
    """As 23h de 04/09 em Sao Paulo ainda sao 04/09, embora ja seja 05/09 em UTC."""
    import radar.core.datas as mod

    class RelogioFalso(datetime):
        @classmethod
        def now(cls, tz=None):
            instante = datetime(2026, 9, 5, 2, 30, tzinfo=timezone.utc)
            return instante.astimezone(tz) if tz else instante

    monkeypatch.setattr(mod, "datetime", RelogioFalso)
    assert hoje() == date(2026, 9, 4)


def test_agora_utc_tem_tzinfo():
    momento = agora_utc()
    assert momento.tzinfo is not None
    assert momento.utcoffset().total_seconds() == 0


def test_parse_data_aceita_iso():
    assert parse_data("2026-09-04") == date(2026, 9, 4)


def test_parse_data_aceita_formato_brasileiro():
    assert parse_data("04/09/2026") == date(2026, 9, 4)


def test_parse_data_rejeita_lixo():
    with pytest.raises(ValueError):
        parse_data("ontem")


def test_tz_br_e_sao_paulo():
    assert str(TZ_BR) == "America/Sao_Paulo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_datas.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.core.datas'`

- [ ] **Step 3: Write minimal implementation**

`radar/core/datas.py`:

```python
"""Resolução de datas no fuso do diário, não no do servidor."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

TZ_BR = ZoneInfo("America/Sao_Paulo")

_FORMATOS = ("%Y-%m-%d", "%d/%m/%Y")


def hoje() -> date:
    """Data de hoje no fuso de São Paulo.

    Usar UTC aqui faz qualquer execução após as 21h BRT pedir a edição de
    amanhã, que não existe.
    """
    return datetime.now(TZ_BR).date()


def agora_utc() -> datetime:
    """Instante atual em UTC, para carimbar `coletado_em`."""
    return datetime.now(timezone.utc)


def parse_data(texto: str) -> date:
    """Interpreta AAAA-MM-DD ou DD/MM/AAAA."""
    for formato in _FORMATOS:
        try:
            return datetime.strptime(texto.strip(), formato).date()
        except ValueError:
            continue
    raise ValueError(f"Data inválida: {texto!r}. Use AAAA-MM-DD ou DD/MM/AAAA.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_datas.py -v`
Expected: PASS (6 testes)

- [ ] **Step 5: Commit**

```bash
git add radar/core/datas.py tests/test_datas.py
git commit -m "feat: datas resolvidas em America/Sao_Paulo"
```

---

### Task 4: Config e logging

Corrige o bug 7 da spec: `setup_logging()` chamado duas vezes duplica cada linha de log e cria dois arquivos por execução.

**Files:**
- Create: `radar/core/config.py`
- Create: `radar/core/log.py`
- Create: `config/config.yaml`
- Create: `config/.env.example`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: nada
- Produces:
  - `Config.carregar(caminho: Path) -> Config` com atributos `timezone: str`, `dou: ConfigDOU`, `iofmg: ConfigIOFMG`, `dir_dados: Path`, `reter_bruto_dias: int`, `email: dict`
  - `ConfigDOU`: `orgao: str`, `delta: int`, `concorrencia: int`, `baixar_texto_integral: bool`
  - `ConfigIOFMG`: `caderno: str`, `secao: str`, `tipos_publicacao: list[str]`
  - `configurar_log(nivel: str = "INFO", arquivo: Path | None = None) -> logging.Logger`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:

```python
import logging
from pathlib import Path

import pytest

from radar.core.config import Config
from radar.core.log import configurar_log

YAML_MINIMO = """
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
    tipos_publicacao: [PORTARIA, RESOLUÇÃO, DELIBERAÇÃO]
armazenamento:
  dir_dados: ./data
  reter_bruto_dias: 30
"""


@pytest.fixture
def caminho_config(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(YAML_MINIMO, encoding="utf-8")
    return p


def test_carrega_config_do_yaml(caminho_config: Path):
    cfg = Config.carregar(caminho_config)
    assert cfg.timezone == "America/Sao_Paulo"
    assert cfg.dou.orgao == "Ministério da Saúde"
    assert cfg.dou.delta == 75
    assert cfg.dou.baixar_texto_integral is True
    assert cfg.iofmg.secao == "Secretaria de Estado de Saúde"
    assert "DELIBERAÇÃO" in cfg.iofmg.tipos_publicacao
    assert cfg.reter_bruto_dias == 30


def test_tipos_de_publicacao_sao_configuraveis_nao_fixos(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text(
        YAML_MINIMO.replace("[PORTARIA, RESOLUÇÃO, DELIBERAÇÃO]", "[EDITAL]"),
        encoding="utf-8",
    )
    assert Config.carregar(p).iofmg.tipos_publicacao == ["EDITAL"]


def test_config_inexistente_da_erro_claro(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        Config.carregar(tmp_path / "nao-existe.yaml")


def test_nenhum_email_hardcoded_no_pacote():
    """Regressão: hoje pedrowilliamrd@gmail.com está fixo em 2 scripts."""
    raiz = Path(__file__).resolve().parent.parent / "radar"
    for arquivo in raiz.rglob("*.py"):
        assert "@gmail.com" not in arquivo.read_text(encoding="utf-8"), arquivo


def test_configurar_log_e_idempotente(tmp_path: Path):
    """Chamar duas vezes nao pode duplicar handlers (bug 7 da spec)."""
    destino = tmp_path / "radar.log"
    primeiro = configurar_log(arquivo=destino)
    quantos = len(primeiro.handlers)
    segundo = configurar_log(arquivo=destino)
    assert segundo is primeiro
    assert len(segundo.handlers) == quantos


def test_configurar_log_escreve_no_arquivo(tmp_path: Path):
    destino = tmp_path / "radar.log"
    logger = configurar_log(arquivo=destino)
    logger.info("mensagem de teste")
    for h in logger.handlers:
        h.flush()
    assert "mensagem de teste" in destino.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _limpa_logger():
    yield
    logger = logging.getLogger("radar")
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.core.config'`

- [ ] **Step 3: Write minimal implementation**

`radar/core/config.py`:

```python
"""Configuração da aplicação. Comportamento no YAML, segredo no ambiente."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ConfigDOU:
    orgao: str = "Ministério da Saúde"
    delta: int = 75
    concorrencia: int = 5
    baixar_texto_integral: bool = True


@dataclass
class ConfigIOFMG:
    caderno: str = "Diário do Executivo"
    secao: str = "Secretaria de Estado de Saúde"
    tipos_publicacao: list[str] = field(default_factory=list)


@dataclass
class Config:
    timezone: str = "America/Sao_Paulo"
    dou: ConfigDOU = field(default_factory=ConfigDOU)
    iofmg: ConfigIOFMG = field(default_factory=ConfigIOFMG)
    dir_dados: Path = Path("./data")
    reter_bruto_dias: int = 30
    email: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def carregar(cls, caminho: str | Path) -> Config:
        caminho = Path(caminho)
        if not caminho.exists():
            raise FileNotFoundError(f"Config não encontrado: {caminho}")
        bruto = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
        fontes = bruto.get("fontes", {})
        armazenamento = bruto.get("armazenamento", {})
        return cls(
            timezone=bruto.get("timezone", "America/Sao_Paulo"),
            dou=ConfigDOU(**fontes.get("dou", {})),
            iofmg=ConfigIOFMG(**fontes.get("iofmg", {})),
            dir_dados=Path(armazenamento.get("dir_dados", "./data")),
            reter_bruto_dias=int(armazenamento.get("reter_bruto_dias", 30)),
            email=bruto.get("email", {}),
        )
```

`radar/core/log.py`:

```python
"""Logging configurado uma única vez por processo."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

NOME = "radar"
_FORMATO = "%(asctime)s | %(levelname)-8s | %(message)s"


def configurar_log(nivel: str = "INFO", arquivo: Path | None = None) -> logging.Logger:
    """Devolve o logger do radar, configurando-o só na primeira chamada.

    Idempotente de propósito: os scripts atuais chamam o setup no `main()` e de
    novo dentro do `run()`, o que duplica cada linha e cria dois arquivos de log.
    """
    logger = logging.getLogger(NOME)
    if getattr(logger, "_radar_configurado", False):
        return logger

    logger.setLevel(getattr(logging, nivel.upper(), logging.INFO))
    logger.propagate = False

    formatador = logging.Formatter(_FORMATO)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatador)
    logger.addHandler(console)

    if arquivo is not None:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        em_disco = logging.FileHandler(arquivo, encoding="utf-8")
        em_disco.setFormatter(formatador)
        logger.addHandler(em_disco)

    logger._radar_configurado = True  # type: ignore[attr-defined]
    return logger
```

`config/config.yaml`:

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
    tipos_publicacao:
      - PORTARIA
      - RESOLUÇÃO
      - DECRETO
      - DELIBERAÇÃO
      - EXTRATO
      - EDITAL
      - ATO
      - AVISO

armazenamento:
  dir_dados: ./data
  reter_bruto_dias: 30

# Opcional. Só usado por `radar notificar`. Credenciais vêm do ambiente.
email:
  habilitado: false
  destinatarios: []
```

`config/.env.example`:

```bash
# Copie para .env e preencha. O .env nunca é versionado.

# Envio de e-mail via SMTP (opcional, usado só por `radar notificar`)
RADAR_SMTP_HOST=
RADAR_SMTP_PORT=587
RADAR_SMTP_USER=
RADAR_SMTP_PASSWORD=
RADAR_EMAIL_FROM=
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (6 testes)

- [ ] **Step 5: Commit**

```bash
git add radar/core/config.py radar/core/log.py config/ tests/test_config.py
git commit -m "feat: config em YAML e logging idempotente"
```

---

### Task 5: Cliente HTTP com retry e encoding explícito

Corrige o bug 5 da spec: hoje um 404 ou 401 é retentado com backoff como se fosse falha transitória, gastando ~12s por modelo/URL inválida.

**Files:**
- Create: `radar/core/http.py`
- Create: `tests/test_http.py`

**Interfaces:**
- Consumes: `radar.core.erros.{FonteIndisponivel, SemEdicao}`
- Produces:
  - `criar_sessao(user_agent: str | None = None) -> requests.Session`
  - `obter_bytes(sessao, url: str, *, tentativas: int = 3, espera_base: float = 1.0) -> bytes`
  - `obter_texto(sessao, url: str, *, encoding: str, tentativas: int = 3, espera_base: float = 1.0) -> str`

- [ ] **Step 1: Write the failing test**

`tests/test_http.py`:

```python
import pytest
import requests

from radar.core.erros import FonteIndisponivel, SemEdicao
from radar.core.http import criar_sessao, obter_bytes, obter_texto


class RespostaFalsa:
    def __init__(self, status: int, corpo: bytes = b"ok"):
        self.status_code = status
        self.content = corpo


class SessaoFalsa:
    """Devolve as respostas programadas, uma por chamada, contando tentativas."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = 0

    def get(self, url, timeout=None):
        self.chamadas += 1
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_sucesso_devolve_bytes():
    s = SessaoFalsa([RespostaFalsa(200, b"conteudo")])
    assert obter_bytes(s, "https://x", espera_base=0) == b"conteudo"
    assert s.chamadas == 1


def test_erro_permanente_nao_e_retentado():
    """404 nunca vira sucesso; retentar so desperdica tempo."""
    s = SessaoFalsa([RespostaFalsa(404)])
    with pytest.raises(FonteIndisponivel):
        obter_bytes(s, "https://x", tentativas=3, espera_base=0)
    assert s.chamadas == 1


def test_401_vira_sem_edicao():
    """A API do IOF-MG responde 401 quando nao ha diario na data."""
    s = SessaoFalsa([RespostaFalsa(401)])
    with pytest.raises(SemEdicao):
        obter_bytes(s, "https://x", espera_base=0)
    assert s.chamadas == 1


def test_erro_transitorio_e_retentado_ate_o_limite():
    s = SessaoFalsa([RespostaFalsa(503), RespostaFalsa(503), RespostaFalsa(503)])
    with pytest.raises(FonteIndisponivel):
        obter_bytes(s, "https://x", tentativas=3, espera_base=0)
    assert s.chamadas == 3


def test_erro_transitorio_que_se_resolve():
    s = SessaoFalsa([RespostaFalsa(500), RespostaFalsa(200, b"agora vai")])
    assert obter_bytes(s, "https://x", tentativas=3, espera_base=0) == b"agora vai"
    assert s.chamadas == 2


def test_429_e_tratado_como_transitorio():
    s = SessaoFalsa([RespostaFalsa(429), RespostaFalsa(200, b"ok")])
    assert obter_bytes(s, "https://x", tentativas=3, espera_base=0) == b"ok"


def test_timeout_de_rede_e_retentado():
    s = SessaoFalsa([requests.exceptions.Timeout(), RespostaFalsa(200, b"ok")])
    assert obter_bytes(s, "https://x", tentativas=3, espera_base=0) == b"ok"


def test_obter_texto_respeita_o_encoding_pedido_e_ignora_o_declarado():
    """A busca do DOU declara UTF-8 mas e ISO-8859-1."""
    corpo = "Ministério da Saúde".encode("iso-8859-1")
    s = SessaoFalsa([RespostaFalsa(200, corpo)])
    assert obter_texto(s, "https://x", encoding="iso-8859-1", espera_base=0) == "Ministério da Saúde"


def test_sessao_tem_user_agent():
    sessao = criar_sessao()
    assert "Mozilla" in sessao.headers["User-Agent"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_http.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.core.http'`

- [ ] **Step 3: Write minimal implementation**

`radar/core/http.py`:

```python
"""Acesso HTTP com política de retry que distingue falha transitória de permanente."""

from __future__ import annotations

import time

import requests

from radar.core.erros import FonteIndisponivel, SemEdicao
from radar.core.log import configurar_log

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 429 entra aqui porque é limite de taxa, não erro do pedido.
_TRANSITORIOS = {429, 500, 502, 503, 504}
_TIMEOUT = 60


def criar_sessao(user_agent: str | None = None) -> requests.Session:
    sessao = requests.Session()
    sessao.headers["User-Agent"] = user_agent or USER_AGENT
    return sessao


def obter_bytes(
    sessao,
    url: str,
    *,
    tentativas: int = 3,
    espera_base: float = 1.0,
) -> bytes:
    """Busca a URL devolvendo bytes crus.

    Erro transitório (rede, 5xx, 429) é retentado com backoff exponencial.
    Erro permanente (4xx) não é: retentar um 404 nunca o transforma em 200.
    """
    logger = configurar_log()
    ultimo: Exception | None = None

    for tentativa in range(1, tentativas + 1):
        try:
            resposta = sessao.get(url, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            ultimo = exc
            logger.warning("Falha de rede em %s (tentativa %d/%d): %s", url, tentativa, tentativas, exc)
        else:
            codigo = resposta.status_code
            if codigo == 200:
                return resposta.content
            if codigo == 401:
                raise SemEdicao(f"Sem edição disponível em {url} (HTTP 401)")
            if codigo not in _TRANSITORIOS:
                raise FonteIndisponivel(f"HTTP {codigo} em {url} (erro permanente, sem retry)")
            ultimo = FonteIndisponivel(f"HTTP {codigo} em {url}")
            logger.warning("HTTP %d em %s (tentativa %d/%d)", codigo, url, tentativa, tentativas)

        if tentativa < tentativas and espera_base:
            time.sleep(espera_base * (2 ** (tentativa - 1)))

    raise FonteIndisponivel(f"Falhou após {tentativas} tentativas em {url}: {ultimo}")


def obter_texto(
    sessao,
    url: str,
    *,
    encoding: str,
    tentativas: int = 3,
    espera_base: float = 1.0,
) -> str:
    """Busca a URL decodificando com o encoding informado.

    O encoding é sempre explícito porque a busca do DOU declara `charset=UTF-8`
    e serve ISO-8859-1; confiar no header produz mojibake.
    """
    bruto = obter_bytes(sessao, url, tentativas=tentativas, espera_base=espera_base)
    return bruto.decode(encoding)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_http.py -v`
Expected: PASS (9 testes)

- [ ] **Step 5: Commit**

```bash
git add radar/core/http.py tests/test_http.py
git commit -m "feat: HTTP com retry que separa erro transitorio de permanente"
```

---

### Task 6: Armazenamento (raw, JSON normalizado, SQLite com FTS5)

Corrige o bug 11 da spec: hoje rodar o mesmo dia duas vezes duplica dados e reenvia e-mail.

**Files:**
- Create: `radar/core/storage.py`
- Create: `tests/test_storage.py`

**Interfaces:**
- Consumes: `radar.core.modelos.{Publicacao, Resultado}`
- Produces: classe `Storage` com
  - `__init__(self, dir_dados: Path)`
  - `salvar_raw(self, data: date, fonte: str, nome: str, conteudo: bytes) -> Path`
  - `ler_raw(self, data: date, fonte: str, nome: str) -> bytes | None`
  - `salvar_normalizado(self, resultado: Resultado) -> Path`
  - `gravar(self, publicacoes: list[Publicacao]) -> int`
  - `consultar(self, termo: str, desde: date | None = None) -> list[dict]`
  - `fechar(self) -> None`

- [ ] **Step 1: Write the failing test**

`tests/test_storage.py`:

```python
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from radar.core.erros import Status
from radar.core.modelos import Publicacao, Resultado, gerar_id
from radar.core.storage import Storage


def _pub(titulo="Portaria 1", url="https://x/1", texto="teto MAC ampliado") -> Publicacao:
    d = date(2026, 9, 4)
    return Publicacao(
        id=gerar_id("dou", d, url, titulo),
        fonte="dou",
        data_publicacao=d,
        coletado_em=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
        orgao="Ministério da Saúde",
        unidade=None,
        secao="1",
        pagina=None,
        edicao="168",
        tipo="Portaria",
        numero="1",
        titulo=titulo,
        ementa=None,
        texto=texto,
        url=url,
        origem={},
    )


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    s = Storage(tmp_path / "data")
    yield s
    s.fechar()


def test_salva_e_le_bruto(storage: Storage):
    caminho = storage.salvar_raw(date(2026, 9, 4), "dou", "busca-p1.html", b"<html>")
    assert caminho.exists()
    assert storage.ler_raw(date(2026, 9, 4), "dou", "busca-p1.html") == b"<html>"


def test_ler_bruto_inexistente_devolve_none(storage: Storage):
    assert storage.ler_raw(date(2026, 9, 4), "dou", "nao-existe.html") is None


def test_salva_json_normalizado_no_caminho_da_spec(storage: Storage):
    r = Resultado(
        fonte="dou",
        data_publicacao=date(2026, 9, 4),
        coletado_em=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
        status=Status.OK,
        escopo={"orgao": "Ministério da Saúde"},
        publicacoes=[_pub()],
    )
    caminho = storage.salvar_normalizado(r)
    assert caminho.name == "dou.json"
    assert caminho.parent.name == "2026-09-04"
    conteudo = json.loads(caminho.read_text(encoding="utf-8"))
    assert conteudo["total"] == 1
    assert conteudo["status"] == "ok"


def test_gravar_duas_vezes_nao_duplica(storage: Storage):
    """Idempotencia: reexecutar o mesmo dia converge, nao acumula."""
    assert storage.gravar([_pub()]) == 1
    assert storage.gravar([_pub()]) == 1
    assert len(storage.consultar("teto")) == 1


def test_gravar_atualiza_texto_em_reprocessamento(storage: Storage):
    storage.gravar([_pub(texto="texto antigo")])
    storage.gravar([_pub(texto="texto novo e melhor")])
    achados = storage.consultar("melhor")
    assert len(achados) == 1
    assert achados[0]["texto"] == "texto novo e melhor"


def test_consulta_fts_encontra_por_termo(storage: Storage):
    storage.gravar([_pub(titulo="A", url="https://x/a", texto="repasse de custeio")])
    storage.gravar([_pub(titulo="B", url="https://x/b", texto="nomeacao de servidor")])
    assert len(storage.consultar("custeio")) == 1
    assert len(storage.consultar("nomeacao")) == 1


def test_consulta_filtra_por_data_inicial(storage: Storage):
    storage.gravar([_pub()])
    assert storage.consultar("teto", desde=date(2026, 9, 1)) != []
    assert storage.consultar("teto", desde=date(2026, 10, 1)) == []


def test_consulta_sem_resultado_devolve_lista_vazia(storage: Storage):
    assert storage.consultar("inexistente") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_storage.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.core.storage'`

- [ ] **Step 3: Write minimal implementation**

`radar/core/storage.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_storage.py -v`
Expected: PASS (8 testes)

- [ ] **Step 5: Commit**

```bash
git add radar/core/storage.py tests/test_storage.py
git commit -m "feat: storage com raw, JSON normalizado e FTS5 idempotente"
```

---

### Task 7: DOU — parse do jsonArray e encoding da busca

Corrige o bug 4 da spec: a seção deixa de ser adivinhada por palavra no título e passa a vir de `pubName`.

**Files:**
- Create: `radar/fontes/__init__.py`
- Create: `radar/fontes/dou/__init__.py`
- Create: `radar/fontes/dou/busca.py`
- Create: `tests/test_dou_busca.py`

**Interfaces:**
- Consumes: `radar.core.erros.ExtracaoParcial`
- Produces:
  - `BASE_BUSCA: str`, `ID_BLOCO_JSON: str`, `ENCODING_BUSCA: str`, `ENCODING_PUBLICACAO: str`
  - `Cursor` (frozen dataclass): `score`, `id`, `display_date`
  - `decodificar_busca(bruto: bytes) -> str`
  - `extrair_jsonarray(html: str) -> list[dict]`
  - `cursor_do_ultimo(itens: list[dict]) -> Cursor | None`
  - `montar_url_busca(orgao: str, data: date, delta: int, pagina: int = 1, cursor: Cursor | None = None) -> str`
  - `url_publicacao(url_title: str) -> str`
  - `total_de_resultados(html: str) -> int`

**Descobertas de campo que este código encerra** (verificadas contra o site real em 2026-09-04, não suposições):

1. **A data só funciona via `exactDate=personalizado`.** `exactDate=dia` com
   `dateDay`/`dateMonth`/`dateYear` — a forma que os scripts atuais usam —
   **ignora silenciosamente a data pedida** e devolve a edição corrente. Pedir
   `dateDay=03` retornou publicações com `pubDate=04/09/2026`. O formato aceito é
   `publishFrom=DD-MM-AAAA` (ou `DD/MM/AAAA`); em ISO (`2026-09-03`) volta a cair
   em hoje, sem erro.
2. **A paginação é por cursor, não por offset.** `currentPage=2` na URL não avança
   (o Liferay apenas ecoa o valor). A página seguinte exige `currentPage`,
   `newPage` e o cursor `score`/`id`/`displayDate` copiado do **último item da
   página atual**. Validado: 03/09 devolveu 75 + 43 = 118 itens únicos, igual ao
   total informado.

- [ ] **Step 1: Write the failing test**

`tests/test_dou_busca.py`:

```python
from datetime import date
from pathlib import Path

import pytest

from radar.fontes.dou.busca import (
    decodificar_busca,
    extrair_jsonarray,
    montar_url_busca,
    total_de_resultados,
    url_publicacao,
)


@pytest.fixture
def html_busca(dir_fixtures: Path) -> str:
    return decodificar_busca((dir_fixtures / "dou" / "busca-ms-2026-09-03-p1.html").read_bytes())


def test_decodifica_em_utf8_preservando_acentuacao(html_busca: str):
    """Acento intacto e sem mojibake. Regressao critica de encoding."""
    assert "Ministério da Saúde" in html_busca
    # Sinais de ter lido UTF-8 como latin-1:
    assert "Ã©" not in html_busca
    assert "Âº" not in html_busca
    assert "�" not in html_busca


def test_cai_para_latin1_se_os_bytes_nao_forem_utf8_valido():
    """Rede de seguranca caso o portal mude o encoding servido."""
    bruto = "Ministério".encode("iso-8859-1")  # invalido em UTF-8
    assert decodificar_busca(bruto) == "Ministério"


def test_extrai_os_itens_do_bloco_json(html_busca: str):
    itens = extrair_jsonarray(html_busca)
    assert len(itens) == 75


def test_itens_trazem_os_campos_que_substituem_heuristica(html_busca: str):
    item = extrair_jsonarray(html_busca)[0]
    for campo in ("pubName", "artType", "hierarchyStr", "urlTitle", "title", "pubDate"):
        assert campo in item, campo


def test_secao_vem_da_fonte_e_cobre_as_tres(html_busca: str):
    secoes = {i["pubName"] for i in extrair_jsonarray(html_busca)}
    assert secoes <= {"DO1", "DO2", "DO3"}
    assert len(secoes) >= 2


def test_tipos_vem_da_fonte_nao_de_palavra_no_titulo(html_busca: str):
    tipos = {i["artType"] for i in extrair_jsonarray(html_busca)}
    assert "Portaria" in tipos
    assert any("Extrato" in t for t in tipos)


def test_total_de_resultados_e_lido_da_pagina(html_busca: str):
    assert total_de_resultados(html_busca) == 118


def test_todos_os_itens_sao_da_data_pedida(html_busca: str):
    """Regressao do parametro de data ignorado: pedir 03/09 tem que trazer 03/09."""
    assert {i["pubDate"] for i in extrair_jsonarray(html_busca)} == {"03/09/2026"}


def test_html_sem_bloco_json_levanta_erro():
    from radar.core.erros import ExtracaoParcial

    with pytest.raises(ExtracaoParcial):
        extrair_jsonarray("<html><body>nada aqui</body></html>")


def test_url_usa_data_personalizada_e_nunca_exactdate_dia():
    """`exactDate=dia` ignora a data pedida e devolve a edicao corrente."""
    url = montar_url_busca("Ministério da Saúde", date(2026, 9, 3), delta=75)
    assert "exactDate=personalizado" in url
    assert "publishFrom=03-09-2026" in url
    assert "publishTo=03-09-2026" in url
    assert "exactDate=dia" not in url
    assert "dateDay" not in url
    assert "delta=75" in url
    assert "Minist%C3%A9rio+da+Sa%C3%BAde" in url or "Minist%C3%A9rio%20da%20Sa%C3%BAde" in url


def test_primeira_pagina_nao_leva_cursor():
    url = montar_url_busca("MS", date(2026, 9, 3), delta=75)
    assert "newPage" not in url
    assert "score" not in url


def test_cursor_e_extraido_do_ultimo_item(html_busca: str):
    from radar.fontes.dou.busca import cursor_do_ultimo

    itens = extrair_jsonarray(html_busca)
    cursor = cursor_do_ultimo(itens)
    assert cursor.id == itens[-1]["classPK"]
    assert cursor.display_date == itens[-1]["displayDateSortable"]
    assert cursor.score == itens[-1]["score"]


def test_cursor_de_lista_vazia_e_none():
    from radar.fontes.dou.busca import cursor_do_ultimo

    assert cursor_do_ultimo([]) is None


def test_url_da_segunda_pagina_carrega_o_cursor(html_busca: str):
    from radar.fontes.dou.busca import cursor_do_ultimo

    cursor = cursor_do_ultimo(extrair_jsonarray(html_busca))
    url = montar_url_busca("MS", date(2026, 9, 3), delta=75, pagina=2, cursor=cursor)
    assert "currentPage=1" in url
    assert "newPage=2" in url
    assert f"id={cursor.id}" in url
    assert f"displayDate={cursor.display_date}" in url


def test_url_de_publicacao_usa_o_slug():
    assert url_publicacao("portaria-x-123") == "https://www.in.gov.br/web/dou/-/portaria-x-123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dou_busca.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.fontes'`

- [ ] **Step 3: Write minimal implementation**

`radar/fontes/__init__.py`:

```python
"""Adaptadores de fonte. Cada um sabe apenas obter e normalizar."""
```

`radar/fontes/dou/__init__.py`:

```python
"""Diário Oficial da União."""
```

`radar/fontes/dou/busca.py`:

```python
"""Listagem do DOU a partir do JSON embutido na página de busca.

A busca do in.gov.br serve os resultados dentro de um <script
type="application/json">, o que dispensa navegador: basta HTTP e json.loads.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import quote_plus, urlencode

from radar.core.erros import ExtracaoParcial

BASE_BUSCA = "https://www.in.gov.br/consulta/-/buscar/dou"
BASE_PUBLICACAO = "https://www.in.gov.br/web/dou/-/"
ID_BLOCO_JSON = "_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"

# Verificado contra o site: o portal serve UTF-8 e o header diz a verdade.
ENCODING_BUSCA = "utf-8"
ENCODING_PUBLICACAO = "utf-8"

_PADRAO_BLOCO = re.compile(
    rf'<script id="{re.escape(ID_BLOCO_JSON)}" type="application/json">(.*?)</script>',
    re.DOTALL,
)
_PADRAO_TOTAL = re.compile(r"(\d+)\s+resultados?")


def decodificar_busca(bruto: bytes) -> str:
    """Decodifica a página de busca.

    UTF-8 é auto-validante: uma sequência inválida levanta em vez de produzir
    lixo silencioso. Por isso tentamos UTF-8 primeiro e só caímos em ISO-8859-1
    se os bytes não forem UTF-8 válido — o que só aconteceria se o portal
    mudasse. Latin-1 nunca falha, então jamais deve vir primeiro.
    """
    try:
        return bruto.decode(ENCODING_BUSCA)
    except UnicodeDecodeError:
        return bruto.decode("iso-8859-1")


def extrair_jsonarray(html: str) -> list[dict]:
    """Devolve os itens de resultado embutidos na página."""
    achado = _PADRAO_BLOCO.search(html)
    if not achado:
        raise ExtracaoParcial(
            "Bloco JSON de resultados não encontrado na busca do DOU. "
            "A estrutura da página pode ter mudado."
        )
    try:
        dados = json.loads(achado.group(1).strip())
    except json.JSONDecodeError as exc:
        raise ExtracaoParcial(f"Bloco JSON da busca do DOU é inválido: {exc}") from exc
    return dados.get("jsonArray", [])


def total_de_resultados(html: str) -> int:
    """Total informado pela própria busca, usado para saber quando parar."""
    achado = _PADRAO_TOTAL.search(html)
    return int(achado.group(1)) if achado else 0


@dataclass(frozen=True)
class Cursor:
    """Posição da paginação: o último item da página já lida.

    A busca do DOU pagina por cursor (`search_after`), não por offset. Mandar
    `currentPage=2` na URL não avança nada — o portal só ecoa o valor.
    """

    score: Any
    id: Any
    display_date: Any


def cursor_do_ultimo(itens: list[dict]) -> Cursor | None:
    if not itens:
        return None
    ultimo = itens[-1]
    return Cursor(
        score=ultimo.get("score"),
        id=ultimo.get("classPK"),
        display_date=ultimo.get("displayDateSortable"),
    )


def montar_url_busca(
    orgao: str,
    data: date,
    delta: int,
    pagina: int = 1,
    cursor: Cursor | None = None,
) -> str:
    """URL da busca para uma data e página.

    A data vai como `exactDate=personalizado` com `publishFrom`/`publishTo` em
    DD-MM-AAAA. A forma `exactDate=dia` + `dateDay/dateMonth/dateYear`, usada
    pelos scripts antigos, ignora a data pedida e devolve a edição corrente —
    sem erro, o que é pior.
    """
    data_br = data.strftime("%d-%m-%Y")
    parametros = {
        "q": "*",
        "s": "todos",
        "orgPrin": orgao,
        "exactDate": "personalizado",
        "publishFrom": data_br,
        "publishTo": data_br,
        "sortType": "0",
        "delta": delta,
    }
    if pagina > 1 and cursor is not None:
        parametros.update(
            {
                "currentPage": pagina - 1,
                "newPage": pagina,
                "score": cursor.score,
                "id": cursor.id,
                "displayDate": cursor.display_date,
            }
        )
    return f"{BASE_BUSCA}?{urlencode(parametros, quote_via=quote_plus)}"


def url_publicacao(url_title: str) -> str:
    return f"{BASE_PUBLICACAO}{url_title}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dou_busca.py -v`
Expected: PASS (15 testes)

- [ ] **Step 5: Commit**

```bash
git add radar/fontes/__init__.py radar/fontes/dou/ tests/test_dou_busca.py
git commit -m "feat: leitura do jsonArray da busca do DOU com encoding correto"
```

---

### Task 8: DOU — paginação com deduplicação

Corrige os bugs 1, 9 e 12 da spec: hoje `extend()` cego mais `len >= total` declaram "extração completa" sobre uma lista metade duplicada, e `max_pages=10` limita a 750 itens.

**Files:**
- Modify: `radar/fontes/dou/busca.py` (acrescentar `percorrer_paginas`)
- Create: `tests/test_dou_paginacao.py`

**Interfaces:**
- Consumes: `extrair_jsonarray`, `total_de_resultados`, `cursor_do_ultimo`, `Cursor` da Task 7
- Produces: `percorrer_paginas(buscar_pagina: Callable[[int, Cursor | None], str], delta: int) -> tuple[list[dict], list[str]]` — devolve itens únicos (por `urlTitle`) e a lista de avisos. O chamador injeta `buscar_pagina`, que recebe o número da página e o cursor da anterior e devolve o HTML já decodificado.

- [ ] **Step 1: Write the failing test**

`tests/test_dou_paginacao.py`:

```python
import json
from pathlib import Path

from radar.fontes.dou.busca import ID_BLOCO_JSON, decodificar_busca, percorrer_paginas


def _pagina(itens: list[dict], total: int) -> str:
    bloco = json.dumps({"jsonArray": itens})
    return (
        f"<html><p>{total} resultados</p>"
        f'<script id="{ID_BLOCO_JSON}" type="application/json">{bloco}</script>'
        f"</html>"
    )


def _itens(inicio: int, quantos: int) -> list[dict]:
    return [
        {"urlTitle": f"ato-{i}", "title": f"Ato {i}", "classPK": str(i),
         "score": 0, "displayDateSortable": 1788490800000}
        for i in range(inicio, inicio + quantos)
    ]


def test_percorre_todas_as_paginas_ate_o_total():
    paginas = {1: _pagina(_itens(0, 3), 5), 2: _pagina(_itens(3, 2), 5)}
    itens, avisos = percorrer_paginas(lambda n, c: paginas[n], delta=3)
    assert len(itens) == 5
    assert avisos == []


def test_cursor_da_pagina_anterior_e_repassado():
    """Sem o cursor a busca do DOU nunca avanca de pagina."""
    recebidos: list = []

    def buscar(n, cursor):
        recebidos.append(cursor)
        return _pagina(_itens((n - 1) * 3, 3), 6)

    percorrer_paginas(buscar, delta=3)
    assert recebidos[0] is None, "a primeira página não tem cursor"
    assert recebidos[1] is not None
    assert recebidos[1].id == "2", "cursor deve vir do último item da página 1"


def test_deduplica_por_url_title():
    """Item repetido na borda de duas paginas conta uma vez so."""
    paginas = {1: _pagina(_itens(0, 3), 4), 2: _pagina(_itens(2, 2), 4)}
    itens, _ = percorrer_paginas(lambda n, c: paginas[n], delta=3)
    assert len(itens) == 4
    assert len({i["urlTitle"] for i in itens}) == 4


def test_para_por_unicos_e_nao_por_posicao_bruta():
    """Regressao: contar posicao bruta em vez de unicos descarta item real.

    Paginas 1 e 2 se sobrepoem no item 2. Somando posicoes, 3+3 ja atinge o
    total 5 e o corte por posicao jogaria fora o item 4.
    """
    paginas = {1: _pagina(_itens(0, 3), 5), 2: _pagina(_itens(2, 3), 5)}
    itens, avisos = percorrer_paginas(lambda n, c: paginas[n], delta=3)
    assert len({i["urlTitle"] for i in itens}) == 5
    assert avisos == []


def test_pagina_repetida_interrompe_e_avisa_em_vez_de_mentir_sucesso():
    """O bug atual: pagina que nao avanca inflava o contador ate 'completo'."""
    repetida = _pagina(_itens(0, 3), 9)
    itens, avisos = percorrer_paginas(lambda n, c: repetida, delta=3)
    assert len(itens) == 3
    assert avisos, "paginação travada precisa gerar aviso"
    assert "repet" in avisos[0].lower() or "trav" in avisos[0].lower()


def test_avisa_quando_coletou_menos_que_o_total():
    paginas = {1: _pagina(_itens(0, 3), 10), 2: _pagina([], 10)}
    itens, avisos = percorrer_paginas(lambda n, c: paginas[n], delta=3)
    assert len(itens) == 3
    assert any("10" in a for a in avisos)


def test_pagina_vazia_encerra_sem_erro():
    paginas = {1: _pagina(_itens(0, 2), 2), 2: _pagina([], 2)}
    itens, avisos = percorrer_paginas(lambda n, c: paginas[n], delta=2)
    assert len(itens) == 2
    assert avisos == []


def test_sem_resultados_devolve_lista_vazia():
    itens, avisos = percorrer_paginas(lambda n, c: _pagina([], 0), delta=75)
    assert itens == []
    assert avisos == []


def test_teto_de_paginas_deriva_do_total_nao_de_constante():
    """Com 800 resultados e delta 75 sao 11 paginas; o limite antigo travava em 10."""
    chamadas: list[int] = []

    def buscar(n, cursor):
        chamadas.append(n)
        inicio = (n - 1) * 75
        return _pagina(_itens(inicio, min(75, 800 - inicio)), 800)

    itens, _ = percorrer_paginas(buscar, delta=75)
    assert len(itens) == 800
    assert max(chamadas) >= 11


def test_edicao_real_percorre_as_duas_paginas(dir_fixtures: Path):
    """Fixtures reais de 03/09/2026: 75 + 43 = 118, o total informado pela busca."""
    paginas = {
        1: decodificar_busca((dir_fixtures / "dou" / "busca-ms-2026-09-03-p1.html").read_bytes()),
        2: decodificar_busca((dir_fixtures / "dou" / "busca-ms-2026-09-03-p2.html").read_bytes()),
    }
    itens, avisos = percorrer_paginas(lambda n, c: paginas[n], delta=75)
    assert len(itens) == 118
    assert avisos == []
    assert len({i["urlTitle"] for i in itens}) == 118, "não pode haver duplicata"
    assert {i["pubName"] for i in itens} == {"DO1", "DO2", "DO3"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dou_paginacao.py -v`
Expected: FAIL com `ImportError: cannot import name 'percorrer_paginas'`

- [ ] **Step 3: Write minimal implementation**

Acrescentar ao fim de `radar/fontes/dou/busca.py`:

```python
def percorrer_paginas(buscar_pagina, delta: int) -> tuple[list[dict], list[str]]:
    """Percorre a paginação da busca acumulando itens únicos.

    `buscar_pagina(numero, cursor) -> html` é injetado para manter esta função
    testável sem rede. O cursor vem do último item da página anterior; sem ele a
    busca do DOU devolve sempre a primeira página.

    Três saídas explícitas, nunca um `except` pelado: total atingido, página
    vazia, ou página cujo conjunto de itens repete o da anterior — que é como a
    paginação trava. Nesse último caso devolve aviso em vez de declarar sucesso.
    """
    from radar.core.log import configurar_log

    logger = configurar_log()
    unicos: dict[str, dict] = {}
    avisos: list[str] = []
    total = 0
    vistos_anteriores: set[str] | None = None
    cursor: Cursor | None = None
    pagina = 1
    teto = 1

    while pagina <= teto:
        html = buscar_pagina(pagina, cursor)
        if pagina == 1:
            total = total_de_resultados(html)
            if total == 0:
                return [], []
            # Uma página de margem para o caso de o total oscilar durante a coleta.
            teto = -(-total // delta) + 1

        itens = extrair_jsonarray(html)
        if not itens:
            break

        chaves = {i.get("urlTitle", "") for i in itens}
        if vistos_anteriores is not None and chaves == vistos_anteriores:
            avisos.append(
                f"Paginação travou: a página {pagina} repetiu os itens da anterior. "
                f"Coletados {len(unicos)} de {total}."
            )
            logger.warning(avisos[-1])
            break
        vistos_anteriores = chaves

        for item in itens:
            chave = item.get("urlTitle", "")
            if chave:
                unicos[chave] = item

        if len(unicos) >= total:
            break
        cursor = cursor_do_ultimo(itens)
        pagina += 1

    if total and len(unicos) < total and not avisos:
        avisos.append(f"Coletadas {len(unicos)} de {total} publicações informadas pela busca.")
        logger.warning(avisos[-1])

    return list(unicos.values()), avisos
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dou_paginacao.py -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Commit**

```bash
git add radar/fontes/dou/busca.py tests/test_dou_paginacao.py
git commit -m "fix: paginacao do DOU deduplica e detecta travamento"
```

---

### Task 9: DOU — extração do texto integral

**Files:**
- Create: `radar/fontes/dou/texto.py`
- Create: `tests/test_dou_texto.py`

**Interfaces:**
- Consumes: nada das tasks anteriores
- Produces:
  - `TextoDOU` (frozen dataclass): `identifica: str | None`, `ementa: str | None`, `texto: str`
  - `extrair_texto(html: str) -> TextoDOU`

- [ ] **Step 1: Write the failing test**

`tests/test_dou_texto.py`:

```python
from pathlib import Path

import pytest

from radar.fontes.dou.texto import TextoDOU, extrair_texto


@pytest.fixture
def html_pub(dir_fixtures: Path) -> str:
    return (dir_fixtures / "dou" / "pub-portaria-gm-ms-12141.html").read_bytes().decode("utf-8")


def test_extrai_identifica(html_pub: str):
    assert "12.141" in extrair_texto(html_pub).identifica


def test_extrai_ementa(html_pub: str):
    ementa = extrair_texto(html_pub).ementa
    assert "SAMU 192" in ementa


def test_texto_integral_e_muito_maior_que_o_snippet_da_listagem(html_pub: str):
    """A listagem trunca em ~420 chars; e por isso que existe o estagio 2."""
    assert len(extrair_texto(html_pub).texto) > 1500


def test_texto_preserva_valor_monetario(html_pub: str):
    """O dado que sustenta o juizo de captacao no agente."""
    assert "274.372,80" in extrair_texto(html_pub).texto


def test_texto_contem_o_articulado(html_pub: str):
    texto = extrair_texto(html_pub).texto
    assert "Art. 1" in texto
    assert "Art. 2" in texto


def test_texto_nao_contem_tags_html(html_pub: str):
    texto = extrair_texto(html_pub).texto
    assert "<" not in texto
    assert "&nbsp;" not in texto


def test_html_sem_corpo_devolve_texto_vazio_sem_estourar():
    resultado = extrair_texto("<html><body><p>nada</p></body></html>")
    assert isinstance(resultado, TextoDOU)
    assert resultado.texto == ""
    assert resultado.identifica is None
    assert resultado.ementa is None


def test_corta_no_rodape_e_ignora_o_que_vem_depois():
    """O ato termina no rodape; paragrafo de mobiliario nao e inteiro teor."""
    html = (
        '<html><div class="texto-dou">'
        '<p class="identifica">Portaria X</p>'
        '<p class="dou-paragraph">Conteudo do ato.</p>'
        "</div>"
        '<div class="informacao-conteudo-dou">'
        '<p class="h6">Este conteudo nao substitui o publicado no DOU.</p>'
        "</div></html>"
    )
    texto = extrair_texto(html).texto
    assert "Conteudo do ato." in texto
    assert "nao substitui" not in texto


def test_sem_rodape_ainda_extrai_ate_o_fim():
    """Fallback: se a pagina nao tiver rodape, nao pode devolver vazio."""
    html = (
        '<html><div class="texto-dou">'
        '<p class="identifica">Portaria Y</p>'
        '<p class="dou-paragraph">Unico paragrafo.</p>'
        "</div></html>"
    )
    assert "Unico paragrafo." in extrair_texto(html).texto
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dou_texto.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.fontes.dou.texto'`

- [ ] **Step 3: Write minimal implementation**

`radar/fontes/dou/texto.py`:

```python
"""Inteiro teor de uma publicação do DOU.

O corpo vive em `div.texto-dou`, com parágrafos já classificados pelo portal:
`identifica` (título), `ementa`, `dou-paragraph` (articulado), `assina`, `anexo`.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass

_CORPO = re.compile(r'<div[^>]*class="[^"]*\btexto-dou\b[^"]*"[^>]*>(.*)', re.DOTALL)
# O ato acaba no rodape. Sem esse corte, paragrafos de mobiliario da pagina
# (classe `h6`, avisos de "nao substitui o publicado") entram no inteiro teor.
_FIM_DO_ATO = re.compile(
    r'<div[^>]*class="[^"]*\b(?:informacao-conteudo-dou|rodape-dou)\b', re.DOTALL
)
_PARAGRAFO = re.compile(r'<p class="([^"]+)"[^>]*>(.*?)</p>', re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_ESPACOS = re.compile(r"\s+")

# `d-none` e `audience-title` são elementos de interface, não conteúdo do ato.
_CLASSES_IGNORADAS = {"d-none", "audience-title"}


@dataclass(frozen=True)
class TextoDOU:
    identifica: str | None
    ementa: str | None
    texto: str


def _limpar(trecho: str) -> str:
    return _ESPACOS.sub(" ", _html.unescape(_TAG.sub(" ", trecho))).strip()


def extrair_texto(html: str) -> TextoDOU:
    """Extrai título, ementa e inteiro teor da página de uma publicação."""
    corpo = _CORPO.search(html)
    if not corpo:
        return TextoDOU(identifica=None, ementa=None, texto="")

    # Corta no rodape quando ele existe; senao vai ate o fim do documento.
    regiao = corpo.group(1)
    rodape = _FIM_DO_ATO.search(regiao)
    if rodape:
        regiao = regiao[: rodape.start()]

    identifica: str | None = None
    ementa: str | None = None
    linhas: list[str] = []

    for classes, conteudo in _PARAGRAFO.finditer(regiao):
        nomes = set(classes.split())
        if nomes & _CLASSES_IGNORADAS:
            continue
        limpo = _limpar(conteudo)
        if not limpo:
            continue
        if "identifica" in nomes and identifica is None:
            identifica = limpo
        elif "ementa" in nomes and ementa is None:
            ementa = limpo
        linhas.append(limpo)

    return TextoDOU(identifica=identifica, ementa=ementa, texto="\n".join(linhas))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dou_texto.py -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Commit**

```bash
git add radar/fontes/dou/texto.py tests/test_dou_texto.py
git commit -m "feat: extracao do inteiro teor de publicacao do DOU"
```

---

### Task 10: DOU — normalização para Publicacao

**Files:**
- Create: `radar/fontes/dou/normaliza.py`
- Create: `tests/test_dou_normaliza.py`

**Interfaces:**
- Consumes: `Publicacao`, `gerar_id` (Task 2); `TextoDOU` (Task 9); `url_publicacao` (Task 7)
- Produces: `normalizar(item: dict, texto: TextoDOU | None, data_publicacao: date, coletado_em: datetime) -> Publicacao`

- [ ] **Step 1: Write the failing test**

`tests/test_dou_normaliza.py`:

```python
from datetime import date, datetime, timezone

from radar.fontes.dou.normaliza import normalizar
from radar.fontes.dou.texto import TextoDOU

QUANDO = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
DIA = date(2026, 9, 4)

ITEM = {
    "pubName": "DO1",
    "artType": "Portaria",
    "hierarchyStr": "Ministério da Saúde/Gabinete do Ministro",
    "urlTitle": "portaria-gm/ms-n-12.141-de-3-de-setembro-de-2026-730143120",
    "title": "Portaria GM/MS Nº 12.141, DE 3 DE setembro DE 2026",
    "content": "Portaria GM/MS Nº 12.141 ... truncado ...",
    "editionNumber": "168",
    "numberPage": "184",
    "pubDate": "04/09/2026",
    "classPK": "730143120",
}


def test_secao_vem_de_pubname():
    assert normalizar(ITEM, None, DIA, QUANDO).secao == "1"
    assert normalizar({**ITEM, "pubName": "DO3"}, None, DIA, QUANDO).secao == "3"


def test_pubname_desconhecido_vira_none_em_vez_de_chute():
    assert normalizar({**ITEM, "pubName": "XX"}, None, DIA, QUANDO).secao is None


def test_tipo_vem_de_arttype():
    assert normalizar(ITEM, None, DIA, QUANDO).tipo == "Portaria"


def test_orgao_e_unidade_saem_da_hierarquia():
    pub = normalizar(ITEM, None, DIA, QUANDO)
    assert pub.orgao == "Ministério da Saúde"
    assert pub.unidade == "Gabinete do Ministro"


def test_hierarquia_sem_barra_deixa_unidade_none():
    pub = normalizar({**ITEM, "hierarchyStr": "Ministério da Saúde"}, None, DIA, QUANDO)
    assert pub.orgao == "Ministério da Saúde"
    assert pub.unidade is None


def test_numero_e_extraido_do_titulo():
    assert normalizar(ITEM, None, DIA, QUANDO).numero == "12.141"


def test_numero_ausente_vira_none_nao_placeholder():
    pub = normalizar({**ITEM, "title": "Aviso de licitação"}, None, DIA, QUANDO)
    assert pub.numero is None


def test_numero_nao_e_inventado_a_partir_de_no_seguido_de_ano():
    """Regressao: 'Plano 2026' contem 'no 2026' e nao pode virar numero do ato."""
    for titulo in (
        "Divulga o Plano 2026 de metas",
        "Concede abono 2026 aos servidores",
        "Extrato do Convênio - Governo 2026",
    ):
        assert normalizar({**ITEM, "title": titulo}, None, DIA, QUANDO).numero is None


def test_pagina_nao_numerica_vira_none_sem_estourar():
    assert normalizar({**ITEM, "numberPage": "184-185"}, None, DIA, QUANDO).pagina is None
    assert normalizar({**ITEM, "numberPage": None}, None, DIA, QUANDO).pagina is None


def test_hierarquia_ausente_nao_estoura():
    item = {k: v for k, v in ITEM.items() if k != "hierarchyStr"}
    pub = normalizar(item, None, DIA, QUANDO)
    assert pub.unidade is None


def test_usa_texto_integral_quando_disponivel():
    texto = TextoDOU(identifica="Portaria GM/MS Nº 12.141", ementa="Renova.", texto="Art. 1º Fica renovada.")
    pub = normalizar(ITEM, texto, DIA, QUANDO)
    assert pub.texto == "Art. 1º Fica renovada."
    assert pub.ementa == "Renova."


def test_sem_texto_integral_cai_para_o_content_da_listagem():
    pub = normalizar(ITEM, None, DIA, QUANDO)
    assert pub.texto == ITEM["content"]


def test_url_e_canonica():
    assert normalizar(ITEM, None, DIA, QUANDO).url.startswith("https://www.in.gov.br/web/dou/-/")


def test_pagina_e_inteiro_e_edicao_e_texto():
    pub = normalizar(ITEM, None, DIA, QUANDO)
    assert pub.pagina == 184
    assert pub.edicao == "168"


def test_origem_registra_a_procedencia():
    origem = normalizar(ITEM, None, DIA, QUANDO).origem
    assert origem["classPK"] == "730143120"
    assert origem["metodo"] == "in.gov.br/consulta"


def test_nao_ha_campo_de_juizo():
    pub = normalizar(ITEM, None, DIA, QUANDO)
    for proibido in ("score", "is_sus", "impacto", "relevancia"):
        assert not hasattr(pub, proibido)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dou_normaliza.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.fontes.dou.normaliza'`

- [ ] **Step 3: Write minimal implementation**

`radar/fontes/dou/normaliza.py`:

```python
"""Converte um item da busca do DOU em `Publicacao`."""

from __future__ import annotations

import re
from datetime import date, datetime

from radar.core.modelos import Publicacao, gerar_id
from radar.fontes.dou.busca import url_publicacao
from radar.fontes.dou.texto import TextoDOU

# `pubName` é a seção real do diário, informada pela fonte.
_SECAO_POR_PUBNAME = {"DO1": "1", "DO2": "2", "DO3": "3"}
# Exige o simbolo ordinal de verdade. Incluir "o" na classe faria a palavra
# "no" casar sob IGNORECASE, e "Plano 2026" viraria numero de ato 2026 —
# invencao de dado, que e exatamente o que este pacote nao pode fazer.
# Medido sobre os 118 titulos reais das fixtures: a forma estrita extrai os
# mesmos 62 numeros que a frouxa, sem perder nada.
_PADRAO_NUMERO = re.compile(r"\bN[º°]\s*([\d][\d.\-/]*)", re.IGNORECASE)


def _numero(titulo: str) -> str | None:
    achado = _PADRAO_NUMERO.search(titulo)
    return achado.group(1).rstrip(".,") if achado else None


def _inteiro(valor) -> int | None:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def normalizar(
    item: dict,
    texto: TextoDOU | None,
    data_publicacao: date,
    coletado_em: datetime,
) -> Publicacao:
    """Normaliza sem inferir: o que a fonte não informa vira `None`."""
    titulo = (item.get("title") or "").strip()
    url = url_publicacao(item.get("urlTitle", ""))

    hierarquia = (item.get("hierarchyStr") or "").split("/")
    orgao = hierarquia[0].strip() if hierarquia and hierarquia[0].strip() else ""
    unidade = hierarquia[1].strip() if len(hierarquia) > 1 and hierarquia[1].strip() else None

    if texto is not None and texto.texto:
        corpo = texto.texto
        ementa = texto.ementa
    else:
        corpo = item.get("content", "") or ""
        ementa = None

    return Publicacao(
        id=gerar_id("dou", data_publicacao, url, titulo),
        fonte="dou",
        data_publicacao=data_publicacao,
        coletado_em=coletado_em,
        orgao=orgao,
        unidade=unidade,
        secao=_SECAO_POR_PUBNAME.get(item.get("pubName", "")),
        pagina=_inteiro(item.get("numberPage")),
        edicao=str(item["editionNumber"]) if item.get("editionNumber") else None,
        tipo=item.get("artType") or None,
        numero=_numero(titulo),
        titulo=titulo,
        ementa=ementa,
        texto=corpo,
        url=url,
        origem={"metodo": "in.gov.br/consulta", "classPK": item.get("classPK")},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dou_normaliza.py -v`
Expected: PASS (16 testes)

- [ ] **Step 5: Commit**

```bash
git add radar/fontes/dou/normaliza.py tests/test_dou_normaliza.py
git commit -m "feat: normalizacao do DOU sem inferencia por palavra-chave"
```

---

### Task 11: DOU — coletor completo

Ao fim desta task a coleta do DOU funciona ponta a ponta.

**Files:**
- Create: `radar/fontes/dou/coletor.py`
- Create: `tests/test_dou_coletor.py`

**Interfaces:**
- Consumes: tudo das Tasks 5–10
- Produces: `FonteDOU` com `nome = "dou"`, `__init__(self, cfg: ConfigDOU, storage: Storage, sessao)` e `coletar(self, data: date, forcar: bool = False) -> Resultado`

- [ ] **Step 1: Write the failing test**

`tests/test_dou_coletor.py`:

```python
import json
from datetime import date
from pathlib import Path

import pytest
import requests

from radar.core.config import ConfigDOU
from radar.core.erros import FonteIndisponivel, Status
from radar.core.storage import Storage
from radar.fontes.dou.busca import ID_BLOCO_JSON
from radar.fontes.dou.coletor import FonteDOU


def _html_busca(itens: list[dict], total: int) -> bytes:
    bloco = json.dumps({"jsonArray": itens})
    return (
        f"<html><p>{total} resultados</p>"
        f'<script id="{ID_BLOCO_JSON}" type="application/json">{bloco}</script></html>'
    ).encode("iso-8859-1")


ITEM = {
    "pubName": "DO1",
    "artType": "Portaria",
    "hierarchyStr": "Ministério da Saúde/Gabinete do Ministro",
    "urlTitle": "portaria-1",
    "title": "Portaria GM/MS Nº 1, DE 3 DE setembro DE 2026",
    "content": "resumo truncado ...",
    "editionNumber": "168",
    "numberPage": "10",
    "classPK": "1",
}

HTML_PUB = (
    '<html><div class="texto-dou">'
    '<p class="identifica">Portaria GM/MS Nº 1</p>'
    '<p class="ementa">Faz algo relevante.</p>'
    '<p class="dou-paragraph">Art. 1º Fica estabelecido o repasse de R$ 100.000,00.</p>'
    "</div></html>"
).encode("utf-8")


class SessaoFalsa:
    def __init__(self, por_url: dict, falhar: set[str] | None = None):
        self.por_url = por_url
        self.falhar = falhar or set()
        self.pedidos: list[str] = []

    def get(self, url, timeout=None):
        self.pedidos.append(url)
        if any(f in url for f in self.falhar):
            # requests.exceptions.ConnectionError, não a builtin: só a primeira é
            # RequestException, que é o que `obter_bytes` converte em FonteIndisponivel.
            raise requests.exceptions.ConnectionError("rede caiu")

        class R:
            status_code = 200
            content = b""

        r = R()
        for chave, corpo in self.por_url.items():
            if chave in url:
                r.content = corpo
                return r
        r.status_code = 404
        return r


@pytest.fixture
def storage(tmp_path: Path):
    s = Storage(tmp_path / "data")
    yield s
    s.fechar()


@pytest.fixture
def cfg() -> ConfigDOU:
    return ConfigDOU(orgao="Ministério da Saúde", delta=75, concorrencia=2)


def test_coleta_completa_com_texto_integral(cfg, storage):
    sessao = SessaoFalsa({"buscar/dou": _html_busca([ITEM], 1), "portaria-1": HTML_PUB})
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))
    assert resultado.status == Status.OK
    assert len(resultado.publicacoes) == 1
    assert "100.000,00" in resultado.publicacoes[0].texto
    assert resultado.avisos == []


def test_dia_sem_publicacoes_e_vazio_nao_erro(cfg, storage):
    sessao = SessaoFalsa({"buscar/dou": _html_busca([], 0)})
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 6))
    assert resultado.status == Status.VAZIO
    assert resultado.publicacoes == []


def test_falha_no_texto_integral_vira_parcial_nao_erro(cfg, storage):
    sessao = SessaoFalsa({"buscar/dou": _html_busca([ITEM], 1)}, falhar={"portaria-1"})
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))
    assert resultado.status == Status.PARCIAL
    assert len(resultado.publicacoes) == 1
    assert resultado.avisos


def test_falha_na_listagem_propaga_como_indisponivel(cfg, storage):
    sessao = SessaoFalsa({}, falhar={"buscar/dou"})
    with pytest.raises(FonteIndisponivel):
        FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))


def test_salva_bruto_e_reusa_no_reprocessamento(cfg, storage):
    sessao = SessaoFalsa({"buscar/dou": _html_busca([ITEM], 1), "portaria-1": HTML_PUB})
    fonte = FonteDOU(cfg, storage, sessao)
    fonte.coletar(date(2026, 9, 4))
    pedidos_primeira = len(sessao.pedidos)
    fonte.coletar(date(2026, 9, 4))
    assert len(sessao.pedidos) == pedidos_primeira, "deveria reusar o cache raw"


def test_forcar_ignora_o_cache(cfg, storage):
    sessao = SessaoFalsa({"buscar/dou": _html_busca([ITEM], 1), "portaria-1": HTML_PUB})
    fonte = FonteDOU(cfg, storage, sessao)
    fonte.coletar(date(2026, 9, 4))
    pedidos = len(sessao.pedidos)
    fonte.coletar(date(2026, 9, 4), forcar=True)
    assert len(sessao.pedidos) > pedidos


def test_escopo_registra_o_orgao(cfg, storage):
    sessao = SessaoFalsa({"buscar/dou": _html_busca([ITEM], 1), "portaria-1": HTML_PUB})
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))
    assert resultado.escopo["orgao"] == "Ministério da Saúde"


def test_texto_vazio_da_pagina_vira_parcial_com_aviso(cfg, storage):
    """Estrutura da pagina mudada devolve vazio sem estourar.

    Isso nao pode passar por coleta completa: o agente consumidor leria o
    resumo truncado achando que e o inteiro teor.
    """
    sessao = SessaoFalsa({
        "buscar/dou": _html_busca([ITEM], 1),
        "portaria-1": b"<html><body>estrutura mudou, sem texto-dou</body></html>",
    })
    resultado = FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4))
    assert resultado.status == Status.PARCIAL
    assert any("vazio" in a.lower() for a in resultado.avisos)


def test_escopo_registra_se_o_texto_integral_foi_buscado(cfg, storage):
    """So lendo o JSON o consumidor precisa saber se `texto` e inteiro teor."""
    sessao = SessaoFalsa({"buscar/dou": _html_busca([ITEM], 1), "portaria-1": HTML_PUB})
    assert FonteDOU(cfg, storage, sessao).coletar(date(2026, 9, 4)).escopo["texto_integral"] is True

    cfg_resumo = ConfigDOU(
        orgao=cfg.orgao, delta=cfg.delta, concorrencia=cfg.concorrencia,
        baixar_texto_integral=False,
    )
    resultado = FonteDOU(cfg_resumo, storage, sessao).coletar(date(2026, 9, 5))
    assert resultado.escopo["texto_integral"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dou_coletor.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.fontes.dou.coletor'`

- [ ] **Step 3: Write minimal implementation**

`radar/fontes/dou/coletor.py`:

```python
"""Coleta do DOU: listagem via JSON embutido, depois inteiro teor de cada ato."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date

from radar.core.config import ConfigDOU
from radar.core.datas import agora_utc
from radar.core.erros import ErroRadar, Status
from radar.core.http import obter_bytes
from radar.core.log import configurar_log
from radar.core.modelos import Resultado
from radar.core.storage import Storage
from radar.fontes.dou import busca, normaliza
from radar.fontes.dou.texto import TextoDOU, extrair_texto


class FonteDOU:
    nome = "dou"

    def __init__(self, cfg: ConfigDOU, storage: Storage, sessao) -> None:
        self.cfg = cfg
        self.storage = storage
        self.sessao = sessao
        self.logger = configurar_log()

    def _buscar_bruto(self, data: date, nome: str, url: str, forcar: bool) -> bytes:
        """Busca com cache em disco, para reprocessar sem repetir requisição."""
        if not forcar:
            guardado = self.storage.ler_raw(data, self.nome, nome)
            if guardado is not None:
                return guardado
        conteudo = obter_bytes(self.sessao, url)
        self.storage.salvar_raw(data, self.nome, nome, conteudo)
        return conteudo

    def coletar(self, data: date, forcar: bool = False) -> Resultado:
        quando = agora_utc()
        escopo = {
            "orgao": self.cfg.orgao,
            # O consumidor precisa saber, so lendo o JSON, se `texto` e o
            # inteiro teor ou o resumo truncado da listagem.
            "texto_integral": self.cfg.baixar_texto_integral,
        }

        def pagina(numero: int, cursor) -> str:
            url = busca.montar_url_busca(self.cfg.orgao, data, self.cfg.delta, numero, cursor)
            bruto = self._buscar_bruto(data, f"busca-p{numero}.html", url, forcar)
            return busca.decodificar_busca(bruto)

        itens, avisos = busca.percorrer_paginas(pagina, self.cfg.delta)

        if not itens:
            self.logger.info("DOU %s: nenhuma publicação para %s", data, self.cfg.orgao)
            return Resultado(
                fonte=self.nome, data_publicacao=data, coletado_em=quando,
                status=Status.VAZIO, escopo=escopo, publicacoes=[], avisos=avisos,
            )

        textos: dict[str, TextoDOU | None] = {}
        if self.cfg.baixar_texto_integral:
            textos, falhas = self._baixar_textos(itens, data, forcar)
            avisos.extend(falhas)

        publicacoes = [
            normaliza.normalizar(item, textos.get(item.get("urlTitle", "")), data, quando)
            for item in itens
        ]

        status = Status.PARCIAL if avisos else Status.OK
        self.logger.info("DOU %s: %d publicações (%s)", data, len(publicacoes), status)
        return Resultado(
            fonte=self.nome, data_publicacao=data, coletado_em=quando,
            status=status, escopo=escopo, publicacoes=publicacoes, avisos=avisos,
        )

    def _baixar_textos(
        self, itens: list[dict], data: date, forcar: bool
    ) -> tuple[dict[str, TextoDOU | None], list[str]]:
        """Baixa o inteiro teor de cada publicação, em paralelo e tolerando falha.

        Uma falha isolada degrada para `parcial`; não derruba o dia inteiro.
        """
        textos: dict[str, TextoDOU | None] = {}
        falhas: list[str] = []

        def um(item: dict) -> tuple[str, TextoDOU | None, str | None]:
            slug = item.get("urlTitle", "")
            try:
                bruto = self._buscar_bruto(
                    data, f"pub-{item.get('classPK', slug)}.html",
                    busca.url_publicacao(slug), forcar,
                )
                extraido = extrair_texto(bruto.decode(busca.ENCODING_PUBLICACAO))
            except (ErroRadar, OSError, UnicodeDecodeError) as exc:
                return slug, None, f"Texto integral indisponível para {slug}: {exc}"

            # Extração vazia não levanta exceção: é o que acontece se o portal
            # mudar a estrutura da página. Sem tratar como falha, a coleta
            # inteira degradaria para o resumo truncado ainda dizendo "ok".
            if not extraido.texto.strip():
                return slug, None, (
                    f"Texto integral vazio para {slug}: a estrutura da página "
                    "pode ter mudado."
                )
            return slug, extraido, None

        with ThreadPoolExecutor(max_workers=max(1, self.cfg.concorrencia)) as executor:
            for slug, texto, falha in executor.map(um, itens):
                textos[slug] = texto
                if falha:
                    falhas.append(falha)

        if falhas:
            self.logger.warning("DOU %s: %d textos integrais não obtidos", data, len(falhas))
        return textos, falhas
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dou_coletor.py -v`
Expected: PASS (9 testes)

- [ ] **Step 5: Commit**

```bash
git add radar/fontes/dou/coletor.py tests/test_dou_coletor.py
git commit -m "feat: coletor do DOU ponta a ponta com cache e degradacao parcial"
```

---

### Task 12: IOF-MG — API e desembrulho do PKCS#7

**Files:**
- Create: `radar/fontes/iofmg/__init__.py`
- Create: `radar/fontes/iofmg/api.py`
- Create: `radar/fontes/iofmg/pkcs7.py`
- Create: `tests/test_iofmg_api.py`

**Interfaces:**
- Consumes: `obter_bytes` (Task 5), `SemEdicao`/`FonteIndisponivel` (Task 2)
- Produces:
  - `URL_API: str`, `montar_url(data: date) -> str`
  - `consultar_edicao(sessao, data: date) -> dict` (o objeto `dados`)
  - `caderno_principal(dados: dict, descricao: str) -> dict`
  - `extrair_base64(dados: dict) -> str`
  - `desembrulhar(bruto: bytes) -> bytes`

- [ ] **Step 1: Write the failing test**

`tests/test_iofmg_api.py`:

```python
import gzip
import json
from datetime import date
from pathlib import Path

import pytest

from radar.core.erros import SemEdicao
from radar.fontes.iofmg.api import caderno_principal, consultar_edicao, montar_url
from radar.fontes.iofmg.pkcs7 import desembrulhar


@pytest.fixture
def dados_03(dir_fixtures: Path) -> dict:
    bruto = json.loads((dir_fixtures / "iofmg" / "edicao-2026-09-03.meta.json").read_text("utf-8"))
    return bruto["dados"]


@pytest.fixture
def envelope(dir_fixtures: Path) -> bytes:
    return gzip.decompress((dir_fixtures / "iofmg" / "envelope-pkcs7-2026-09-03.bin.gz").read_bytes())


def test_monta_url_com_a_data():
    assert "dataPublicacao=2026-09-04" in montar_url(date(2026, 9, 4))


def test_caderno_principal_e_o_diario_do_executivo(dados_03):
    caderno = caderno_principal(dados_03, "Diário do Executivo")
    assert caderno["descricao"] == "Diário do Executivo"


def test_id_do_caderno_vem_da_resposta_nao_de_constante(dados_03, dir_fixtures: Path):
    """Regressao do bug 3: hoje 326074 esta fixo e erra em toda data."""
    id_03 = caderno_principal(dados_03, "Diário do Executivo")["id"]
    dados_02 = json.loads(
        (dir_fixtures / "iofmg" / "edicao-2026-09-02.meta.json").read_text("utf-8")
    )["dados"]
    id_02 = caderno_principal(dados_02, "Diário do Executivo")["id"]
    assert id_03 == 330896
    assert id_02 == 330892
    assert id_03 != id_02, "o id muda por edição; não pode ser constante"
    assert 326074 not in (id_03, id_02)


def test_caderno_inexistente_levanta_sem_edicao(dados_03):
    with pytest.raises(SemEdicao):
        caderno_principal(dados_03, "Caderno Que Não Existe")


def test_desembrulha_envelope_pkcs7_em_ber_indefinido(envelope):
    """O payload usa BER de comprimento indefinido (30 80), nao DER estrito."""
    assert envelope[:1] == b"\x30"
    pdf = desembrulhar(envelope)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1_000_000


def test_desembrulhar_aceita_pdf_cru_sem_envelope():
    """Robustez: se a API parar de assinar, seguimos funcionando."""
    cru = b"%PDF-1.7\n resto do arquivo"
    assert desembrulhar(cru) == cru


def test_desembrulhar_rejeita_formato_desconhecido():
    with pytest.raises(ValueError):
        desembrulhar(b"isto nao e nem PDF nem DER")


class SessaoFalsa:
    def __init__(self, corpo: bytes, status: int = 200):
        self.corpo, self.status = corpo, status

    def get(self, url, timeout=None):
        class R:
            pass

        r = R()
        r.status_code = self.status
        r.content = self.corpo
        return r


def test_consultar_edicao_devolve_dados():
    corpo = json.dumps({"dados": {"dataPublicacao": "2026-09-04T00:00:00"}}).encode()
    assert consultar_edicao(SessaoFalsa(corpo), date(2026, 9, 4))["dataPublicacao"].startswith("2026")


def test_consultar_edicao_sem_dados_levanta_sem_edicao():
    corpo = json.dumps({"dados": None, "erros": []}).encode()
    with pytest.raises(SemEdicao):
        consultar_edicao(SessaoFalsa(corpo), date(2026, 9, 6))


def test_http_401_vira_sem_edicao():
    with pytest.raises(SemEdicao):
        consultar_edicao(SessaoFalsa(b"", status=401), date(2026, 9, 6))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iofmg_api.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.fontes.iofmg'`

- [ ] **Step 3: Write minimal implementation**

`radar/fontes/iofmg/__init__.py`:

```python
"""Diário Oficial de Minas Gerais (Imprensa Oficial de MG)."""
```

`radar/fontes/iofmg/pkcs7.py`:

```python
"""Desembrulho do PDF assinado do IOF-MG.

O `arquivo` da API é base64 de um envelope PKCS#7/CMS em BER de comprimento
indefinido (`30 80`), não DER estrito. `asn1crypto` lê BER; fazemos isso em
Python puro para não depender do binário `openssl` na VPS.
"""

from __future__ import annotations

from asn1crypto import cms

_MAGIC_PDF = b"%PDF"
_DER_SEQUENCE = 0x30


def desembrulhar(bruto: bytes) -> bytes:
    """Devolve o PDF, esteja ele cru ou dentro de um envelope assinado."""
    if bruto[:4] == _MAGIC_PDF:
        return bruto
    if bruto and bruto[0] == _DER_SEQUENCE:
        info = cms.ContentInfo.load(bruto)
        conteudo = info["content"]["encap_content_info"]["content"].native
        if not conteudo or conteudo[:4] != _MAGIC_PDF:
            raise ValueError("Envelope PKCS#7 não encapsula um PDF.")
        return conteudo
    raise ValueError(
        f"Formato desconhecido: não é PDF nem envelope DER/BER (primeiros bytes: {bruto[:8]!r})"
    )
```

`radar/fontes/iofmg/api.py`:

```python
"""Cliente da API de edições do Jornal Minas Gerais."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import urlencode

from radar.core.erros import FonteIndisponivel, SemEdicao
from radar.core.http import obter_bytes

URL_API = (
    "https://www.jornalminasgerais.mg.gov.br/api/v1/Jornal/ObterEdicaoPorDataPublicacao"
)


def montar_url(data: date) -> str:
    return f"{URL_API}?{urlencode({'dataPublicacao': data.strftime('%Y-%m-%d')})}"


def dados_de(bruto: bytes, data: date) -> dict:
    """Extrai o objeto `dados` de uma resposta já baixada.

    Separado de `consultar_edicao` para que o caminho com cache em disco e o
    caminho de rede compartilhem exatamente a mesma interpretação.
    """
    try:
        resposta = json.loads(bruto)
    except json.JSONDecodeError as exc:
        raise FonteIndisponivel(f"Resposta da API do IOF-MG não é JSON: {exc}") from exc

    dados = resposta.get("dados")
    if not dados:
        raise SemEdicao(f"Nenhuma edição do IOF-MG publicada em {data.isoformat()}")
    return dados


def consultar_edicao(sessao, data: date) -> dict:
    """Devolve o objeto `dados` da edição. Sem edição na data → `SemEdicao`."""
    return dados_de(obter_bytes(sessao, montar_url(data)), data)


def caderno_principal(dados: dict, descricao: str) -> dict:
    """Localiza o caderno pedido pela descrição configurada."""
    for caderno in dados.get("cadernos", []):
        if caderno.get("descricao") == descricao:
            return caderno
    disponiveis = [c.get("descricao") for c in dados.get("cadernos", [])]
    raise SemEdicao(f"Caderno {descricao!r} não encontrado. Disponíveis: {disponiveis}")


def extrair_base64(dados: dict) -> str:
    return str(dados.get("arquivoCadernoPrincipal", {}).get("arquivo", ""))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_iofmg_api.py -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Commit**

```bash
git add radar/fontes/iofmg/ tests/test_iofmg_api.py
git commit -m "feat: API do IOF-MG e desembrulho PKCS7 em Python puro"
```

---

### Task 13: IOF-MG — recorte de páginas pelo índice de seções

Substitui o `find_section_pages()`, que lia só a página 1 e confiava em regex sobre o sumário.

**Files:**
- Create: `radar/fontes/iofmg/pdf.py`
- Create: `tests/test_iofmg_pdf.py`

**Interfaces:**
- Consumes: `SemEdicao` (Task 2)
- Produces:
  - `intervalo_da_secao(caderno: dict, secao: str, total_paginas: int) -> tuple[int, int]`
  - `proxima_secao(caderno: dict, secao: str) -> str | None`
  - `texto_das_paginas(pdf: bytes, inicio: int, fim: int) -> list[tuple[int, str]]`
  - `truncar_na_proxima_secao(paginas: list[tuple[int, str]], proxima: str | None) -> list[tuple[int, str]]`
  - `limpar(texto: str) -> str`

**Por que o truncamento existe:** a última página do intervalo é compartilhada — ela contém o fim da seção alvo *e* o início da próxima. Sem cortar no cabeçalho da próxima seção, atos da Educação entram na coleta como se fossem da Saúde. A spec §7.2 exige isso.

- [ ] **Step 1: Write the failing test**

`tests/test_iofmg_pdf.py`:

```python
import json
from pathlib import Path

import pytest

from radar.core.erros import SemEdicao
from radar.fontes.iofmg.pdf import intervalo_da_secao, limpar, texto_das_paginas

CADERNO = {
    "id": 330896,
    "descricao": "Diário do Executivo",
    "secoes": [
        {"descricao": "Governo do Estado", "paginaInicial": 1},
        {"descricao": "Secretaria de Estado de Saúde", "paginaInicial": 16},
        {"descricao": "Secretaria de Estado de Educação", "paginaInicial": 17},
        {"descricao": "Editais e Avisos", "paginaInicial": 23},
    ],
}


def test_intervalo_vai_ate_a_proxima_secao():
    assert intervalo_da_secao(CADERNO, "Secretaria de Estado de Saúde", 53) == (16, 17)


def test_ultima_secao_vai_ate_o_fim_do_caderno():
    assert intervalo_da_secao(CADERNO, "Editais e Avisos", 53) == (23, 53)


def test_secoes_fora_de_ordem_sao_ordenadas():
    embaralhado = {"secoes": list(reversed(CADERNO["secoes"]))}
    assert intervalo_da_secao(embaralhado, "Secretaria de Estado de Saúde", 53) == (16, 17)


def test_secao_ausente_levanta_sem_edicao():
    with pytest.raises(SemEdicao):
        intervalo_da_secao(CADERNO, "Secretaria de Estado de Turismo", 53)


def test_secao_ausente_lista_as_disponiveis_na_mensagem():
    with pytest.raises(SemEdicao) as exc:
        intervalo_da_secao(CADERNO, "Inexistente", 53)
    assert "Governo do Estado" in str(exc.value)


def test_extrai_texto_das_paginas_reais(dir_fixtures: Path):
    """A fixture ja vem recortada nas paginas da SES-MG."""
    pdf = (dir_fixtures / "iofmg" / "caderno-2026-09-03-ses.pdf").read_bytes()
    paginas = texto_das_paginas(pdf, 1, 2)
    assert len(paginas) == 2
    assert all(isinstance(n, int) and isinstance(t, str) for n, t in paginas)
    assert sum(len(t) for _, t in paginas) > 10_000


def test_texto_contem_normativas_da_ses(dir_fixtures: Path):
    pdf = (dir_fixtures / "iofmg" / "caderno-2026-09-03-ses.pdf").read_bytes()
    tudo = "\n".join(t for _, t in texto_das_paginas(pdf, 1, 2))
    assert "RESOLUÇÃO SES" in tudo.upper()


def test_intervalo_alem_do_total_nao_estoura(dir_fixtures: Path):
    pdf = (dir_fixtures / "iofmg" / "caderno-2026-09-03-ses.pdf").read_bytes()
    assert len(texto_das_paginas(pdf, 1, 999)) == 2


def test_limpar_remove_cabecalho_recorrente():
    sujo = "MINAS GERAIS \tDiário do Executivo\t\n16 – quinta-feira, 03 DE Setembro DE 2026\nPORTARIA Nº 1"
    assert "PORTARIA Nº 1" in limpar(sujo)
    assert "Diário do Executivo" not in limpar(sujo)


def test_limpar_junta_palavra_hifenizada_na_quebra():
    assert "delegação" in limpar("dispõe sobre a delega-\nção de competência")


def test_limpar_preserva_hifen_legitimo():
    assert "CIB-SUS" in limpar("DELIBERAÇÃO CIB-SUS/MG Nº 5.953")


def test_limpar_refaz_separador_de_milhar_quebrado():
    """A extracao do PDF insere espaco depois do ponto de milhar."""
    assert "5.953" in limpar("DELIBERAÇÃO CIB-SUS/MG Nº 5. 953, DE 1 DE SETEMBRO")
    assert "R$ 168.895.626,43" in limpar("valor total anual de R$ 168. 895. 626,43")
    assert "1.130.647-9" in limpar("MASP 1. 130. 647-9")


def test_limpar_nao_junta_quando_nao_ha_tres_digitos():
    """So o padrao de milhar (exatamente 3 digitos) e normalizado."""
    assert limpar("no exercício de 2025. 30 servidores") == "no exercício de 2025. 30 servidores"


def test_limpar_nao_apaga_o_nome_do_estado_dentro_do_ato():
    """Regressao: sem ancora de linha, o nome das entidades e mutilado.

    "MINAS GERAIS" aparece 27 vezes dentro do corpo dos atos nas edicoes reais.
    """
    sujo = (
        "MINAS GERAIS 	
"
        "Diário do Executivo	
"
        "A PRESIDENTE DA FUNDAÇÃO HOSPITALAR DO ESTADO DE MINAS GERAIS - FHEMIG resolve:
"
    )
    limpo = limpar(sujo)
    assert "FUNDAÇÃO HOSPITALAR DO ESTADO DE MINAS GERAIS - FHEMIG" in limpo
    assert limpo.count("MINAS GERAIS") == 1, "só a ocorrência do corpo deve sobrar"
    assert "Diário do Executivo" not in limpo


def test_proxima_secao_e_a_seguinte_por_pagina():
    from radar.fontes.iofmg.pdf import proxima_secao

    assert proxima_secao(CADERNO, "Secretaria de Estado de Saúde") == (
        "Secretaria de Estado de Educação"
    )


def test_proxima_secao_da_ultima_e_none():
    from radar.fontes.iofmg.pdf import proxima_secao

    assert proxima_secao(CADERNO, "Editais e Avisos") is None


def test_trunca_pagina_de_fronteira_no_cabecalho_seguinte():
    """A ultima pagina traz o fim da secao alvo E o inicio da proxima."""
    from radar.fontes.iofmg.pdf import truncar_na_proxima_secao

    paginas = [
        (16, "PORTARIA SES Nº 1\nConteudo da saude."),
        (17, "Fim da saude.\nSecretaria de Estado de Educação\nPORTARIA SEE Nº 9\nConteudo da educacao."),
    ]
    cortadas = truncar_na_proxima_secao(paginas, "Secretaria de Estado de Educação")
    assert "Fim da saude." in cortadas[1][1]
    assert "PORTARIA SEE" not in cortadas[1][1]
    assert "Conteudo da educacao" not in cortadas[1][1]


def test_truncar_sem_proxima_secao_nao_altera_nada():
    from radar.fontes.iofmg.pdf import truncar_na_proxima_secao

    paginas = [(23, "EDITAL Nº 1\nConteudo.")]
    assert truncar_na_proxima_secao(paginas, None) == paginas


def test_truncar_ignora_paginas_que_nao_a_ultima():
    from radar.fontes.iofmg.pdf import truncar_na_proxima_secao

    paginas = [
        (16, "Secretaria de Estado de Educação mencionada de passagem.\nPORTARIA SES Nº 1"),
        (17, "Conteudo final."),
    ]
    cortadas = truncar_na_proxima_secao(paginas, "Secretaria de Estado de Educação")
    assert cortadas[0][1] == paginas[0][1], "só a última página é truncada"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iofmg_pdf.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.fontes.iofmg.pdf'`

- [ ] **Step 3: Write minimal implementation**

`radar/fontes/iofmg/pdf.py`:

```python
"""Recorte e limpeza do PDF do IOF-MG.

O intervalo de páginas de cada órgão vem do índice que a própria API entrega em
`cadernos[].secoes[]`, o que dispensa parsear o sumário impresso.
"""

from __future__ import annotations

import re

import fitz

from radar.core.erros import SemEdicao

# Linha feita APENAS de mobiliario de pagina, uma ou mais pecas. A ancora de
# linha e obrigatoria: "MINAS GERAIS" aparece 27 vezes DENTRO do corpo dos
# atos ("FUNDACAO HOSPITALAR DO ESTADO DE MINAS GERAIS - FHEMIG"), e remove-la
# sem ancora mutila o nome das entidades que publicam.
_CABECALHO = re.compile(
    r"^[ \t]*(?:(?:MINAS GERAIS|Diário do Executivo|Diário do Legislativo)[ \t]*)+$",
    re.IGNORECASE | re.MULTILINE,
)
_LINHA_DE_PAGINA = re.compile(
    r"^\s*\d{1,4}\s*[–-]\s*(?:segunda|terça|quarta|quinta|sexta|sábado|domingo)"
    r"[^\n]*\d{4}\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_DATA_E_PAGINA = re.compile(
    r"^\s*(?:segunda|terça|quarta|quinta|sexta|sábado|domingo)[^\n]*\d{4}\s*[–-]\s*\d{1,4}\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# A extração do PDF insere um espaço depois do ponto de milhar: "5. 953",
# "R$ 168. 895. 626,43", "MASP 1. 130. 647-9". Isso produz número de ato
# ERRADO ("5" em vez de "5.953" — quatro deliberações viram todas "5") e
# mutila os valores em reais, que são o principal sinal de captação.
# Medido nas duas edições reais: 166 normalizações, zero falsos positivos.
_MILHAR_QUEBRADO = re.compile(r"(?<=\d)\.[ ]+(?=\d{3}(?!\d))")
# Hífen no fim da linha que quebra uma palavra; o legítimo (CIB-SUS) não é seguido de \n.
_HIFENIZACAO = re.compile(r"(\w)-\s*\n\s*(\w)")
_LINHAS_VAZIAS = re.compile(r"\n{3,}")


def intervalo_da_secao(caderno: dict, secao: str, total_paginas: int) -> tuple[int, int]:
    """Páginas inicial e final do órgão, pelo índice da API.

    O fim é a página inicial da próxima seção — que compartilha essa página —
    ou o total do caderno, se for a última.
    """
    secoes = sorted(caderno.get("secoes", []), key=lambda s: s.get("paginaInicial", 0))
    for posicao, atual in enumerate(secoes):
        if atual.get("descricao") == secao:
            inicio = int(atual["paginaInicial"])
            if posicao + 1 < len(secoes):
                fim = int(secoes[posicao + 1]["paginaInicial"])
            else:
                fim = int(total_paginas)
            return inicio, max(inicio, fim)
    disponiveis = [s.get("descricao") for s in secoes]
    raise SemEdicao(f"Seção {secao!r} não encontrada no caderno. Disponíveis: {disponiveis}")


def proxima_secao(caderno: dict, secao: str) -> str | None:
    """Descrição da seção que começa depois da alvo, ou `None` se for a última."""
    secoes = sorted(caderno.get("secoes", []), key=lambda s: s.get("paginaInicial", 0))
    for posicao, atual in enumerate(secoes):
        if atual.get("descricao") == secao and posicao + 1 < len(secoes):
            return secoes[posicao + 1].get("descricao")
    return None


def truncar_na_proxima_secao(
    paginas: list[tuple[int, str]], proxima: str | None
) -> list[tuple[int, str]]:
    """Corta a última página no cabeçalho da seção seguinte.

    A página de fronteira é compartilhada entre dois órgãos; sem o corte, atos do
    órgão seguinte entram na coleta como se fossem do alvo.
    """
    if not proxima or not paginas:
        return paginas
    numero, texto = paginas[-1]
    posicao = texto.find(proxima)
    if posicao == -1:
        return paginas
    return paginas[:-1] + [(numero, texto[:posicao].rstrip())]


def texto_das_paginas(pdf: bytes, inicio: int, fim: int) -> list[tuple[int, str]]:
    """Texto de cada página do intervalo, 1-indexado e inclusivo."""
    paginas: list[tuple[int, str]] = []
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        ultimo = min(fim, doc.page_count)
        for numero in range(max(1, inicio), ultimo + 1):
            paginas.append((numero, doc[numero - 1].get_text()))
    return paginas


def limpar(texto: str) -> str:
    """Remove cabeçalhos de página e refaz palavras quebradas por hifenização."""
    limpo = _CABECALHO.sub("", texto)
    limpo = _LINHA_DE_PAGINA.sub("", limpo)
    limpo = _DATA_E_PAGINA.sub("", limpo)
    limpo = _MILHAR_QUEBRADO.sub(".", limpo)
    limpo = _HIFENIZACAO.sub(r"\1\2", limpo)
    limpo = _LINHAS_VAZIAS.sub("\n\n", limpo)
    return limpo.strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_iofmg_pdf.py -v`
Expected: PASS (19 testes)

- [ ] **Step 5: Commit**

```bash
git add radar/fontes/iofmg/pdf.py tests/test_iofmg_pdf.py
git commit -m "feat: recorte de secao do IOF-MG pelo indice da API"
```

---

### Task 14: IOF-MG — segmentação em publicações

Esta é a task de maior risco da spec. O critério de aceitação é medido, não visual: o teste exige taxa mínima de acerto sobre as duas edições reais e ausência dos falsos positivos conhecidos.

**Files:**
- Create: `radar/fontes/iofmg/segmenta.py`
- Create: `tests/test_iofmg_segmenta.py`

**Interfaces:**
- Consumes: `limpar` (Task 13)
- Produces:
  - `Bruto` (frozen dataclass): `tipo: str`, `numero: str | None`, `titulo: str`, `texto: str`, `pagina: int`
  - `segmentar(paginas: list[tuple[int, str]], tipos: list[str]) -> list[Bruto]`

- [ ] **Step 1: Write the failing test**

`tests/test_iofmg_segmenta.py`:

```python
from pathlib import Path

import pytest

from radar.fontes.iofmg.pdf import texto_das_paginas
from radar.fontes.iofmg.segmenta import Bruto, segmentar

TIPOS = ["PORTARIA", "RESOLUÇÃO", "DECRETO", "DELIBERAÇÃO", "EXTRATO", "EDITAL", "ATO", "AVISO"]


@pytest.fixture
def paginas_03(dir_fixtures: Path):
    pdf = (dir_fixtures / "iofmg" / "caderno-2026-09-03-ses.pdf").read_bytes()
    return texto_das_paginas(pdf, 1, 2)


@pytest.fixture
def paginas_02(dir_fixtures: Path):
    pdf = (dir_fixtures / "iofmg" / "caderno-2026-09-02-ses.pdf").read_bytes()
    return texto_das_paginas(pdf, 1, 3)


def test_cabecalho_exige_numero_ou_data():
    paginas = [(1, "RESOLUÇÃO SES Nº 11.606, 02 DE SETEMBRO DE 2026.\nO Secretário resolve...")]
    achados = segmentar(paginas, TIPOS)
    assert len(achados) == 1
    assert achados[0].tipo == "RESOLUÇÃO"
    assert achados[0].numero == "11.606"


def test_rejeita_delibera_dois_pontos():
    """Falso positivo real medido na sondagem."""
    paginas = [(1, "Considerando a necessidade,\nDELIBERA:\nArt. 1º Fica aprovado.")]
    assert segmentar(paginas, TIPOS) == []


def test_rejeita_mencao_em_meio_de_frase():
    """Outro falso positivo real: 'Resolucoes que menciona.'"""
    paginas = [(1, "Altera as Resoluções que menciona.\nOutro texto qualquer.")]
    assert segmentar(paginas, TIPOS) == []


def test_captura_deliberacao_cib_sus():
    """Tipo ausente da regex do script antigo e central para captacao."""
    paginas = [(1, "DELIBERAÇÃO CIB-SUS/MG Nº 5.953, DE 1 DE SETEMBRO DE 2026\nAprova recurso.")]
    achados = segmentar(paginas, TIPOS)
    assert len(achados) == 1
    assert achados[0].tipo == "DELIBERAÇÃO"
    assert "CIB-SUS" in achados[0].titulo


def test_tipos_nao_configurados_sao_ignorados():
    paginas = [(1, "PORTARIA Nº 35, DE 25 DE AGOSTO DE 2026\nAltera algo.")]
    assert segmentar(paginas, ["RESOLUÇÃO"]) == []


def test_texto_vai_ate_o_proximo_cabecalho():
    paginas = [(
        1,
        "PORTARIA Nº 1, DE 1 DE SETEMBRO DE 2026\nPrimeiro conteudo.\n"
        "PORTARIA Nº 2, DE 2 DE SETEMBRO DE 2026\nSegundo conteudo.",
    )]
    achados = segmentar(paginas, TIPOS)
    assert len(achados) == 2
    assert "Primeiro conteudo" in achados[0].texto
    assert "Segundo conteudo" not in achados[0].texto
    assert "Segundo conteudo" in achados[1].texto


def test_registra_a_pagina_de_origem():
    paginas = [(16, "PORTARIA Nº 1, DE 1 DE SETEMBRO DE 2026\nConteudo.")]
    assert segmentar(paginas, TIPOS)[0].pagina == 16


def test_texto_nunca_e_vazio():
    paginas = [(1, "PORTARIA Nº 1, DE 1 DE SETEMBRO DE 2026\nConteudo relevante aqui.")]
    for bruto in segmentar(paginas, TIPOS):
        assert bruto.texto.strip()


def test_edicao_real_03_produz_publicacoes(paginas_03):
    achados = segmentar(paginas_03, TIPOS)
    assert len(achados) >= 5, f"segmentou apenas {len(achados)}"
    assert all(isinstance(a, Bruto) for a in achados)


def test_edicao_real_02_produz_publicacoes(paginas_02):
    achados = segmentar(paginas_02, TIPOS)
    assert len(achados) >= 5, f"segmentou apenas {len(achados)}"


def test_numero_completo_em_deliberacao_cib_sus(paginas_02):
    """Numero truncado e numero ERRADO: 4 deliberacoes distintas viram todas "5"."""
    cib = [a for a in segmentar(paginas_02, TIPOS) if "CIB-SUS" in a.titulo]
    assert cib, "as deliberacoes CIB-SUS precisam ser segmentadas"
    assert all(a.numero and "." in a.numero for a in cib), [a.numero for a in cib]
    assert len({a.numero for a in cib}) == len(cib), "os numeros devem ser distintos"


def test_edicao_real_nao_gera_falsos_positivos_conhecidos(paginas_02):
    titulos = [a.titulo.upper() for a in segmentar(paginas_02, TIPOS)]
    assert not any(t.startswith("DELIBERA:") for t in titulos)
    assert not any(t.startswith("DELIBERAÇÃO, CABERÁ") for t in titulos)


def test_maioria_dos_segmentos_tem_numero(paginas_02):
    """Proxy de qualidade: cabecalho de verdade quase sempre traz numero."""
    achados = segmentar(paginas_02, TIPOS)
    com_numero = [a for a in achados if a.numero]
    assert len(com_numero) / len(achados) >= 0.6


def test_segmentos_nao_se_sobrepoem(paginas_03):
    achados = segmentar(paginas_03, TIPOS)
    for anterior, seguinte in zip(achados, achados[1:]):
        assert seguinte.titulo not in anterior.texto
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iofmg_segmenta.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.fontes.iofmg.segmenta'`

- [ ] **Step 3: Write minimal implementation**

`radar/fontes/iofmg/segmenta.py`:

```python
"""Quebra o texto de um órgão em publicações discretas.

Herda a ideia do `parse_publications_ses` do scraper antigo, com âncora mais
forte: só é cabeçalho a linha que começa com um tipo configurado E traz número
ou data. Sem isso, `DELIBERA:` e `Resoluções que menciona.` viram publicações.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from radar.fontes.iofmg.pdf import limpar

_NUMERO = re.compile(r"N[º°o]?\s*([\d][\d.]*)", re.IGNORECASE)
_TEM_DATA = re.compile(r"\bDE\s+\d{1,2}\s+DE\s+[A-ZÇÃÊÉÓÍÚÂÔ]+\s+DE\s+\d{4}", re.IGNORECASE)


@dataclass(frozen=True)
class Bruto:
    tipo: str
    numero: str | None
    titulo: str
    texto: str
    pagina: int


def _compilar(tipos: list[str]) -> re.Pattern:
    alternativas = "|".join(re.escape(t) for t in sorted(tipos, key=len, reverse=True))
    # Cabeçalho começa a linha e não é seguido imediatamente de ':' (DELIBERA:).
    return re.compile(rf"^\s*({alternativas})(?![:A-ZÇ])(.*)$", re.IGNORECASE | re.MULTILINE)


def _e_cabecalho(tipo: str, resto: str) -> bool:
    """Só aceita como cabeçalho o que traz número ou data — o que um ato sempre traz."""
    linha = f"{tipo} {resto}"
    return bool(_NUMERO.search(linha) or _TEM_DATA.search(linha))


def segmentar(paginas: list[tuple[int, str]], tipos: list[str]) -> list[Bruto]:
    """Devolve as publicações encontradas, em ordem de aparição."""
    if not tipos:
        return []
    padrao = _compilar(tipos)
    achados: list[Bruto] = []

    for numero_pagina, bruto in paginas:
        texto = limpar(bruto)
        marcas = [
            (m.start(), m.end(), m.group(1).upper(), m.group(0).strip())
            for m in padrao.finditer(texto)
            if _e_cabecalho(m.group(1), m.group(2))
        ]
        for posicao, (inicio, fim, tipo, titulo) in enumerate(marcas):
            limite = marcas[posicao + 1][0] if posicao + 1 < len(marcas) else len(texto)
            corpo = texto[fim:limite].strip()
            if not corpo:
                continue
            achado_numero = _NUMERO.search(titulo)
            achados.append(
                Bruto(
                    tipo=tipo,
                    numero=achado_numero.group(1).rstrip(".") if achado_numero else None,
                    titulo=titulo,
                    texto=corpo,
                    pagina=numero_pagina,
                )
            )
    return achados
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_iofmg_segmenta.py -v`
Expected: PASS (14 testes). Se `test_maioria_dos_segmentos_tem_numero` ou os testes de edição real falharem, ajustar `_e_cabecalho` — **não** relaxar o limiar do teste.

- [ ] **Step 5: Commit**

```bash
git add radar/fontes/iofmg/segmenta.py tests/test_iofmg_segmenta.py
git commit -m "feat: segmentacao do IOF-MG com ancora por numero ou data"
```

---

### Task 15: IOF-MG — normalização e coletor

Ao fim desta task a coleta do IOF-MG funciona ponta a ponta.

**Files:**
- Create: `radar/fontes/iofmg/normaliza.py`
- Create: `radar/fontes/iofmg/coletor.py`
- Create: `tests/test_iofmg_coletor.py`

**Interfaces:**
- Consumes: Tasks 2, 5, 6, 12, 13, 14
- Produces:
  - `url_pagina(data: date, id_caderno: int | None, pagina: int) -> str | None`
  - `normalizar(bruto: Bruto, data_publicacao: date, coletado_em: datetime, id_caderno: int | None, orgao: str) -> Publicacao`
  - `FonteIOFMG` com `nome = "iofmg"`, `__init__(self, cfg: ConfigIOFMG, storage: Storage, sessao)` e `coletar(self, data: date, forcar: bool = False) -> Resultado`

- [ ] **Step 1: Write the failing test**

`tests/test_iofmg_coletor.py`:

```python
import gzip
import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import pytest

from radar.core.config import ConfigIOFMG
from radar.core.erros import Status
from radar.core.storage import Storage
from radar.fontes.iofmg.coletor import FonteIOFMG
from radar.fontes.iofmg.normaliza import normalizar, url_pagina
from radar.fontes.iofmg.segmenta import Bruto

QUANDO = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
DIA = date(2026, 9, 3)
BRUTO = Bruto(
    tipo="RESOLUÇÃO",
    numero="11.606",
    titulo="RESOLUÇÃO SES Nº 11.606, 02 DE SETEMBRO DE 2026.",
    texto="O Secretário de Estado de Saúde resolve aprovar o repasse.",
    pagina=16,
)


def test_url_da_pagina_usa_o_id_do_caderno_da_edicao():
    url = url_pagina(DIA, 330896, 16)
    assert "330896" in unquote(url)
    assert "326074" not in url


def test_sem_id_de_caderno_nao_emite_link():
    """Link errado e pior que link ausente: o agente cita e ninguem percebe."""
    assert url_pagina(DIA, None, 16) is None


def test_normaliza_preenche_procedencia():
    pub = normalizar(BRUTO, DIA, QUANDO, 330896, "Secretaria de Estado de Saúde")
    assert pub.fonte == "iofmg"
    assert pub.orgao == "Secretaria de Estado de Saúde"
    assert pub.tipo == "RESOLUÇÃO"
    assert pub.numero == "11.606"
    assert pub.pagina == 16
    assert pub.texto.startswith("O Secretário")


def test_secao_e_none_no_iofmg():
    """IOF-MG nao tem o conceito de Secao 1/2/3 do DOU."""
    assert normalizar(BRUTO, DIA, QUANDO, 330896, "SES").secao is None


def test_url_ausente_nao_quebra_normalizacao():
    pub = normalizar(BRUTO, DIA, QUANDO, None, "SES")
    assert pub.url == ""
    assert pub.id


class SessaoFalsa:
    def __init__(self, corpo: bytes):
        self.corpo = corpo
        self.pedidos: list[str] = []

    def get(self, url, timeout=None):
        self.pedidos.append(url)

        class R:
            status_code = 200

        r = R()
        r.content = self.corpo
        return r


@pytest.fixture
def resposta_api(dir_fixtures: Path) -> bytes:
    """Reconstroi a resposta real: metadados + envelope PKCS#7 em base64."""
    import base64

    meta = json.loads((dir_fixtures / "iofmg" / "edicao-2026-09-03.meta.json").read_text("utf-8"))
    envelope = gzip.decompress(
        (dir_fixtures / "iofmg" / "envelope-pkcs7-2026-09-03.bin.gz").read_bytes()
    )
    meta["dados"]["arquivoCadernoPrincipal"]["arquivo"] = base64.b64encode(envelope).decode()
    return json.dumps(meta).encode("utf-8")


@pytest.fixture
def storage(tmp_path: Path):
    s = Storage(tmp_path / "data")
    yield s
    s.fechar()


@pytest.fixture
def cfg() -> ConfigIOFMG:
    return ConfigIOFMG(
        caderno="Diário do Executivo",
        secao="Secretaria de Estado de Saúde",
        tipos_publicacao=["PORTARIA", "RESOLUÇÃO", "DELIBERAÇÃO", "ATO", "EXTRATO", "EDITAL"],
    )


def test_coleta_edicao_real_ponta_a_ponta(cfg, storage, resposta_api):
    resultado = FonteIOFMG(cfg, storage, SessaoFalsa(resposta_api)).coletar(DIA)
    assert resultado.status == Status.OK
    assert len(resultado.publicacoes) >= 5
    assert all(p.texto.strip() for p in resultado.publicacoes)
    assert all(p.fonte == "iofmg" for p in resultado.publicacoes)


def test_links_apontam_para_a_edicao_correta(cfg, storage, resposta_api):
    resultado = FonteIOFMG(cfg, storage, SessaoFalsa(resposta_api)).coletar(DIA)
    for pub in resultado.publicacoes:
        assert "330896" in unquote(pub.url)


def test_dia_sem_edicao_vira_status_vazio(cfg, storage):
    sessao = SessaoFalsa(json.dumps({"dados": None}).encode())
    resultado = FonteIOFMG(cfg, storage, sessao).coletar(date(2026, 9, 6))
    assert resultado.status == Status.VAZIO
    assert resultado.publicacoes == []


def test_reprocessamento_reusa_o_pdf_em_cache(cfg, storage, resposta_api):
    sessao = SessaoFalsa(resposta_api)
    fonte = FonteIOFMG(cfg, storage, sessao)
    fonte.coletar(DIA)
    pedidos = len(sessao.pedidos)
    fonte.coletar(DIA)
    assert len(sessao.pedidos) == pedidos


def test_escopo_registra_secao_e_caderno(cfg, storage, resposta_api):
    resultado = FonteIOFMG(cfg, storage, SessaoFalsa(resposta_api)).coletar(DIA)
    assert resultado.escopo["secao"] == "Secretaria de Estado de Saúde"
    assert resultado.escopo["caderno"] == "Diário do Executivo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iofmg_coletor.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.fontes.iofmg.normaliza'`

- [ ] **Step 3: Write minimal implementation**

`radar/fontes/iofmg/normaliza.py`:

```python
"""Converte um segmento do IOF-MG em `Publicacao`."""

from __future__ import annotations

import json
from datetime import date, datetime
from urllib.parse import quote

from radar.core.modelos import Publicacao, gerar_id
from radar.fontes.iofmg.segmenta import Bruto

_BASE_EDICAO = "https://www.jornalminasgerais.mg.gov.br/edicao-do-dia?dados="


def url_pagina(data: date, id_caderno: int | None, pagina: int) -> str | None:
    """Link para a página no visualizador do Jornal MG.

    Sem o id do caderno da própria edição não há link correto — devolvemos
    `None` em vez de um link que aponta para a edição errada.
    """
    if id_caderno is None:
        return None
    payload = {
        "dataPublicacaoSelecionada": f"{data.isoformat()}T03:00:00.000Z",
        "idCadernoEdicaoSelecionado": id_caderno,
        "paginaSelecionada": pagina,
    }
    return _BASE_EDICAO + quote(json.dumps(payload, separators=(",", ":")))


def normalizar(
    bruto: Bruto,
    data_publicacao: date,
    coletado_em: datetime,
    id_caderno: int | None,
    orgao: str,
) -> Publicacao:
    url = url_pagina(data_publicacao, id_caderno, bruto.pagina) or ""
    ementa = bruto.texto.split(".")[0][:300] if bruto.texto else None
    return Publicacao(
        id=gerar_id("iofmg", data_publicacao, url or bruto.titulo, bruto.titulo),
        fonte="iofmg",
        data_publicacao=data_publicacao,
        coletado_em=coletado_em,
        orgao=orgao,
        unidade=None,
        secao=None,  # IOF-MG não tem Seção 1/2/3.
        pagina=bruto.pagina,
        edicao=str(id_caderno) if id_caderno is not None else None,
        tipo=bruto.tipo,
        numero=bruto.numero,
        titulo=bruto.titulo,
        ementa=ementa,
        texto=bruto.texto,
        url=url,
        origem={"metodo": "api jornalminasgerais", "id_caderno": id_caderno},
    )
```

`radar/fontes/iofmg/coletor.py`:

```python
"""Coleta do IOF-MG: API → PKCS#7 → PDF → recorte da seção → segmentação."""

from __future__ import annotations

import base64
from datetime import date

from radar.core.config import ConfigIOFMG
from radar.core.datas import agora_utc
from radar.core.erros import SemEdicao, Status
from radar.core.http import obter_bytes
from radar.core.log import configurar_log
from radar.core.modelos import Resultado
from radar.core.storage import Storage
from radar.fontes.iofmg import api, normaliza, pdf as pdf_mod, segmenta
from radar.fontes.iofmg.pkcs7 import desembrulhar


class FonteIOFMG:
    nome = "iofmg"

    def __init__(self, cfg: ConfigIOFMG, storage: Storage, sessao) -> None:
        self.cfg = cfg
        self.storage = storage
        self.sessao = sessao
        self.logger = configurar_log()

    def coletar(self, data: date, forcar: bool = False) -> Resultado:
        quando = agora_utc()
        escopo = {"caderno": self.cfg.caderno, "secao": self.cfg.secao}
        vazio = Resultado(
            fonte=self.nome, data_publicacao=data, coletado_em=quando,
            status=Status.VAZIO, escopo=escopo, publicacoes=[], avisos=[],
        )

        try:
            dados = self._obter_dados(data, forcar)
            caderno = api.caderno_principal(dados, self.cfg.caderno)
            arquivo = dados.get("arquivoCadernoPrincipal", {})
            total_paginas = int(arquivo.get("totalPaginas", 0))
            inicio, fim = pdf_mod.intervalo_da_secao(caderno, self.cfg.secao, total_paginas)
        except SemEdicao as exc:
            self.logger.info("IOF-MG %s: %s", data, exc)
            vazio.avisos.append(str(exc))
            return vazio

        conteudo = self._obter_pdf(data, dados, forcar)
        paginas = pdf_mod.texto_das_paginas(conteudo, inicio, fim)
        # A última página é compartilhada com o órgão seguinte; cortar antes de segmentar.
        paginas = pdf_mod.truncar_na_proxima_secao(
            paginas, pdf_mod.proxima_secao(caderno, self.cfg.secao)
        )
        brutos = segmenta.segmentar(paginas, self.cfg.tipos_publicacao)

        if not brutos:
            aviso = f"Seção {self.cfg.secao!r} localizada em pp. {inicio}-{fim}, mas nada segmentado."
            self.logger.warning("IOF-MG %s: %s", data, aviso)
            vazio.avisos.append(aviso)
            return vazio

        id_caderno = caderno.get("id")
        publicacoes = [
            normaliza.normalizar(b, data, quando, id_caderno, self.cfg.secao) for b in brutos
        ]
        self.logger.info("IOF-MG %s: %d publicações em pp. %d-%d", data, len(publicacoes), inicio, fim)
        return Resultado(
            fonte=self.nome, data_publicacao=data, coletado_em=quando,
            status=Status.OK, escopo=escopo, publicacoes=publicacoes, avisos=[],
        )

    def _obter_dados(self, data: date, forcar: bool) -> dict:
        """Lê do cache ou da rede; a interpretação é a mesma nos dois caminhos."""
        if not forcar:
            guardado = self.storage.ler_raw(data, self.nome, "edicao.json")
            if guardado is not None:
                return api.dados_de(guardado, data)

        bruto = obter_bytes(self.sessao, api.montar_url(data))
        self.storage.salvar_raw(data, self.nome, "edicao.json", bruto)
        return api.dados_de(bruto, data)

    def _obter_pdf(self, data: date, dados: dict, forcar: bool) -> bytes:
        if not forcar:
            guardado = self.storage.ler_raw(data, self.nome, "caderno.pdf")
            if guardado is not None:
                return guardado
        conteudo = desembrulhar(base64.b64decode(api.extrair_base64(dados)))
        self.storage.salvar_raw(data, self.nome, "caderno.pdf", conteudo)
        return conteudo
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_iofmg_coletor.py -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Commit**

```bash
git add radar/fontes/iofmg/normaliza.py radar/fontes/iofmg/coletor.py tests/test_iofmg_coletor.py
git commit -m "feat: coletor do IOF-MG com link da edicao correta"
```

---

### Task 16: CLI — `coletar` e `consultar`

**Files:**
- Create: `radar/cli.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 2–6, 11, 15
- Produces: `main(argv: list[str] | None = None) -> int` e `executar() -> None` (entry point do console script)

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
import json
from datetime import date
from pathlib import Path

import pytest

from radar.cli import main

YAML = """
timezone: America/Sao_Paulo
fontes:
  dou:
    orgao: "Ministério da Saúde"
    delta: 75
    concorrencia: 2
    baixar_texto_integral: false
  iofmg:
    caderno: "Diário do Executivo"
    secao: "Secretaria de Estado de Saúde"
    tipos_publicacao: [PORTARIA]
armazenamento:
  dir_dados: "{dir_dados}"
  reter_bruto_dias: 30
"""


@pytest.fixture
def ambiente(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(YAML.format(dir_dados=(tmp_path / "data").as_posix()), encoding="utf-8")

    from radar.core.erros import Status
    from radar.core.modelos import Resultado

    def coleta_falsa(self, data, forcar=False):
        from radar.core.datas import agora_utc

        return Resultado(
            fonte=self.nome, data_publicacao=data, coletado_em=agora_utc(),
            status=Status.OK, escopo={}, publicacoes=[], avisos=[],
        )

    monkeypatch.setattr("radar.fontes.dou.coletor.FonteDOU.coletar", coleta_falsa)
    monkeypatch.setattr("radar.fontes.iofmg.coletor.FonteIOFMG.coletar", coleta_falsa)
    return cfg, tmp_path / "data"


def test_coletar_uma_fonte_devolve_exit_zero(ambiente):
    cfg, _ = ambiente
    assert main(["coletar", "--config", str(cfg), "--data", "2026-09-04", "--fonte", "dou"]) == 0


def test_coletar_grava_o_json_normalizado(ambiente):
    cfg, dir_dados = ambiente
    main(["coletar", "--config", str(cfg), "--data", "2026-09-04", "--fonte", "dou"])
    destino = dir_dados / "normalized" / "2026-09-04" / "dou.json"
    assert destino.exists()
    assert json.loads(destino.read_text(encoding="utf-8"))["status"] == "ok"


def test_coletar_todas_gera_um_json_por_fonte(ambiente):
    cfg, dir_dados = ambiente
    main(["coletar", "--config", str(cfg), "--data", "2026-09-04", "--fonte", "todas"])
    pasta = dir_dados / "normalized" / "2026-09-04"
    assert (pasta / "dou.json").exists()
    assert (pasta / "iofmg.json").exists()


def test_status_parcial_devolve_exit_um(ambiente, monkeypatch):
    cfg, _ = ambiente
    from radar.core.datas import agora_utc
    from radar.core.erros import Status
    from radar.core.modelos import Resultado

    def parcial(self, data, forcar=False):
        return Resultado(
            fonte=self.nome, data_publicacao=data, coletado_em=agora_utc(),
            status=Status.PARCIAL, escopo={}, publicacoes=[], avisos=["algo falhou"],
        )

    monkeypatch.setattr("radar.fontes.dou.coletor.FonteDOU.coletar", parcial)
    assert main(["coletar", "--config", str(cfg), "--data", "2026-09-04", "--fonte", "dou"]) == 1


def test_fonte_indisponivel_devolve_exit_dois(ambiente, monkeypatch):
    cfg, _ = ambiente
    from radar.core.erros import FonteIndisponivel

    def explode(self, data, forcar=False):
        raise FonteIndisponivel("rede caiu")

    monkeypatch.setattr("radar.fontes.dou.coletor.FonteDOU.coletar", explode)
    assert main(["coletar", "--config", str(cfg), "--data", "2026-09-04", "--fonte", "dou"]) == 2


def test_pior_status_entre_fontes_define_o_exit(ambiente, monkeypatch):
    cfg, _ = ambiente
    from radar.core.erros import FonteIndisponivel

    def explode(self, data, forcar=False):
        raise FonteIndisponivel("rede caiu")

    monkeypatch.setattr("radar.fontes.iofmg.coletor.FonteIOFMG.coletar", explode)
    assert main(["coletar", "--config", str(cfg), "--data", "2026-09-04", "--fonte", "todas"]) == 2


def test_data_invalida_devolve_exit_dois(ambiente):
    cfg, _ = ambiente
    assert main(["coletar", "--config", str(cfg), "--data", "ontem", "--fonte", "dou"]) == 2


def test_consultar_encontra_no_historico(ambiente, capsys):
    cfg, dir_dados = ambiente
    from datetime import datetime, timezone

    from radar.core.modelos import Publicacao, gerar_id
    from radar.core.storage import Storage

    s = Storage(dir_dados)
    d = date(2026, 9, 4)
    s.gravar([
        Publicacao(
            id=gerar_id("dou", d, "https://x/1", "T"), fonte="dou", data_publicacao=d,
            coletado_em=datetime(2026, 9, 4, tzinfo=timezone.utc), orgao="MS", unidade=None,
            secao="1", pagina=None, edicao=None, tipo="Portaria", numero=None, titulo="T",
            ementa=None, texto="ampliacao do teto MAC", url="https://x/1", origem={},
        )
    ])
    s.fechar()
    assert main(["consultar", "--config", str(cfg), "teto"]) == 0
    assert "teto MAC" in capsys.readouterr().out


def test_consultar_sem_resultado_devolve_zero(ambiente, capsys):
    cfg, _ = ambiente
    assert main(["consultar", "--config", str(cfg), "inexistente"]) == 0


def test_modulo_executavel_com_python_m():
    """Sem a guarda __main__, `python -m radar.cli` sai 0 em silencio.

    Um cron nessa forma reportaria sucesso todo dia sem coletar nada. Usamos
    --help porque ele exercita o despacho sem tocar a rede.
    """
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "radar.cli", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "coletar" in r.stdout, "o --help precisa listar os subcomandos"
    assert "consultar" in r.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.cli'`

- [ ] **Step 3: Write minimal implementation**

`radar/cli.py`:

```python
"""Interface de linha de comando. Pensada para cron e para agente."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from radar.core.config import Config
from radar.core.datas import hoje, parse_data
from radar.core.erros import ErroRadar, Status, status_para_exit
from radar.core.http import criar_sessao
from radar.core.log import configurar_log
from radar.core.storage import Storage

def _montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="radar", description="Radar de Diários Oficiais")
    # `--config` fica só nos subcomandos: declará-lo também no parser de topo faz
    # o default do subparser sobrescrever silenciosamente o valor informado antes
    # do subcomando.
    sub = parser.add_subparsers(dest="comando", required=True)

    coletar = sub.add_parser("coletar", help="Coleta as publicações de uma data")
    coletar.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    coletar.add_argument("--data", default=None, help="AAAA-MM-DD ou DD/MM/AAAA (padrão: hoje)")
    coletar.add_argument("--fonte", choices=["dou", "iofmg", "todas"], default="todas")
    coletar.add_argument("--forcar", action="store_true", help="Ignora o cache de artefatos brutos")

    consultar = sub.add_parser("consultar", help="Busca no histórico já coletado")
    consultar.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    consultar.add_argument("termo")
    consultar.add_argument("--desde", default=None)
    return parser


def _fontes(nome: str, cfg: Config, storage: Storage, sessao) -> list:
    from radar.fontes.dou.coletor import FonteDOU
    from radar.fontes.iofmg.coletor import FonteIOFMG

    disponiveis = {
        "dou": lambda: FonteDOU(cfg.dou, storage, sessao),
        "iofmg": lambda: FonteIOFMG(cfg.iofmg, storage, sessao),
    }
    chaves = list(disponiveis) if nome == "todas" else [nome]
    return [disponiveis[c]() for c in chaves]


def _coletar(args) -> int:
    logger = configurar_log()
    cfg = Config.carregar(args.config)
    data = parse_data(args.data) if args.data else hoje()

    storage = Storage(cfg.dir_dados)
    sessao = criar_sessao()
    pior = 0
    try:
        for fonte in _fontes(args.fonte, cfg, storage, sessao):
            try:
                resultado = fonte.coletar(data, forcar=args.forcar)
            except ErroRadar as exc:
                logger.error("%s falhou: %s", fonte.nome, exc)
                pior = max(pior, status_para_exit(Status.ERRO))
                continue
            storage.salvar_normalizado(resultado)
            storage.gravar(resultado.publicacoes)
            pior = max(pior, status_para_exit(resultado.status))
            print(
                f"{resultado.fonte}: {resultado.status} | "
                f"{len(resultado.publicacoes)} publicações | {len(resultado.avisos)} avisos"
            )
    finally:
        storage.fechar()
    return pior


def _consultar(args) -> int:
    cfg = Config.carregar(args.config)
    storage = Storage(cfg.dir_dados)
    try:
        desde = parse_data(args.desde) if args.desde else None
        for linha in storage.consultar(args.termo, desde):
            print(f"{linha['data_publicacao']} | {linha['fonte']:6s} | {linha['titulo'][:70]}")
            print(f"    {linha['texto'][:160]}")
    finally:
        storage.fechar()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _montar_parser().parse_args(argv)
    configurar_log()
    try:
        if args.comando == "coletar":
            return _coletar(args)
        return _consultar(args)
    except (ErroRadar, ValueError, FileNotFoundError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2


def executar() -> None:
    raise SystemExit(main())


# Sem esta guarda, `python -m radar.cli coletar ...` importa o modulo, nao roda
# nada e sai com codigo 0. Um cron nessa forma reportaria sucesso todo dia sem
# coletar coisa alguma — falha total silenciosa, que e exatamente o que o
# contrato de status existe para impedir.
if __name__ == "__main__":
    executar()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Commit**

```bash
git add radar/cli.py tests/test_cli.py
git commit -m "feat: CLI coletar e consultar com exit code por status"
```

---

### Task 17: Notificação por e-mail (opcional, fora do núcleo)

Substitui as **quatro** implementações de envio espalhadas hoje (Gmail API, SMTP, `email_sender` externo, ×2) por uma só. Corrige o bug 10 da spec: `pub["url"]`, que vem raspado da web, era interpolado cru dentro de `href`.

**Files:**
- Create: `radar/notificacao/__init__.py`
- Create: `radar/notificacao/email.py`
- Modify: `radar/cli.py` (acrescentar o subcomando `notificar`)
- Create: `tests/test_notificacao.py`

**Interfaces:**
- Consumes: `Resultado` (Task 2), `Storage` (Task 6), `Config` (Task 4)
- Produces:
  - `montar_html(resultados: list[Resultado]) -> str`
  - `enviar(html: str, assunto: str, cfg_email: dict) -> bool`

- [ ] **Step 1: Write the failing test**

`tests/test_notificacao.py`:

```python
from datetime import date, datetime, timezone

import pytest

from radar.core.erros import Status
from radar.core.modelos import Publicacao, Resultado, gerar_id
from radar.notificacao.email import enviar, montar_html


def _pub(titulo="Portaria 1", url="https://in.gov.br/x", unidade=None) -> Publicacao:
    d = date(2026, 9, 4)
    return Publicacao(
        id=gerar_id("dou", d, url, titulo), fonte="dou", data_publicacao=d,
        coletado_em=datetime(2026, 9, 4, tzinfo=timezone.utc), orgao="Ministério da Saúde",
        unidade=unidade, secao="1", pagina=None, edicao="168", tipo="Portaria", numero="1",
        titulo=titulo, ementa="Faz algo.", texto="Art. 1º ...", url=url, origem={},
    )


def _resultado(publicacoes) -> Resultado:
    return Resultado(
        fonte="dou", data_publicacao=date(2026, 9, 4),
        coletado_em=datetime(2026, 9, 4, tzinfo=timezone.utc), status=Status.OK,
        escopo={"orgao": "Ministério da Saúde"}, publicacoes=publicacoes, avisos=[],
    )


def test_html_lista_as_publicacoes():
    html = montar_html([_resultado([_pub()])])
    assert "Portaria 1" in html
    assert "Ministério da Saúde" in html


def test_orgao_aparece_uma_vez_so_e_nao_por_publicacao():
    """Repetir o orgao em cada item vira ruido: sao 118 num dia de DOU."""
    html = montar_html([_resultado([
        _pub(titulo="A", url="https://x/a"),
        _pub(titulo="B", url="https://x/b"),
    ])])
    assert html.count("Ministério da Saúde") == 1


def test_unidade_aparece_quando_existe():
    """`unidade` varia dentro da coleta (Gabinete do Ministro, ANVISA) e informa."""
    html = montar_html([_resultado([_pub(titulo="A", url="https://x/a", unidade="ANVISA")])])
    assert "ANVISA" in html


def test_titulo_com_html_e_escapado():
    html = montar_html([_resultado([_pub(titulo='Portaria <script>alert(1)</script>')])])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_url_e_escapada_no_href():
    """Bug 10: pub['url'] vem raspado da web e era interpolado cru no href."""
    html = montar_html([_resultado([_pub(url='https://x/a" onmouseover="mal()')])])
    assert 'onmouseover="mal()"' not in html
    assert "&quot;" in html or "%22" in html


def test_avisos_aparecem_no_html():
    r = _resultado([_pub()])
    r.avisos = ["paginação travou"]
    assert "paginação travou" in montar_html([r])


def test_status_vazio_gera_html_sem_estourar():
    r = _resultado([])
    r.status = Status.VAZIO
    assert "sem publicações" in montar_html([r]).lower()


def test_enviar_sem_destinatario_devolve_false():
    assert enviar("<p>x</p>", "assunto", {"habilitado": True, "destinatarios": []}) is False


def test_enviar_desabilitado_devolve_false():
    assert enviar("<p>x</p>", "assunto", {"habilitado": False, "destinatarios": ["a@b.c"]}) is False


def test_enviar_usa_smtp_do_ambiente(monkeypatch):
    enviadas = {}

    class SMTPFalso:
        def __init__(self, host, port, timeout=None):
            enviadas["host"], enviadas["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            enviadas["tls"] = True

        def login(self, u, p):
            enviadas["user"] = u

        def sendmail(self, de, para, msg):
            enviadas["para"] = para

    monkeypatch.setattr("smtplib.SMTP", SMTPFalso)
    monkeypatch.setenv("RADAR_SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setenv("RADAR_SMTP_PORT", "587")
    monkeypatch.setenv("RADAR_SMTP_USER", "u@exemplo.com")
    monkeypatch.setenv("RADAR_SMTP_PASSWORD", "segredo")
    monkeypatch.setenv("RADAR_EMAIL_FROM", "u@exemplo.com")

    assert enviar("<p>x</p>", "assunto", {"habilitado": True, "destinatarios": ["a@b.c"]}) is True
    assert enviadas["host"] == "smtp.exemplo.com"
    assert enviadas["para"] == ["a@b.c"]


def test_falha_de_envio_devolve_false_sem_propagar(monkeypatch):
    def explode(*a, **k):
        raise OSError("smtp fora do ar")

    monkeypatch.setattr("smtplib.SMTP", explode)
    monkeypatch.setenv("RADAR_SMTP_HOST", "smtp.exemplo.com")
    assert enviar("<p>x</p>", "a", {"habilitado": True, "destinatarios": ["a@b.c"]}) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_notificacao.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'radar.notificacao'`

- [ ] **Step 3: Write minimal implementation**

`radar/notificacao/__init__.py`:

```python
"""Notificação opcional. Fora do núcleo: a newsletter é do agente de marketing."""
```

`radar/notificacao/email.py`:

```python
"""Envio de briefing bruto por e-mail. Uma implementação, não quatro."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from html import escape

from radar.core.erros import Status
from radar.core.log import configurar_log
from radar.core.modelos import Resultado

_ESTILO = (
    "font-family:Segoe UI,Arial,sans-serif;line-height:1.5;color:#222;"
    "max-width:760px;margin:0 auto;padding:16px;"
)


def montar_html(resultados: list[Resultado]) -> str:
    """Monta o corpo do e-mail escapando todo campo vindo da raspagem."""
    partes = [f'<body style="{_ESTILO}">']
    for resultado in resultados:
        partes.append(
            f"<h2>{escape(resultado.fonte.upper())} — "
            f"{escape(resultado.data_publicacao.strftime('%d/%m/%Y'))} "
            f"({escape(str(resultado.status))})</h2>"
        )
        # O escopo (órgão/seção) é o mesmo para toda a coleta: entra uma vez no
        # cabeçalho. Repeti-lo por publicação daria 118 linhas iguais num dia de DOU.
        escopo = resultado.escopo.get("orgao") or resultado.escopo.get("secao") or ""
        if escopo:
            partes.append(f"<p><strong>{escape(escopo)}</strong></p>")
        if resultado.avisos:
            itens = "".join(f"<li>{escape(a)}</li>" for a in resultado.avisos)
            partes.append(f'<ul style="color:#8a6d3b">{itens}</ul>')
        if resultado.status == Status.VAZIO or not resultado.publicacoes:
            partes.append("<p><em>Dia sem publicações para o escopo monitorado.</em></p>")
            continue
        partes.append(f"<p>{len(resultado.publicacoes)} publicações.</p><ul>")
        for pub in resultado.publicacoes:
            titulo = escape(pub.titulo)
            # `quote=True` é o que impede a URL raspada de escapar do atributo.
            destino = escape(pub.url or "", quote=True)
            corpo = escape((pub.ementa or pub.texto)[:220])
            link = f'<a href="{destino}">{titulo}</a>' if destino else titulo
            # `unidade` varia dentro da mesma coleta (Gabinete do Ministro,
            # ANVISA, FHEMIG) e por isso informa; `orgao` é igual para todas.
            origem = f"<strong>{escape(pub.unidade)}</strong> — " if pub.unidade else ""
            partes.append(f"<li>{origem}{link}<br><small>{corpo}</small></li>")
        partes.append("</ul>")
    partes.append("</body>")
    return "".join(partes)


def enviar(html: str, assunto: str, cfg_email: dict) -> bool:
    """Envia via SMTP com credenciais do ambiente. Nunca propaga falha de envio."""
    logger = configurar_log()
    if not cfg_email.get("habilitado"):
        return False
    destinatarios = cfg_email.get("destinatarios") or []
    if not destinatarios:
        logger.warning("Notificação habilitada, mas sem destinatários configurados.")
        return False

    remetente = os.getenv("RADAR_EMAIL_FROM", "")
    host = os.getenv("RADAR_SMTP_HOST", "")
    porta = int(os.getenv("RADAR_SMTP_PORT", "587"))
    usuario = os.getenv("RADAR_SMTP_USER", "")
    senha = os.getenv("RADAR_SMTP_PASSWORD", "")

    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["From"] = remetente or usuario
    mensagem["To"] = ", ".join(destinatarios)
    mensagem.set_content("Este briefing requer um cliente com suporte a HTML.")
    mensagem.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(host, porta, timeout=30) as servidor:
            servidor.starttls()
            if usuario and senha:
                servidor.login(usuario, senha)
            servidor.sendmail(mensagem["From"], destinatarios, mensagem.as_string())
    except Exception as exc:
        logger.error("Falha ao enviar e-mail: %s", exc)
        return False

    logger.info("E-mail enviado para %s", ", ".join(destinatarios))
    return True
```

- [ ] **Step 4: Acrescentar o subcomando ao CLI**

Em `radar/cli.py`, dentro de `_montar_parser()`, após o parser `consultar`:

```python
    notificar = sub.add_parser("notificar", help="Envia por e-mail o que já foi coletado")
    notificar.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    notificar.add_argument("--data", default=None)
```

Acrescentar a função:

```python
def _notificar(args) -> int:
    import json

    from radar.core.modelos import Resultado
    from radar.notificacao.email import enviar, montar_html

    cfg = Config.carregar(args.config)
    data = parse_data(args.data) if args.data else hoje()
    pasta = cfg.dir_dados / "normalized" / data.isoformat()
    if not pasta.exists():
        print(f"erro: nada coletado em {data.isoformat()}", file=sys.stderr)
        return 2

    resultados = []
    for arquivo in sorted(pasta.glob("*.json")):
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        resultados.append(
            Resultado(
                fonte=dados["fonte"],
                data_publicacao=data,
                coletado_em=hoje_como_datetime(),
                status=Status(dados["status"]),
                escopo=dados["escopo"],
                publicacoes=[],
                avisos=dados["avisos"],
            )
        )
        resultados[-1].publicacoes = _publicacoes_de(dados, data)

    assunto = f"Radar de Diários Oficiais — {data.strftime('%d/%m/%Y')}"
    enviado = enviar(montar_html(resultados), assunto, cfg.email)
    print("e-mail enviado" if enviado else "e-mail não enviado (ver config/log)")
    return 0
```

E os dois auxiliares, no mesmo arquivo:

```python
def hoje_como_datetime():
    from radar.core.datas import agora_utc

    return agora_utc()


def _publicacoes_de(dados: dict, data) -> list:
    from datetime import datetime, timezone

    from radar.core.modelos import Publicacao

    publicacoes = []
    for bruto in dados["publicacoes"]:
        campos = dict(bruto)
        campos["data_publicacao"] = data
        campos["coletado_em"] = datetime.fromisoformat(
            campos["coletado_em"].replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        publicacoes.append(Publicacao(**campos))
    return publicacoes
```

Por fim, em `main()`, antes do `return _consultar(args)`:

```python
        if args.comando == "notificar":
            return _notificar(args)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_notificacao.py tests/test_cli.py -v`
Expected: PASS (11 testes novos + os 10 do CLI seguem passando)

- [ ] **Step 6: Commit**

```bash
git add radar/notificacao/ radar/cli.py tests/test_notificacao.py
git commit -m "feat: notificacao por e-mail unica, com escape de campo raspado"
```

---

### Task 18: Validação contra as fontes reais e README

Última task: confirma que a pipeline funciona contra a rede de verdade e documenta a operação na VPS.

**Files:**
- Create: `README.md`
- Create: `docs/migracao.md`

**Interfaces:**
- Consumes: todas as tasks anteriores
- Produces: documentação. Nenhum símbolo novo.

- [ ] **Step 1: Rodar a suíte completa**

Run: `python -m pytest -v`
Expected: PASS em todos os testes de todas as tasks. Se algum falhar, corrigir antes de seguir.

- [ ] **Step 2: Coleta real de ponta a ponta**

```bash
pip install -e ".[dev]"

# As DUAS formas de invocacao precisam funcionar: o console script (usado no
# README) e o modulo (usado no cron quando o PATH nao tem os scripts do venv).
radar --help
python -m radar.cli --help

python -m radar.cli coletar --config config/config.yaml --data 2026-09-03 --fonte todas
echo "exit=$?"
```

Expected: exit 0 ou 1; duas linhas de status; `data/normalized/2026-09-03/dou.json` e `iofmg.json` criados.

- [ ] **Step 3: Conferir o resultado à mão**

```bash
python - <<'PY'
import json, pathlib
for f in sorted(pathlib.Path("data/normalized/2026-09-03").glob("*.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    print(f"{f.name}: status={d['status']} total={d['total']} avisos={len(d['avisos'])}")
    for p in d["publicacoes"][:2]:
        print(f"   [{p['tipo']}] {p['titulo'][:70]}")
        print(f"   secao={p['secao']} orgao={p['orgao']} texto={len(p['texto'])} chars")
        print(f"   url={p['url'][:100]}")
PY
```

Expected, e a verificar explicitamente:
- `dou.json`: `secao` em {"1","2","3"}, `texto` com mais de 1000 chars na maioria, nenhum mojibake (`Ã`, `ï¿½`)
- `iofmg.json`: `url` contendo `330896` (o id da edição de 03/09), nunca `326074`

- [ ] **Step 4: Confirmar idempotência**

```bash
python -m radar.cli coletar --config config/config.yaml --data 2026-09-03 --fonte todas
python - <<'PY'
import sqlite3
c = sqlite3.connect("data/radar.db")
total, distintos = c.execute("SELECT COUNT(*), COUNT(DISTINCT id) FROM publicacoes").fetchone()
print(f"linhas={total} ids_distintos={distintos}")
assert total == distintos, "UPSERT falhou: há duplicatas"
print("OK: idempotente")
PY
```

Expected: `total == distintos`, e a contagem igual à da primeira execução.

- [ ] **Step 5: Escrever o README**

`README.md`:

````markdown
# Radar de Diários Oficiais

Coleta as publicações de saúde do Diário Oficial da União (Ministério da Saúde)
e do Diário Oficial de Minas Gerais (Secretaria de Estado de Saúde) e entrega
JSON normalizado com texto integral, para consumo por agente.

O juízo sobre o que é relevante **não** está aqui: este pacote entrega dado
limpo e completo. A avaliação de relevância para captação de recursos e a
redação da newsletter são responsabilidade dos agentes a jusante.

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp config/.env.example .env    # só necessário para `radar notificar`
```

Sem Playwright e sem `openssl` no sistema: a listagem do DOU vem de um JSON
embutido na página de busca e o PDF assinado do IOF-MG é desembrulhado em
Python puro.

## Uso

```bash
radar coletar --data 2026-09-04 --fonte todas   # dou | iofmg | todas
radar coletar --forcar                          # ignora o cache de brutos
radar consultar "teto MAC" --desde 2026-06-01   # histórico indexado
```

Sem `--data`, usa hoje no fuso `America/Sao_Paulo`.

## Saída

```
data/
  raw/<data>/<fonte>/       artefatos originais (reprocessar sem rebaixar)
  normalized/<data>/<fonte>.json    ← o que o agente lê
  radar.db                  histórico com FTS5
```

Cada JSON segue o contrato da seção 5 da spec. O campo `status` é o que
distingue os quatro desfechos:

| `status`  | exit | significado                        | o agente deve       |
|-----------|------|------------------------------------|---------------------|
| `ok`      | 0    | coleta completa                    | processar           |
| `vazio`   | 0    | não houve edição (feriado/domingo) | seguir sem alarme   |
| `parcial` | 1    | coletou, mas algo falhou           | processar e alertar |
| `erro`    | 2    | a coleta quebrou                   | **não** publicar    |

Com `--fonte todas`, o exit code é o pior status entre as fontes.

## Integração com o Hermes

```python
import json, subprocess
from pathlib import Path

data = "2026-09-04"
proc = subprocess.run(["radar", "coletar", "--data", data, "--fonte", "todas"])
if proc.returncode == 2:
    raise RuntimeError("coleta falhou; não gerar newsletter")

for arquivo in Path(f"data/normalized/{data}").glob("*.json"):
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    if dados["status"] == "vazio":
        continue
    for pub in dados["publicacoes"]:
        ...  # pub["texto"] traz o inteiro teor
```

## Cron na VPS

```cron
30 9 * * 1-6 cd /opt/radar && .venv/bin/radar coletar --fonte todas >> logs/cron.log 2>&1
```

O DOU e o IOF-MG publicam em dias úteis; sábado tem edição eventual. Domingo
retorna `vazio` com exit 0, o que não polui o log de erro.

## Testes

```bash
python -m pytest
```

Rodam offline, contra HTML e PDF reais em `tests/fixtures/`. Nenhum faz
requisição de rede.

## Configuração

`config/config.yaml` controla órgão, seção e tipos de publicação. Segredos só
por variável de ambiente — nada de e-mail ou chave no código.

## Documentos

- Design: `docs/superpowers/specs/2026-09-04-radar-diarios-oficiais-design.md`
- Migração dos scripts antigos: `docs/migracao.md`
````

- [ ] **Step 6: Escrever o guia de migração**

`docs/migracao.md`:

````markdown
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
   apontam para a edição errada em qualquer data.

## O que não foi portado, de propósito

`classify_sus_relevance()` do `iof_mg_scraper.py` classificava relevância SUS
por palavra-chave. Ficou de fora porque o juízo de relevância passou a ser
responsabilidade do Hermes, que trabalha sobre o texto integral — informação que
a heurística antiga não tinha.

Se um dia for preciso um pré-filtro no código, ele volta como camada opcional
sobre `Publicacao`, nunca como campo do modelo.
````

- [ ] **Step 7: Commit**

```bash
git add README.md docs/migracao.md
git commit -m "docs: README de operacao e guia de migracao dos scripts antigos"
```

---

## Sequenciamento

- **Tasks 1–6:** núcleo. Nada coleta ainda, tudo testável.
- **Task 11:** DOU funcionando ponta a ponta.
- **Task 15:** IOF-MG funcionando ponta a ponta.
- **Task 16:** CLI, ponto de entrada do Hermes.
- **Task 17:** notificação por e-mail (opcional; pode ser adiada sem bloquear o Hermes).
- **Task 18:** validação contra a rede real e documentação.

As Tasks 7–11 (DOU) e 12–15 (IOF-MG) são independentes entre si depois da Task 6
e podem ser executadas em qualquer ordem, ou em paralelo.

## Cobertura dos bugs da spec §12

| bug | task |
|---|---|
| 1 dedup na paginação | 8 |
| 2 `--backtest` / config recriada | 4 (carga única) + 16 (injeção) |
| 3 `idCadernoEdicaoSelecionado` fixo | 12 (leitura) + 15 (uso no link) |
| 4 seção inventada | 7 (leitura de `pubName`) + 10 (mapeamento) |
| 5 retry de erro permanente | 5 |
| 6 `datetime.now(UTC).date()` | 3 |
| 7 logging duplicado | 4 |
| 8 falhas indistinguíveis | 2 (erros) + 5 (HTTP) + 11/15 (status) |
| 9 `except:` pelado | 8 |
| 10 URL crua em `href` | 17 |
| 11 sem idempotência | 6 |
| 12 `max_pages` fixo | 8 |
