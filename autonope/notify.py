"""Send alerts via Discord, Slack, Email, Apprise, Pushover."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Callable, List

import requests
from apprise import Apprise

from autonope.config import NotifyChannel


class Notifier:
    """Aggregate multiple notification back-ends."""

    def __init__(self, channels: List[NotifyChannel]):
        self.senders: List[Callable[[str, str], None]] = []
        for ch in channels:
            t = ch.type.lower()
            p = ch.params

            if t == "discord":
                self.senders.append(
                    lambda title, body, u=p["url"]: requests.post(
                        u, json={"content": f"**{title}**\n{body}"}, timeout=10
                    )
                )

            elif t == "slack":
                self.senders.append(
                    lambda title, body, u=p["url"]: requests.post(
                        u, json={"text": f"*{title}*\n{body}"}, timeout=10
                    )
                )

            elif t == "email":

                def _email(title: str, body: str, cfg=p) -> None:
                    msg = EmailMessage()
                    msg["From"] = cfg["username"]
                    msg["To"] = cfg["to"]
                    msg["Subject"] = title
                    msg.set_content(body)
                    with smtplib.SMTP(cfg["smtp_host"], cfg["port"]) as s:
                        s.starttls()
                        s.login(cfg["username"], cfg["password"])
                        s.send_message(msg)

                self.senders.append(_email)

            elif t == "apprise":
                a = Apprise()
                a.add(p["url"])
                self.senders.append(
                    lambda title, body, a=a: a.notify(title=title, body=body)
                )

            elif t == "pushover":

                def _pushover(title: str, body: str, cfg=p) -> None:
                    requests.post(
                        "https://api.pushover.net/1/messages.json",
                        data={
                            "token": cfg["token"],
                            "user": cfg["user"],
                            "title": title,
                            "message": body,
                        },
                        timeout=10,
                    )

                self.senders.append(_pushover)

    # ------------------------------------------------------------------ #

    def send(self, title: str, body: str) -> None:  # noqa: D401
        for fn in self.senders:
            try:
                fn(title, body)
            except Exception:  # noqa: BLE001
                pass
