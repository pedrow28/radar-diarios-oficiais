"""Coleta do INLABS: zip por seção → artigos → recorte por órgão → publicações."""

from __future__ import annotations

import os
from datetime import date

from radar.core.config import ConfigINLABS
from radar.core.datas import agora_utc
from radar.core.erros import FonteIndisponivel, Status
from radar.core.log import configurar_log
from radar.core.modelos import Resultado
from radar.core.storage import Storage
from radar.fontes.inlabs import normaliza
from radar.fontes.inlabs.sessao import abrir_sessao, baixar_zip
from radar.fontes.inlabs.xml import Artigo, listar_artigos

# A ANVISA às vezes é 1º nível de `artCategory` e às vezes vem sob o
# "Ministério da Saúde" — o mesmo órgão, em duas árvores. Casar em qualquer
# nível é o que impede a RDC de sumir conforme o dia.
_ANVISA = "Agência Nacional de Vigilância Sanitária"

# A "Presidência da República" assina boa parte do diário. Sem exigir a
# subunidade, incluí-la em `orgaos` faria o recorte deixar de recortar.
_PRESIDENCIA = "Presidência da República"


def em_escopo(a: Artigo, cfg: ConfigINLABS) -> bool:
    """Diz se o artigo é de um órgão que se quer acompanhar."""
    niveis = [n.strip() for n in a.art_category.split("/") if n.strip()]
    if _ANVISA in cfg.orgaos and _ANVISA in niveis:
        return True
    primeiro = niveis[0] if niveis else ""
    if primeiro not in cfg.orgaos:
        return False
    if primeiro == _PRESIDENCIA:
        return len(niveis) > 1 and niveis[1] in cfg.subunidades_extra
    return True


class FonteINLABS:
    nome = "inlabs"

    def __init__(self, cfg: ConfigINLABS, storage: Storage, sessao) -> None:
        self.cfg = cfg
        self.storage = storage
        self.sessao = sessao
        self.logger = configurar_log()
        self._autenticada = False

    def coletar(self, data: date, forcar: bool = False) -> Resultado:
        quando = agora_utc()
        escopo = {"secoes": self.cfg.secoes, "orgaos": self.cfg.orgaos}

        def sem_nada(status: Status, avisos: list[str]) -> Resultado:
            return Resultado(
                fonte=self.nome, data_publicacao=data, coletado_em=quando,
                status=status, escopo=escopo, publicacoes=[], avisos=avisos,
            )

        zips: dict[str, bytes] = {}
        faltantes: list[str] = []
        for secao in self.cfg.secoes:
            bruto = self._obter_zip(data, secao, forcar)
            if bruto is None:
                faltantes.append(secao)
            else:
                zips[secao] = bruto

        # Nenhuma seção com arquivo é dia sem edição — o único `vazio`
        # legítimo. Sem aviso: `vazio` com aviso seria "não houve edição"
        # carregando o relato de uma falha, e o agente nunca alertaria ninguém.
        if not zips:
            self.logger.info("INLABS %s: nenhuma seção publicada", data)
            return sem_nada(Status.VAZIO, [])

        avisos = [f"seção {secao} sem arquivo" for secao in faltantes]

        artigos: list[Artigo] = []
        for secao, bruto in zips.items():
            lidos, avisos_xml = listar_artigos(bruto)
            avisos.extend(avisos_xml)
            artigos.extend(lidos)

        selecionados = self._selecionar(artigos)
        if not selecionados:
            # Edição publicada e nada do escopo pode ser dia sem ato dos órgãos
            # acompanhados, mas também pode ser renomeação de `artCategory` na
            # fonte — que, reportada como `vazio`, seria filtro quebrado
            # passando por domingo, todo dia, para sempre.
            aviso = (
                "nenhum artigo dos órgãos configurados na(s) seção(ões) "
                f"{', '.join(zips)}"
            )
            self.logger.warning("INLABS %s: %s", data, aviso)
            avisos.append(aviso)
            return sem_nada(Status.PARCIAL, avisos)

        publicacoes = [normaliza.normalizar(a, data, quando) for a in selecionados]
        self.logger.info(
            "INLABS %s: %d publicações em %s", data, len(publicacoes), ", ".join(zips)
        )
        return Resultado(
            fonte=self.nome, data_publicacao=data, coletado_em=quando,
            status=Status.PARCIAL if avisos else Status.OK, escopo=escopo,
            publicacoes=publicacoes, avisos=avisos,
        )

    def _selecionar(self, artigos: list[Artigo]) -> list[Artigo]:
        """Filtra pelo escopo e tira as repetições, mantendo a primeira.

        A mesma matéria sai na seção comum e na extra do dia; contá-la duas
        vezes inflaria o volume do dia. Só desempata quem tem `idMateria`:
        sem ele, artigos distintos colapsariam num só.
        """
        selecionados: list[Artigo] = []
        vistos: set[str] = set()
        for artigo in artigos:
            if not em_escopo(artigo, self.cfg):
                continue
            if artigo.id_materia and artigo.id_materia in vistos:
                continue
            vistos.add(artigo.id_materia)
            selecionados.append(artigo)
        return selecionados

    def _obter_zip(self, data: date, secao: str, forcar: bool) -> bytes | None:
        nome = f"{data.isoformat()}-{secao}.zip"
        if not forcar:
            guardado = self.storage.ler_raw(data, self.nome, nome)
            if guardado is not None:
                return guardado

        bruto = baixar_zip(self._autenticar(), data, secao)
        if bruto is not None:
            self.storage.salvar_raw(data, self.nome, nome, bruto)
        return bruto

    def _autenticar(self):
        """Login preguiçoso: só quando alguma seção precisa mesmo ser baixada.

        Reprocessar um dia já em cache não pode exigir conta no serviço.
        """
        if self._autenticada:
            return self.sessao
        email = os.environ.get("INLABS_EMAIL")
        senha = os.environ.get("INLABS_SENHA")
        if not email or not senha:
            raise FonteIndisponivel("INLABS_EMAIL/INLABS_SENHA não definidos")
        self.sessao = abrir_sessao(email, senha, self.sessao)
        self._autenticada = True
        return self.sessao
