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
        # A chave é `orgao`, não `secao`: no IOF-MG o que a API chama de "seção"
        # é a divisão por órgão (spec §4), e toda `Publicacao` daqui tem
        # `secao: null`. `ConfigIOFMG.secao` é config do usuário e não muda aqui.
        escopo = {"caderno": self.cfg.caderno, "orgao": self.cfg.secao}

        def sem_nada(status: Status, avisos: list[str]) -> Resultado:
            return Resultado(
                fonte=self.nome, data_publicacao=data, coletado_em=quando,
                status=status, escopo=escopo, publicacoes=[], avisos=avisos,
            )

        # Dia sem edição é o único `vazio` legítimo: nada a relatar além do
        # próprio status, portanto sem aviso — `vazio` com aviso seria "não
        # houve edição" carregando o relato de uma falha.
        try:
            dados = self._obter_dados(data, forcar)
        except SemEdicao as exc:
            self.logger.info("IOF-MG %s: %s", data, exc)
            return sem_nada(Status.VAZIO, [])

        # Já daqui para baixo há edição publicada. Não achar o caderno ou o
        # órgão dentro dela pode ser dia sem publicação da SES, mas também pode
        # ser renomeação no índice da API — que, reportada como `vazio`, seria
        # coleta quebrada passando por domingo, todo dia, para sempre.
        try:
            caderno = api.caderno_principal(dados, self.cfg.caderno)
            arquivo = dados.get("arquivoCadernoPrincipal", {})
            total_paginas = int(arquivo.get("totalPaginas", 0))
            inicio, fim = pdf_mod.intervalo_da_secao(caderno, self.cfg.secao, total_paginas)
        except SemEdicao as exc:
            self.logger.warning("IOF-MG %s: %s", data, exc)
            return sem_nada(Status.PARCIAL, [str(exc)])

        conteudo = self._obter_pdf(data, dados, forcar)
        paginas = pdf_mod.texto_das_paginas(conteudo, inicio, fim)
        avisos: list[str] = []

        # As duas pontas do intervalo são compartilhadas: a primeira página traz
        # o fim do órgão anterior e a última, o início do seguinte. Cortar as
        # duas antes de segmentar, senão ato alheio entra com procedência falsa.
        # `truncar_*` já tem um fallback seguro para cabeçalho não encontrado:
        # não corta nada, para não mutilar conteúdo em silêncio. Mas "não
        # cortar" sem avisar saía `ok`, exit 0 — possivelmente com atos de
        # outro órgão rotulados como do alvo. Checar aqui, antes de cortar, é
        # o que transforma esse fallback silencioso em `parcial`.
        if paginas and pdf_mod.posicao_do_cabecalho(paginas[0][1], self.cfg.secao) is None:
            aviso = (
                f"Cabeçalho de {self.cfg.secao!r} não encontrado na primeira "
                f"página (p. {inicio}); a fronteira com o órgão anterior pode "
                f"não ter sido cortada."
            )
            self.logger.warning("IOF-MG %s: %s", data, aviso)
            avisos.append(aviso)
        paginas = pdf_mod.truncar_antes_da_secao(paginas, self.cfg.secao)

        proxima = pdf_mod.proxima_secao(caderno, self.cfg.secao)
        if proxima and paginas and pdf_mod.posicao_do_cabecalho(paginas[-1][1], proxima) is None:
            aviso = (
                f"Cabeçalho de {proxima!r} não encontrado na última página "
                f"(p. {fim}); a fronteira com o órgão seguinte pode não ter "
                f"sido cortada."
            )
            self.logger.warning("IOF-MG %s: %s", data, aviso)
            avisos.append(aviso)
        paginas = pdf_mod.truncar_na_proxima_secao(paginas, proxima)

        brutos = segmenta.segmentar(paginas, self.cfg.tipos_publicacao)

        if not brutos:
            # Órgão localizado e nada segmentado é quebra de extração, não
            # ausência de edição: `parcial`, para o agente processar e alertar.
            aviso = f"Órgão {self.cfg.secao!r} localizado em pp. {inicio}-{fim}, mas nada segmentado."
            self.logger.warning("IOF-MG %s: %s", data, aviso)
            avisos.append(aviso)
            return sem_nada(Status.PARCIAL, avisos)

        id_caderno = caderno.get("id")
        publicacoes = [
            normaliza.normalizar(b, data, quando, id_caderno, self.cfg.secao) for b in brutos
        ]
        self.logger.info("IOF-MG %s: %d publicações em pp. %d-%d", data, len(publicacoes), inicio, fim)
        status = Status.PARCIAL if avisos else Status.OK
        return Resultado(
            fonte=self.nome, data_publicacao=data, coletado_em=quando,
            status=status, escopo=escopo, publicacoes=publicacoes, avisos=avisos,
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
