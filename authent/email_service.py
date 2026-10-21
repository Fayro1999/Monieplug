
import base64
import logging
import mimetypes
import os

import requests

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


class ZeptoMailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        api_key = getattr(settings, "ZEPTOMAIL_API_KEY", "")

        if not api_key:
            raise RuntimeError(
                "ZEPTOMAIL_API_KEY is not configured."
            )

        sent_count = 0

        for message in email_messages:
            try:
                sender = (
                    message.from_email
                    or settings.DEFAULT_FROM_EMAIL
                )

                payload = {
                    "from": {"address": sender},
                    "to": [
                        {"email_address": {"address": email}}
                        for email in message.to
                    ],
                    "subject": message.subject or "",
                }

                # Plain-text or HTML message body.
                if message.content_subtype == "html":
                    payload["htmlbody"] = message.body
                else:
                    payload["textbody"] = message.body

                # Add HTML alternatives safely.
                for alternative in getattr(
                    message, "alternatives", []
                ):
                    if hasattr(alternative, "content"):
                        content = alternative.content
                        mimetype = alternative.mimetype
                    else:
                        content, mimetype = alternative

                    if mimetype == "text/html":
                        payload["htmlbody"] = content

                if message.cc:
                    payload["cc"] = [
                        {"email_address": {"address": email}}
                        for email in message.cc
                    ]

                if message.bcc:
                    payload["bcc"] = [
                        {"email_address": {"address": email}}
                        for email in message.bcc
                    ]

                # Convert Django file attachments to Base64.
                attachments = []

                for attachment in getattr(
                    message, "attachments", []
                ):
                    if isinstance(attachment, tuple):
                        filename = attachment[0]
                        content = attachment[1]
                        mime_type = (
                            attachment[2]
                            if len(attachment) > 2
                            else None
                        )
                    else:
                        filename = attachment.get_filename()
                        content = attachment.get_payload(
                            decode=True
                        )
                        mime_type = attachment.get_content_type()

                    if not filename or content is None:
                        continue

                    if isinstance(content, str):
                        content = content.encode("utf-8")

                    if not mime_type:
                        mime_type = (
                            mimetypes.guess_type(filename)[0]
                            or "application/octet-stream"
                        )

                    attachments.append({
                        "name": os.path.basename(filename),
                        "mime_type": mime_type,
                        "content": base64.b64encode(
                            content
                        ).decode("ascii"),
                    })

                if attachments:
                    payload["attachments"] = attachments

                # Send request to ZeptoMail.
                response = requests.post(
                    getattr(
                        settings,
                        "ZEPTOMAIL_API_URL",
                        "https://cpaas.zoho.com/v1.1/email",
                    ),
                    headers={
                        "Authorization": (
                            f"Zoho-enczapikey {api_key}"
                        ),
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=30,
                )

                if not response.ok:
                    logger.error(
                        "ZeptoMail API error: status=%s, response=%s",
                        response.status_code,
                        response.text[:2000],
                    )
                    raise RuntimeError(
                        f"ZeptoMail returned HTTP "
                        f"{response.status_code}: "
                        f"{response.text[:1000]}"
                    )

                sent_count += 1

            except Exception:
                logger.exception(
                    "Failed to send email through ZeptoMail."
                )

                if not self.fail_silently:
                    raise

        return sent_count
