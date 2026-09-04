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
