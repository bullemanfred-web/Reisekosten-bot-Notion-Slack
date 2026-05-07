#!/usr/bin/env python3
"""
Message Templates Module
Slack Message Formatting mit Block Kit
"""

from typing import Dict, Any, List


def build_new_request_channel_message(
    antrag_name: str,
    vorgangs_id: str,
    email: str,
    betrag: float,
    ziel: str = "N/A",
    reisedatum: str = "N/A",
    page_id: str = ""
) -> Dict[str, Any]:
    """
    Erstellt formatierte Channel-Message für neuen Antrag
    Nutzt Slack Block Kit für besseres Layout
    """

    notion_link = f"https://www.notion.so/{page_id}" if page_id else "#"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "📝 *Neuer Reisekostenantrag*"
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*👤 Antragsteller*\n{antrag_name}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*💰 Betrag*\n€{betrag:,.2f}" if isinstance(betrag, (int, float)) else f"*💰 Betrag*\n€{betrag}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*📍 Ziel*\n{ziel}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*📅 Reisedatum*\n{reisedatum}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*📄 Vorgangs-ID*\n{vorgangs_id}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*✉️ E-Mail*\n{email}"
                }
            ]
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<{notion_link}|🔗 In Notion öffnen>"
            }
        }
    ]

    return {"blocks": blocks}


def build_approval_dm_message(
    antrag_name: str,
    vorgangs_id: str,
    betrag: float,
    ziel: str = "N/A",
    reisedatum: str = "N/A",
    page_id: str = ""
) -> Dict[str, Any]:
    """
    Erstellt formatierte DM für Genehmigung
    """

    notion_link = f"https://www.notion.so/{page_id}" if page_id else "#"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "✅ *Reisekostenantrag genehmigt!*"
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*📄 Antrag*\n{antrag_name}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*💰 Betrag*\n€{betrag:,.2f}" if isinstance(betrag, (int, float)) else f"*💰 Betrag*\n€{betrag}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*📍 Ziel*\n{ziel}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*📅 Reisedatum*\n{reisedatum}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*📄 Vorgangs-ID*\n{vorgangs_id}"
                },
                {
                    "type": "mrkdwn",
                    "text": "*✅ Status*\nFreigegeben (gültig ab sofort)"
                }
            ]
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Nächste Schritte:*\n• Reise buchen & durchführen\n• Belege sammeln\n• Abrechnung einreichen"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<{notion_link}|🔗 Antrag in Notion ansehen>"
            }
        }
    ]

    return {"blocks": blocks}


def build_rejection_dm_message(
    antrag_name: str,
    vorgangs_id: str,
    betrag: float,
    ziel: str = "N/A",
    reisedatum: str = "N/A",
    page_id: str = ""
) -> Dict[str, Any]:
    """
    Erstellt formatierte DM für Ablehnung
    """

    notion_link = f"https://www.notion.so/{page_id}" if page_id else "#"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "❌ *Reisekostenantrag abgelehnt*"
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*📄 Antrag*\n{antrag_name}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*💰 Betrag*\n€{betrag:,.2f}" if isinstance(betrag, (int, float)) else f"*💰 Betrag*\n€{betrag}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*📍 Ziel*\n{ziel}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*📅 Reisedatum*\n{reisedatum}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*📄 Vorgangs-ID*\n{vorgangs_id}"
                },
                {
                    "type": "mrkdwn",
                    "text": "*❌ Status*\nAbgelehnt"
                }
            ]
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Falls du Fragen zur Ablehnung hast, wende dich bitte an die Reisekostenprüfung."
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<{notion_link}|🔗 Antrag in Notion ansehen>"
            }
        }
    ]

    return {"blocks": blocks}
