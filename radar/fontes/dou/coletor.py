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
            # `vazio` significa "não houve edição, siga sem alarme". Com aviso na
            # mão, isso é mentira: houve algo a relatar, e o status é `parcial`.
            status = Status.PARCIAL if avisos else Status.VAZIO
            self.logger.info(
                "DOU %s: nenhuma publicação para %s (%s)", data, self.cfg.orgao, status
            )
            return Resultado(
                fonte=self.nome, data_publicacao=data, coletado_em=quando,
                status=status, escopo=escopo, publicacoes=[], avisos=avisos,
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
