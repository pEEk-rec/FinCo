"""
Plain-language setup instructions for the phone bridge (PLAN_CAPTURE Stage C5).

The phone runs a no-code automation (MacroDroid or Tasker on Android, Shortcuts on iPhone).
It must forward only the messages from your bank's sender IDs, to FinCo's webhook, with the
secret in a header. This module turns the configuration into the exact rule to create.
"""

from __future__ import annotations

from copilot.config.capture import SmsSendersConfig

PATH = "/api/capture/sms"


def bridge_url(port: int, host: str = "localhost") -> str:
    return f"http://{host}:{port}{PATH}"


def adb_command(port: int) -> str:
    return f"adb reverse tcp:{port} tcp:{port}"


def bridge_instructions(
    senders: SmsSendersConfig,
    *,
    port: int,
    secret: str,
    secret_header: str,
    lan_host: str | None = None,
) -> str:
    """The setup text. `lan_host` set means the Wi-Fi route instead of the USB route."""
    enabled = {c: b for c, b in senders.banks.items() if b.enabled}
    chosen = enabled or senders.banks
    ids = sorted({s for b in chosen.values() for s in b.sender_ids})
    url = bridge_url(port, lan_host or "localhost")
    out: list[str] = []
    out.append("PHONE BRIDGE SETUP")
    out.append("=" * 60)
    if not enabled:
        out.append(
            "No bank is switched on yet, so FinCo would drop every message. Open\n"
            "config/sms_senders.yaml, check each sender ID against a real alert on your phone,\n"
            "and set enabled: true for the banks you use. The IDs below are shown so you can\n"
            "compare, they are not a promise that they are right."
        )
        out.append("")
    out.append("1. Forward ONLY these senders (never all messages):")
    for b in chosen.values():
        mark = "ON " if b.enabled else "off"
        out.append(f"     [{mark}] {b.name}: {', '.join(b.sender_ids)}")
    out.append("")
    out.append("2. Send each one to:")
    out.append(f"     POST {url}")
    out.append(f"     Header   {secret_header}: {secret}")
    out.append("     Body     JSON with the sender and the message text:")
    out.append("")
    out.append("   MacroDroid  Trigger: SMS Received, 'Specific contact' for each sender ID above.")
    out.append(
        "               Action: HTTP Request, POST, body"
        ' {"sender":"[sms_number]","text":"[sms_message]"},'
    )
    out.append("               content type application/json, plus the header above.")
    out.append("   Tasker      Event: Phone, Received Text, Sender = each ID above.")
    out.append("               Task: HTTP Request, Method POST, URL and Headers as above,")
    out.append('               Body {"sender":"%SMSRF","text":"%SMSRB"}.')
    out.append("   iPhone      Shortcuts, Automation, Message, 'Message Contains' your bank name,")
    out.append(
        "               Run Immediately. Action: Get Contents of URL, Method POST, JSON body with"
    )
    out.append("               sender and text from Shortcut Input, header as above.")
    out.append("")
    if lan_host:
        out.append(
            "3. Same Wi-Fi route. WARNING: with --lan the webhook can be reached by any device on"
        )
        out.append(
            "   this network. Only the secret protects it. Use a network you trust, never public"
        )
        out.append("   Wi-Fi, and run `copilot serve --lan` to bind to it.")
    else:
        out.append("3. Keep it private with a USB cable (the backend stays on localhost):")
        out.append(f"     {adb_command(port)}")
        out.append(
            "   Run it again if you unplug the phone. Then the phone reaches this computer as"
        )
        out.append("   http://localhost on the same port.")
    out.append("")
    out.append(
        "4. Test it: pay Rs 1 to a friend. The alert should show up under Tag payments within"
    )
    out.append(
        "   a few seconds. If it does not, Tag payments shows the last alert received per bank."
    )
    out.append("")
    out.append("What FinCo keeps: the amount, direction, last four digits, UTR, payee and time.")
    out.append("What it never keeps: the message text. It is read in memory and thrown away.")
    out.append(f"Allowed sender IDs right now: {', '.join(ids) if enabled else '(none enabled)'}")
    return "\n".join(out)
