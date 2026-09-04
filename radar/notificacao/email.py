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
        if resultado.avisos:
            itens = "".join(f"<li>{escape(a)}</li>" for a in resultado.avisos)
            partes.append(f'<ul style="color:#8a6d3b">{itens}</ul>')
        if resultado.status == Status.VAZIO or not resultado.publicacoes:
            partes.append("<p><em>Dia sem publicações para o escopo monitorado.</em></p>")
            continue
        partes.append(f"<p>{len(resultado.publicacoes)} publicações.</p><ul>")
        for pub in resultado.publicacoes:
            titulo = escape(pub.titulo)
            orgao = escape(pub.orgao)
            # `quote=True` é o que impede a URL raspada de escapar do atributo.
            destino = escape(pub.url or "", quote=True)
            corpo = escape((pub.ementa or pub.texto)[:220])
            link = f'<a href="{destino}">{titulo}</a>' if destino else titulo
            partes.append(f"<li><strong>{orgao}</strong> — {link}<br><small>{corpo}</small></li>")
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
