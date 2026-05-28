"""HTML + text templates for transactional emails."""

from __future__ import annotations

import html
from dataclasses import dataclass

from config.settings import settings


@dataclass
class RenderedEmail:
    subject: str
    text: str
    html: str


def member_invitation_email(
    *,
    full_name: str,
    email: str,
    temp_password: str,
    organization_name: str,
    inviter_name: str | None = None,
) -> RenderedEmail:
    """Email sent to a freshly-invited member with their temp password."""

    login_url = settings.APP_LOGIN_URL
    inviter = inviter_name or "Your admin"
    subject = f"You're invited to join {organization_name} on {settings.APP_NAME}"

    text = f"""Hi {full_name},

{inviter} added you to {organization_name} on {settings.APP_NAME}.

Sign in with the credentials below:

  Email:    {email}
  Password: {temp_password}

Login link: {login_url}

For security, please change your password after your first sign-in.

If you weren't expecting this invitation, you can ignore this email.

— The {settings.APP_NAME} team
"""

    safe_name = html.escape(full_name)
    safe_email = html.escape(email)
    safe_pw = html.escape(temp_password)
    safe_org = html.escape(organization_name)
    safe_inviter = html.escape(inviter)
    safe_app = html.escape(settings.APP_NAME)
    safe_url = html.escape(login_url)

    html_body = f"""<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background:#0a0a0d;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#e5e5e7;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0a0a0d;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="560" cellspacing="0" cellpadding="0" style="max-width:560px;width:100%;background:#0f0f12;border:1px solid rgba(255,255,255,0.06);border-radius:14px;overflow:hidden;">
            <tr>
              <td style="padding:28px 32px 8px 32px;">
                <div style="font-size:12px;letter-spacing:0.18em;color:#a78bfa;font-weight:600;text-transform:uppercase;">{safe_app}</div>
              </td>
            </tr>
            <tr>
              <td style="padding:8px 32px 0 32px;">
                <h1 style="margin:0;font-size:22px;font-weight:600;color:#ffffff;line-height:1.3;">
                  You're invited to {safe_org}
                </h1>
                <p style="margin:12px 0 0 0;font-size:14px;color:rgba(255,255,255,0.55);line-height:1.55;">
                  Hi {safe_name}, {safe_inviter} added you to <strong style="color:#fff;font-weight:500;">{safe_org}</strong>. Use the credentials below to sign in.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 8px 32px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px;">
                  <tr>
                    <td style="padding:16px 18px;">
                      <div style="font-size:11px;letter-spacing:0.08em;color:rgba(255,255,255,0.4);text-transform:uppercase;font-weight:500;margin-bottom:4px;">Email</div>
                      <div style="font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:14px;color:#ffffff;word-break:break-all;">{safe_email}</div>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:0 18px 16px 18px;">
                      <div style="font-size:11px;letter-spacing:0.08em;color:rgba(255,255,255,0.4);text-transform:uppercase;font-weight:500;margin-bottom:4px;">Temporary password</div>
                      <div style="font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:14px;color:#c4b5fd;word-break:break-all;">{safe_pw}</div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:20px 32px 4px 32px;">
                <a href="{safe_url}" style="display:inline-block;background:#7c3aed;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:11px 22px;border-radius:9px;">
                  Sign in to {safe_app} &rarr;
                </a>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:8px 32px 0 32px;">
                <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.35);">
                  Or open this link: <a href="{safe_url}" style="color:#a78bfa;text-decoration:none;">{safe_url}</a>
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 28px 32px;">
                <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.4);line-height:1.6;border-top:1px solid rgba(255,255,255,0.06);padding-top:16px;">
                  For security, please change your password after your first sign-in. If you weren't expecting this invitation, you can safely ignore this email.
                </p>
              </td>
            </tr>
          </table>
          <p style="margin:16px 0 0 0;font-size:11px;color:rgba(255,255,255,0.25);">
            &mdash; The {safe_app} team
          </p>
        </td>
      </tr>
    </table>
  </body>
</html>"""

    return RenderedEmail(subject=subject, text=text, html=html_body)


def member_removed_email(
    *,
    full_name: str,
    organization_name: str,
    actor_name: str | None = None,
) -> RenderedEmail:
    """Notify a member that they were removed from an organization."""

    actor = actor_name or "An administrator"
    subject = f"You've been removed from {organization_name}"

    text = f"""Hi {full_name},

{actor} removed you from {organization_name} on {settings.APP_NAME}. You no
longer have access to that workspace.

If you believe this was a mistake, please contact your administrator.

— The {settings.APP_NAME} team
"""

    safe_name = html.escape(full_name)
    safe_org = html.escape(organization_name)
    safe_actor = html.escape(actor)
    safe_app = html.escape(settings.APP_NAME)

    html_body = f"""<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background:#0a0a0d;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#e5e5e7;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0a0a0d;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="560" cellspacing="0" cellpadding="0" style="max-width:560px;width:100%;background:#0f0f12;border:1px solid rgba(255,255,255,0.06);border-radius:14px;overflow:hidden;">
            <tr>
              <td style="padding:28px 32px 8px 32px;">
                <div style="font-size:12px;letter-spacing:0.18em;color:#a78bfa;font-weight:600;text-transform:uppercase;">{safe_app}</div>
              </td>
            </tr>
            <tr>
              <td style="padding:8px 32px 0 32px;">
                <h1 style="margin:0;font-size:22px;font-weight:600;color:#ffffff;line-height:1.3;">
                  Access removed
                </h1>
                <p style="margin:12px 0 0 0;font-size:14px;color:rgba(255,255,255,0.55);line-height:1.55;">
                  Hi {safe_name}, {safe_actor} removed you from <strong style="color:#fff;font-weight:500;">{safe_org}</strong>. You no longer have access to that workspace.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 28px 32px;">
                <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.4);line-height:1.6;border-top:1px solid rgba(255,255,255,0.06);padding-top:16px;">
                  If you believe this was a mistake, please contact your administrator.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""

    return RenderedEmail(subject=subject, text=text, html=html_body)


def password_reset_email(
    *,
    full_name: str,
    email: str,
    temp_password: str,
) -> RenderedEmail:
    """Sent when an admin resets a member's password."""

    login_url = settings.APP_LOGIN_URL
    subject = f"Your {settings.APP_NAME} password was reset"

    text = f"""Hi {full_name},

An admin reset your {settings.APP_NAME} password. You can now sign in with the
temporary password below and change it from your account settings.

  Email:    {email}
  Password: {temp_password}

Login link: {login_url}

If you didn't expect this, contact your administrator immediately.

— The {settings.APP_NAME} team
"""

    safe_name = html.escape(full_name)
    safe_email = html.escape(email)
    safe_pw = html.escape(temp_password)
    safe_app = html.escape(settings.APP_NAME)
    safe_url = html.escape(login_url)

    html_body = f"""<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background:#0a0a0d;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#e5e5e7;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0a0a0d;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="560" cellspacing="0" cellpadding="0" style="max-width:560px;width:100%;background:#0f0f12;border:1px solid rgba(255,255,255,0.06);border-radius:14px;overflow:hidden;">
            <tr>
              <td style="padding:28px 32px 8px 32px;">
                <div style="font-size:12px;letter-spacing:0.18em;color:#a78bfa;font-weight:600;text-transform:uppercase;">{safe_app}</div>
              </td>
            </tr>
            <tr>
              <td style="padding:8px 32px 0 32px;">
                <h1 style="margin:0;font-size:22px;font-weight:600;color:#ffffff;line-height:1.3;">
                  Your password was reset
                </h1>
                <p style="margin:12px 0 0 0;font-size:14px;color:rgba(255,255,255,0.55);line-height:1.55;">
                  Hi {safe_name}, an admin reset your {safe_app} password. Use the temporary password below to sign in, then change it from your account settings.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 8px 32px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px;">
                  <tr>
                    <td style="padding:16px 18px;">
                      <div style="font-size:11px;letter-spacing:0.08em;color:rgba(255,255,255,0.4);text-transform:uppercase;font-weight:500;margin-bottom:4px;">Email</div>
                      <div style="font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:14px;color:#ffffff;word-break:break-all;">{safe_email}</div>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:0 18px 16px 18px;">
                      <div style="font-size:11px;letter-spacing:0.08em;color:rgba(255,255,255,0.4);text-transform:uppercase;font-weight:500;margin-bottom:4px;">Temporary password</div>
                      <div style="font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:14px;color:#c4b5fd;word-break:break-all;">{safe_pw}</div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:20px 32px 4px 32px;">
                <a href="{safe_url}" style="display:inline-block;background:#7c3aed;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:11px 22px;border-radius:9px;">
                  Sign in to {safe_app} &rarr;
                </a>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 28px 32px;">
                <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.4);line-height:1.6;border-top:1px solid rgba(255,255,255,0.06);padding-top:16px;">
                  If you didn't expect this, contact your administrator immediately.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""

    return RenderedEmail(subject=subject, text=text, html=html_body)
