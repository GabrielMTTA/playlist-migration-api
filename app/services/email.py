import httpx

from app.core.config import settings


async def send_approval_email(name: str, contact_email: str) -> None:
    """Send a Spotify access approval e-mail via Resend."""

    html = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Seu acesso ao TuneShip foi aprovado</title>
</head>
<body style="margin:0;padding:0;background:#0f1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f1117;padding:40px 20px;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#161b27;border-radius:16px;border:1px solid #252d3d;overflow:hidden;">

          <!-- Header -->
          <tr>
            <td style="padding:32px 32px 24px;text-align:center;border-bottom:1px solid #252d3d;">
              <div style="display:inline-flex;align-items:center;justify-content:center;width:48px;height:48px;background:#1DB954;border-radius:12px;margin-bottom:16px;">
                <span style="font-size:24px;">🎵</span>
              </div>
              <h1 style="margin:0;font-size:22px;font-weight:700;color:#e8ecf4;">TuneShip</h1>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:32px;">
              <p style="margin:0 0 12px;font-size:18px;font-weight:600;color:#e8ecf4;">
                Olá, {name}! 🎉
              </p>
              <p style="margin:0 0 20px;font-size:15px;line-height:1.6;color:#a8b1c8;">
                Boa notícia! Seu acesso ao <strong style="color:#e8ecf4;">TuneShip</strong> via Spotify foi aprovado.
                Agora você pode migrar suas playlists entre Spotify e YouTube Music de forma gratuita.
              </p>

              <!-- CTA Button -->
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding:8px 0 24px;">
                    <a
                      href="https://tuneship-web-music.vercel.app/login"
                      style="display:inline-block;padding:14px 36px;background:#6366f1;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;border-radius:12px;"
                    >
                      Acessar o TuneShip →
                    </a>
                  </td>
                </tr>
              </table>

              <p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#a8b1c8;">
                Ao entrar, faça login com a conta do Spotify cujo e-mail você informou no cadastro.
              </p>

              <!-- Divider -->
              <hr style="border:none;border-top:1px solid #252d3d;margin:24px 0;" />

              <p style="margin:0;font-size:13px;color:#4b5675;line-height:1.6;">
                Se você não solicitou acesso ao TuneShip, pode ignorar este e-mail com segurança.
                <br/>Dúvidas? Responda este e-mail ou contate <a href="mailto:contato@tuneship.app" style="color:#6366f1;">contato@tuneship.app</a>
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:16px 32px;text-align:center;border-top:1px solid #252d3d;">
              <p style="margin:0;font-size:12px;color:#4b5675;">
                © 2026 TuneShip · tuneship-web-music.vercel.app
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": settings.resend_from_email,
                "to": [contact_email],
                "subject": "🎉 Seu acesso ao TuneShip foi aprovado!",
                "html": html,
            },
            timeout=15.0,
        )
        response.raise_for_status()
