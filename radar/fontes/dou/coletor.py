"""Coleta do DOU: uma busca por órgão, recorte de escopo, depois inteiro teor."""

from __future__ import annotations

import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from radar.core.config import ConfigDOU
from radar.core.datas import agora_utc
from radar.core.erros import ErroRadar, FonteIndisponivel, Status
from radar.core.http import obter_bytes
from radar.core.log import configurar_log
from radar.core.modelos import Resultado
from radar.core.storage import Storage
from radar.fontes import escopo as regra_escopo
from radar.fontes.dou import busca, normaliza
from radar.fontes.dou.texto import TextoDOU, extrair_texto


def _apelido(orgao: str) -> str:
    """Nome de arquivo estável para o bruto de cada órgão.

    Sem ele os órgãos dividiriam `busca-p1.html` e o segundo leria, do cache, a
    listagem do primeiro — coleta silenciosamente errada no reprocessamento.
    """
    sem_acento = unicodedata.normalize("NFKD", orgao).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-") or "orgao"


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
        orgaos = list(self.cfg.orgaos or [])
        if not orgaos:
            # Coletar zero órgão sairia `vazio`, exit 0, todo dia — falha total
            # em silêncio, que é o que o contrato de status existe para impedir.
            raise ValueError("fontes.dou.orgaos está vazio: nenhum órgão a coletar")

        escopo = {
            "orgaos": orgaos,
            "subunidades_extra": list(self.cfg.subunidades_extra),
            # O consumidor precisa saber, so lendo o JSON, se `texto` e o
            # inteiro teor ou o resumo truncado da listagem.
            "texto_integral": self.cfg.baixar_texto_integral,
        }

        encontrados, avisos, falharam = self._buscar_orgaos(data, orgaos, forcar)

        # Todos os órgãos fora do ar não é "dia sem edição": é a fonte
        # indisponível, e isso tem de chegar ao agente como `erro` (exit 2).
        if len(falharam) == len(orgaos):
            raise FonteIndisponivel(
                f"Busca do DOU falhou em todos os órgãos: {', '.join(falharam)}"
            )

        # O recorte usa a hierarquia do próprio item, ANTES de buscar o inteiro
        # teor: filtrar depois custaria uma requisição por ato descartado — e a
        # Presidência traz o Executivo inteiro para se ficar com a Casa Civil.
        itens = [i for i in encontrados if self._no_escopo(i)]

        if not itens:
            if encontrados:
                # Achou e descartou tudo pode ser hierarquia renomeada na fonte;
                # dizer `vazio` calaria o filtro quebrado para sempre.
                aviso = (
                    f"{len(encontrados)} publicações encontradas e nenhuma no escopo "
                    f"({', '.join(orgaos)}); o filtro de órgão pode ter quebrado."
                )
                self.logger.warning("DOU %s: %s", data, aviso)
                avisos.append(aviso)
            # `vazio` significa "não houve edição, siga sem alarme". Com aviso na
            # mão, isso é mentira: houve algo a relatar, e o status é `parcial`.
            status = Status.PARCIAL if avisos else Status.VAZIO
            self.logger.info(
                "DOU %s: nenhuma publicação para %s (%s)", data, ", ".join(orgaos), status
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
        self.logger.info(
            "DOU %s: %d publicações de %d encontradas em %d órgão(s) (%s)",
            data, len(publicacoes), len(encontrados), len(orgaos), status,
        )
        return Resultado(
            fonte=self.nome, data_publicacao=data, coletado_em=quando,
            status=status, escopo=escopo, publicacoes=publicacoes, avisos=avisos,
        )

    def _no_escopo(self, item: dict) -> bool:
        """Aplica a regra compartilhada com o INLABS à hierarquia do item.

        A busca já vem recortada por `orgPrin`, mas o portal devolve a
        Presidência inteira sob esse órgão: é o 2º nível que separa a Casa Civil
        da Secretaria-Geral.
        """
        return regra_escopo.em_escopo(
            regra_escopo.niveis_de(item.get("hierarchyStr")),
            self.cfg.orgaos or [],
            self.cfg.subunidades_extra,
        )

    def _buscar_orgaos(
        self, data: date, orgaos: list[str], forcar: bool
    ) -> tuple[list[dict], list[str], list[str]]:
        """Uma busca por órgão, acumulando itens únicos por `urlTitle`.

        Um órgão que não publicou no dia não é aviso — é normal a Fazenda não
        ter ato nenhum. Um órgão que caiu é: o dia segue com os outros, mas
        degradado a `parcial` e com o nome de quem faltou.
        """
        encontrados: dict[str, dict] = {}
        avisos: list[str] = []
        falharam: list[str] = []

        for orgao in orgaos:
            def pagina(numero: int, cursor, orgao=orgao) -> str:
                url = busca.montar_url_busca(orgao, data, self.cfg.delta, numero, cursor)
                nome = f"busca-{_apelido(orgao)}-p{numero}.html"
                return busca.decodificar_busca(self._buscar_bruto(data, nome, url, forcar))

            try:
                itens, avisos_do_orgao = busca.percorrer_paginas(pagina, self.cfg.delta)
            except ErroRadar as exc:
                falharam.append(orgao)
                aviso = f"Busca do órgão {orgao} falhou: {exc}"
                self.logger.warning("DOU %s: %s", data, aviso)
                avisos.append(aviso)
                continue

            avisos.extend(avisos_do_orgao)
            novos = 0
            for item in itens:
                chave = item.get("urlTitle") or str(item.get("classPK") or "")
                if chave and chave not in encontrados:
                    encontrados[chave] = item
                    novos += 1
            self.logger.info(
                "DOU %s: %s trouxe %d publicações (%d inéditas)",
                data, orgao, len(itens), novos,
            )

        return list(encontrados.values()), avisos, falharam

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
