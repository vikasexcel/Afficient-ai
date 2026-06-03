"""Idempotent provisioning for LiveKit-originated outbound calls.

Sets up the SIP plumbing required for the "Option 2" calling path:

    backend -> LiveKit CreateSIPParticipant
            -> LiveKit OUTBOUND trunk
            -> Twilio Elastic SIP Trunk (termination)
            -> PSTN (the lead's phone)

It creates / reuses, in order:

1. A Twilio Elastic SIP Trunk with a unique ``*.pstn.twilio.com``
   termination domain.
2. A Twilio Credential List (digest auth) attached to the trunk so only
   our LiveKit trunk can send calls through it.
3. Associates the Twilio phone number with the trunk for caller ID.
4. A LiveKit OUTBOUND trunk pointing at the Twilio termination domain,
   authenticating with the credential-list username/password.

The resulting identifiers are printed and appended to ``backend/.env``
(``LIVEKIT_SIP_OUTBOUND_TRUNK_ID`` etc.) so the app can pick them up.

Run:  ./venv/bin/python scripts/setup_sip_trunk.py
"""

from __future__ import annotations

import asyncio
import os
import secrets
import string
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

import livekit.api as lkapi  # noqa: E402
from twilio.rest import Client as TwilioClient  # noqa: E402

TRUNK_FRIENDLY_NAME = "aifficient-lk"
CRED_LIST_NAME = "aifficient-lk-creds"
SIP_USERNAME = "aifficient"


def _gen_password() -> str:
    # Twilio SIP password rules: >=12 chars, upper+lower+digit.
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(20))
        if (
            any(c.islower() for c in pw)
            and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw)
        ):
            return pw


def _termination_domain() -> str:
    suffix = (os.environ["TWILIO_ACCOUNT_SID"][-8:]).lower()
    return f"aifficient-{suffix}.pstn.twilio.com"


def setup_twilio() -> dict[str, str]:
    c = TwilioClient(
        os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]
    )
    phone_number = os.environ["TWILIO_PHONE_NUMBER"]
    domain = _termination_domain()

    # 1. Trunk (reuse by friendly name).
    trunk = next(
        (
            t
            for t in c.trunking.v1.trunks.list(limit=50)
            if t.friendly_name == TRUNK_FRIENDLY_NAME
        ),
        None,
    )
    if trunk is None:
        trunk = c.trunking.v1.trunks.create(
            friendly_name=TRUNK_FRIENDLY_NAME,
            domain_name=domain,
        )
        print(f"[twilio] created trunk {trunk.sid} domain={domain}")
    else:
        print(f"[twilio] reusing trunk {trunk.sid} domain={trunk.domain_name}")
        domain = trunk.domain_name or domain

    # 2. Credential list (reuse by name) + a credential.
    cred_list = next(
        (
            cl
            for cl in c.sip.credential_lists.list(limit=50)
            if cl.friendly_name == CRED_LIST_NAME
        ),
        None,
    )
    password = _gen_password()
    if cred_list is None:
        cred_list = c.sip.credential_lists.create(
            friendly_name=CRED_LIST_NAME
        )
        c.sip.credential_lists(cred_list.sid).credentials.create(
            username=SIP_USERNAME, password=password
        )
        print(
            f"[twilio] created credential list {cred_list.sid} "
            f"user={SIP_USERNAME}"
        )
    else:
        # Rotate the credential so we always know the password.
        for existing in c.sip.credential_lists(
            cred_list.sid
        ).credentials.list(limit=50):
            if existing.username == SIP_USERNAME:
                c.sip.credential_lists(cred_list.sid).credentials(
                    existing.sid
                ).delete()
        c.sip.credential_lists(cred_list.sid).credentials.create(
            username=SIP_USERNAME, password=password
        )
        print(
            f"[twilio] reusing credential list {cred_list.sid}, "
            f"rotated password for user={SIP_USERNAME}"
        )

    # Attach credential list to the trunk for termination auth.
    attached = c.trunking.v1.trunks(trunk.sid).credentials_lists.list(
        limit=50
    )
    if not any(a.sid == cred_list.sid for a in attached):
        c.trunking.v1.trunks(trunk.sid).credentials_lists.create(
            credential_list_sid=cred_list.sid
        )
        print("[twilio] attached credential list to trunk")

    # 3. Associate the phone number with the trunk (caller ID).
    num = next(
        (
            n
            for n in c.incoming_phone_numbers.list(
                phone_number=phone_number, limit=5
            )
        ),
        None,
    )
    if num is not None and num.trunk_sid != trunk.sid:
        c.incoming_phone_numbers(num.sid).update(trunk_sid=trunk.sid)
        print(f"[twilio] assigned {phone_number} to trunk")
    elif num is not None:
        print(f"[twilio] {phone_number} already on trunk")

    return {
        "domain": domain,
        "username": SIP_USERNAME,
        "password": password,
        "trunk_sid": trunk.sid,
        "phone_number": phone_number,
    }


async def setup_livekit(tw: dict[str, str]) -> str:
    lk = lkapi.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"].replace("wss://", "https://").replace(
            "ws://", "http://"
        ),
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )
    try:
        # Remove stale outbound trunks with the same name so reruns are clean.
        existing = await lk.sip.list_sip_outbound_trunk(
            lkapi.ListSIPOutboundTrunkRequest()
        )
        for t in existing.items:
            if t.name == TRUNK_FRIENDLY_NAME:
                await lk.sip.delete_sip_trunk(
                    lkapi.DeleteSIPTrunkRequest(sip_trunk_id=t.sip_trunk_id)
                )
                print(f"[livekit] deleted stale outbound trunk {t.sip_trunk_id}")

        resp = await lk.sip.create_sip_outbound_trunk(
            lkapi.CreateSIPOutboundTrunkRequest(
                trunk=lkapi.SIPOutboundTrunkInfo(
                    name=TRUNK_FRIENDLY_NAME,
                    address=tw["domain"],
                    transport=lkapi.SIP_TRANSPORT_AUTO,
                    numbers=[tw["phone_number"]],
                    auth_username=tw["username"],
                    auth_password=tw["password"],
                )
            )
        )
        print(f"[livekit] created outbound trunk {resp.sip_trunk_id}")
        return resp.sip_trunk_id
    finally:
        await lk.aclose()


def write_env(updates: dict[str, str]) -> None:
    lines = ENV_PATH.read_text().splitlines()
    keys = set(updates)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key in keys:
            continue
        out.append(line)
    out.append("")
    out.append("# --- SIP outbound (LiveKit-originated calls) ---")
    for k, v in updates.items():
        out.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(out) + "\n")
    print(f"[env] wrote {', '.join(updates)} to {ENV_PATH}")


def main() -> None:
    tw = setup_twilio()
    trunk_id = asyncio.run(setup_livekit(tw))
    write_env(
        {
            "LIVEKIT_SIP_OUTBOUND_TRUNK_ID": trunk_id,
            "TWILIO_SIP_TERMINATION_DOMAIN": tw["domain"],
            "TWILIO_SIP_USERNAME": tw["username"],
            "TWILIO_SIP_PASSWORD": tw["password"],
        }
    )
    print("\nDone. Outbound SIP trunk ready:", trunk_id)


if __name__ == "__main__":
    main()
