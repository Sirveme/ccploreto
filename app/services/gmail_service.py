"""
Servicio: Lectura de correos Gmail
app/services/gmail_service.py

Lee emails de notificación bancaria via Gmail API (OAuth2).
Filtra por remitentes conocidos (bancos) y los envía al parser.

Requisitos:
    pip install google-auth google-auth-oauthlib google-api-python-client

Setup OAuth2:
    1. Ir a https://console.cloud.google.com
    2. Crear proyecto o seleccionar existente
    3. Habilitar Gmail API
    4. Crear credenciales OAuth2 (tipo: Aplicación web)
    5. Redirect URI: https://ccploreto.metraes.com/api/gmail/callback
    6. Descargar credentials.json
    7. Guardar client_id y client_secret en env vars
"""

import os
import json
import base64
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

TZ_PERU = timezone(timedelta(hours=-5))

# Remitentes bancarios que nos interesan
BANK_SENDERS = [
    "bancadigital@scotiabank.com.pe",
    "servicioalcliente@netinterbank.com.pe",
    "notificaciones@bcp.com.pe",
    "noreply@bcp.com.pe",
    "bbva.pe",
    "bbvacontinental.pe",
]


class GmailService:
    """Servicio para leer emails de Gmail via API."""

    def __init__(self, credentials_json: str = None, token_json: str = None):
        """
        Args:
            credentials_json: Path o contenido JSON de credenciales OAuth2
            token_json: Path o contenido JSON del token de acceso
        """
        self.credentials_json = credentials_json or os.getenv("GMAIL_CREDENTIALS")
        self.token_json = token_json or os.getenv("GMAIL_TOKEN")
        self.service = None

    def _get_service(self):
        """Inicializa el servicio de Gmail API."""
        if self.service:
            return self.service

        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            creds = None

            # Cargar token existente
            if self.token_json:
                if os.path.isfile(self.token_json):
                    creds = Credentials.from_authorized_user_file(
                        self.token_json,
                        scopes=['https://www.googleapis.com/auth/gmail.readonly']
                    )
                else:
                    # Token como JSON string (desde env var o BD)
                    token_data = json.loads(self.token_json)
                    creds = Credentials.from_authorized_user_info(
                        token_data,
                        scopes=['https://www.googleapis.com/auth/gmail.readonly']
                    )

            # Refrescar si expiró
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Guardar token actualizado
                if os.path.isfile(self.token_json):
                    with open(self.token_json, 'w') as f:
                        f.write(creds.to_json())

            if not creds or not creds.valid:
                logger.error("Gmail: Token no válido. Requiere re-autorización.")
                return None

            self.service = build('gmail', 'v1', credentials=creds)
            return self.service

        except Exception as e:
            logger.error(f"Error inicializando Gmail API: {e}")
            return None

    def obtener_url_autorizacion(self) -> Optional[str]:
        """
        Genera URL para que el usuario autorice acceso a Gmail.
        Usar en el flujo de setup inicial.
        """
        try:
            from google_auth_oauthlib.flow import Flow

            if os.path.isfile(self.credentials_json):
                flow = Flow.from_client_secrets_file(
                    self.credentials_json,
                    scopes=['https://www.googleapis.com/auth/gmail.readonly'],
                    redirect_uri=os.getenv("GMAIL_REDIRECT_URI",
                                           "https://ccploreto.metraes.com/api/gmail/callback")
                )
            else:
                client_config = json.loads(self.credentials_json)
                flow = Flow.from_client_config(
                    client_config,
                    scopes=['https://www.googleapis.com/auth/gmail.readonly'],
                    redirect_uri=os.getenv("GMAIL_REDIRECT_URI",
                                           "https://ccploreto.metraes.com/api/gmail/callback")
                )

            auth_url, _ = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent'
            )
            return auth_url

        except Exception as e:
            logger.error(f"Error generando URL de autorización: {e}")
            return None

    def completar_autorizacion(self, auth_code: str) -> Optional[str]:
        """
        Completa el flujo OAuth2 con el código de autorización.
        Retorna el token JSON para guardar.
        """
        try:
            from google_auth_oauthlib.flow import Flow

            if os.path.isfile(self.credentials_json):
                flow = Flow.from_client_secrets_file(
                    self.credentials_json,
                    scopes=['https://www.googleapis.com/auth/gmail.readonly'],
                    redirect_uri=os.getenv("GMAIL_REDIRECT_URI",
                                           "https://ccploreto.metraes.com/api/gmail/callback")
                )
            else:
                client_config = json.loads(self.credentials_json)
                flow = Flow.from_client_config(
                    client_config,
                    scopes=['https://www.googleapis.com/auth/gmail.readonly'],
                    redirect_uri=os.getenv("GMAIL_REDIRECT_URI",
                                           "https://ccploreto.metraes.com/api/gmail/callback")
                )

            flow.fetch_token(code=auth_code)
            creds = flow.credentials

            token_json = creds.to_json()
            logger.info("Gmail: Autorización completada exitosamente")
            return token_json

        except Exception as e:
            logger.error(f"Error completando autorización Gmail: {e}")
            return None

    def leer_notificaciones_bancarias(
        self,
        desde: datetime = None,
        max_results: int = 50,
    ) -> List[Dict]:
        """
        Lee emails de notificación bancaria desde Gmail.

        Args:
            desde: Fecha desde la cual buscar (default: últimas 24 horas)
            max_results: Máximo de emails a leer

        Returns:
            Lista de dicts con: message_id, from, subject, date, body
        """
        service = self._get_service()
        if not service:
            return []

        if desde is None:
            desde = datetime.now(TZ_PERU) - timedelta(hours=24)

        # Construir query de Gmail
        # Buscar emails de remitentes bancarios
        senders_query = " OR ".join([f"from:{s}" for s in BANK_SENDERS])
        after_epoch = int(desde.timestamp())
        query = f"({senders_query}) after:{after_epoch}"

        try:
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results,
            ).execute()

            messages = results.get('messages', [])
            if not messages:
                logger.info(f"Gmail: No se encontraron emails bancarios desde {desde}")
                return []

            emails = []
            for msg_ref in messages:
                try:
                    msg = service.users().messages().get(
                        userId='me',
                        id=msg_ref['id'],
                        format='full',
                    ).execute()

                    email_data = self._extraer_datos_email(msg)
                    if email_data:
                        emails.append(email_data)
                except Exception as e:
                    logger.warning(f"Error leyendo email {msg_ref['id']}: {e}")
                    continue

            logger.info(f"Gmail: {len(emails)} notificaciones bancarias encontradas")
            return emails

        except Exception as e:
            logger.error(f"Error leyendo Gmail: {e}")
            return []

    def _extraer_datos_email(self, message: dict) -> Optional[Dict]:
        """Extrae datos relevantes de un mensaje de Gmail."""
        try:
            headers = {h['name'].lower(): h['value']
                       for h in message.get('payload', {}).get('headers', [])}

            email_from = headers.get('from', '')
            subject = headers.get('subject', '')
            date_str = headers.get('date', '')

            # Extraer body
            body = self._extraer_body(message.get('payload', {}))

            # Parsear fecha del header
            email_date = None
            try:
                from email.utils import parsedate_to_datetime
                email_date = parsedate_to_datetime(date_str)
            except Exception:
                pass

            return {
                "message_id": message['id'],
                "from": email_from,
                "subject": subject,
                "date": email_date,
                "body": body,
                "snippet": message.get('snippet', ''),
            }
        except Exception as e:
            logger.warning(f"Error extrayendo datos del email: {e}")
            return None

    def _extraer_body(self, payload: dict) -> str:
        """Extrae el cuerpo de texto del email (text/plain o text/html)."""
        body = ""

        if 'body' in payload and payload['body'].get('data'):
            body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='replace')

        if not body and 'parts' in payload:
            for part in payload['parts']:
                mime_type = part.get('mimeType', '')
                if mime_type == 'text/plain' and part.get('body', {}).get('data'):
                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='replace')
                    break
                elif mime_type == 'text/html' and part.get('body', {}).get('data'):
                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='replace')

                # Recursivo para multipart
                if 'parts' in part:
                    nested = self._extraer_body(part)
                    if nested:
                        body = nested

        return body