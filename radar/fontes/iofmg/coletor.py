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
        # As duas pontas do intervalo são compartilhadas: a primeira página traz
        # o fim do órgão anterior e a última, o início do seguinte. Cortar as
        # duas antes de segmentar, senão ato alheio entra com procedência falsa.
        paginas = pdf_mod.truncar_antes_da_secao(paginas, self.cfg.secao)
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
