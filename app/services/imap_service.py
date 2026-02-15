"""
Servicio: Lectura de emails bancarios via IMAP
app/services/imap_service.py

Reemplaza gmail_service.py — funciona con CUALQUIER proveedor:
  ✅ Gmail (imap.gmail.com)
  ✅ Google Workspace (imap.gmail.com)
  ✅ Microsoft 365 (outlook.office365.com)
  ✅ cPanel / Hostinger (mail.dominio.org.pe)
  ✅ Zoho (imap.zoho.com)

Dependencias: NINGUNA extra (imaplib y email son built-in de Python)

Configuración por colegio:
  - imap_server: "imap.gmail.com"
  - imap_port: 993
  - imap_user: "tesoreria@colegio.org.pe"
  - imap_password: "app_password_o_contraseña"
"""

import imaplib
import email
from email.header import decode_header
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

TZ_PERU = timezone(timedelta(hours=-5))


class ImapService:
    """Lee emails bancarios de cualquier servidor IMAP."""

    def __init__(
        self,
        server: Optional[str] = None,
        port: int = 993,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.server = server or os.getenv("IMAP_SERVER", "imap.gmail.com")
        self.port = port or int(os.getenv("IMAP_PORT", "993"))
        self.user = user or os.getenv("IMAP_USER", "")
        self.password = password or os.getenv("IMAP_PASSWORD", "")

    def probar_conexion(self) -> dict:
        """Prueba la conexión IMAP. Retorna éxito o error."""
        try:
            conn = imaplib.IMAP4_SSL(self.server, self.port)
            conn.login(self.user, self.password)
            status, mailbox_data = conn.select("INBOX", readonly=True)
            total_msgs = int(mailbox_data[0])
            conn.logout()
            return {
                "success": True,
                "message": f"Conectado a {self.server} — {total_msgs} emails en INBOX",
                "total_emails": total_msgs,
            }
        except imaplib.IMAP4.error as e:
            return {"success": False, "message": f"Error de autenticación: {e}"}
        except Exception as e:
            return {"success": False, "message": f"Error de conexión: {e}"}

    def leer_notificaciones_bancarias(
        self,
        desde: Optional[datetime] = None,
        max_results: int = 50,
    ) -> list[dict]:
        """
        Lee emails bancarios del INBOX.

        Args:
            desde: Fecha desde la cual buscar (default: últimas 2 horas)
            max_results: Máximo de emails a procesar

        Returns:
            Lista de dicts con: message_id, from_addr, subject, body, date
        """
        if not self.user or not self.password:
            logger.warning("IMAP no configurado: faltan credenciales")
            return []

        if desde is None:
            desde = datetime.now(TZ_PERU) - timedelta(hours=2)

        # Remitentes bancarios conocidos
        remitentes_banco = [
            "bancadigital@scotiabank.com.pe",
            "servicioalcliente@netinterbank.com.pe",
            "notificaciones@bcp.com.pe",
            "notificacionesbcp@bcp.com.pe",
            "info@bbva.pe",
            "notificaciones@bbva.pe",
            "alertas@continental.com.pe",
        ]

        emails_encontrados = []

        try:
            conn = imaplib.IMAP4_SSL(self.server, self.port)
            conn.login(self.user, self.password)
            conn.select("INBOX", readonly=True)  # Solo lectura

            # Buscar por fecha (IMAP usa formato DD-Mon-YYYY)
            fecha_imap = desde.strftime("%d-%b-%Y")
            status, msg_ids = conn.search(None, f'(SINCE {fecha_imap})')

            if status != "OK" or not msg_ids[0]:
                conn.logout()
                return []

            # Procesar de más reciente a más antiguo
            id_list = msg_ids[0].split()
            id_list.reverse()
            id_list = id_list[:max_results]

            for msg_id in id_list:
                try:
                    status, msg_data = conn.fetch(msg_id, "(RFC822)")
                    if status != "OK":
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    # Obtener remitente
                    from_addr = self._extract_email_address(msg.get("From", ""))

                    # Filtrar: solo emails de bancos
                    if not any(banco in from_addr.lower() for banco in remitentes_banco):
                        continue

                    # Obtener fecha
                    date_str = msg.get("Date", "")
                    msg_date = email.utils.parsedate_to_datetime(date_str) if date_str else None

                    # Filtrar por fecha exacta (IMAP SINCE es por día, no hora)
                    if msg_date and desde.tzinfo:
                        if msg_date.tzinfo is None:
                            msg_date = msg_date.replace(tzinfo=timezone.utc)
                        if msg_date < desde:
                            continue

                    # Obtener subject
                    subject = self._decode_header(msg.get("Subject", ""))

                    # Obtener body (texto plano o HTML)
                    body = self._extract_body(msg)

                    # Message-ID único
                    message_id = msg.get("Message-ID", f"imap-{msg_id.decode()}")

                    emails_encontrados.append({
                        "message_id": message_id,
                        "from_addr": from_addr,
                        "subject": subject,
                        "body": body,
                        "date": msg_date,
                    })

                except Exception as e:
                    logger.warning(f"Error procesando email {msg_id}: {e}")
                    continue

            conn.logout()

        except imaplib.IMAP4.error as e:
            logger.error(f"Error IMAP autenticación: {e}")
        except Exception as e:
            logger.error(f"Error IMAP conexión: {e}", exc_info=True)

        logger.info(
            f"IMAP: {len(emails_encontrados)} emails bancarios encontrados "
            f"(de {len(id_list) if 'id_list' in dir() else '?'} procesados)"
        )
        return emails_encontrados

    def _extract_email_address(self, from_field: str) -> str:
        """Extrae solo el email de 'Nombre <email@domain.com>'."""
        if "<" in from_field and ">" in from_field:
            return from_field.split("<")[1].split(">")[0].strip()
        return from_field.strip()

    def _decode_header(self, header_value: str) -> str:
        """Decodifica header con posibles encodings (UTF-8, ISO-8859-1, etc.)."""
        if not header_value:
            return ""
        decoded_parts = decode_header(header_value)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(part)
        return " ".join(result)

    def _extract_body(self, msg) -> str:
        """Extrae el cuerpo del email (prefiere texto plano, fallback HTML)."""
        body_text = ""
        body_html = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Saltar adjuntos
                if "attachment" in content_disposition:
                    continue

                try:
                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue
                    charset = part.get_content_charset() or "utf-8"
                    decoded = payload.decode(charset, errors="replace")

                    if content_type == "text/plain":
                        body_text = decoded
                    elif content_type == "text/html":
                        body_html = decoded
                except Exception:
                    continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace") if payload else ""

                if msg.get_content_type() == "text/plain":
                    body_text = decoded
                else:
                    body_html = decoded
            except Exception:
                pass

        # Preferir texto plano; si no hay, usar HTML
        return body_text if body_text else body_html