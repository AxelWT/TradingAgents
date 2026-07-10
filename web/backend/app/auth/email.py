import asyncio
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _build_message(to_email: str, code: str, settings: Settings) -> MIMEMultipart:
    message = MIMEMultipart("alternative")
    message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    message["To"] = to_email
    message["Subject"] = "TradingAgents 注册验证码"

    text_body = (
        f"您正在注册 TradingAgents 账号。\n\n"
        f"您的验证码是：{code}\n\n"
        f"验证码 {settings.VERIFY_CODE_EXPIRE_MINUTES} 分钟内有效，请尽快使用。\n"
        f"如果不是您本人操作，请忽略此邮件。\n"
    )
    html_body = (
        f"<div style='font-family:Arial,sans-serif;max-width:480px;margin:0 auto;"
        f"padding:24px;color:#333;'>"
        f"<h2 style='color:#10b981;'>TradingAgents 注册验证码</h2>"
        f"<p>您正在注册 TradingAgents 账号，请使用以下验证码完成注册：</p>"
        f"<div style='margin:24px 0;text-align:center;'>"
        f"<span style='display:inline-block;font-size:28px;font-weight:bold;"
        f"letter-spacing:6px;color:#10b981;background:#f0fdf4;border:1px solid #bbf7d0;"
        f"border-radius:8px;padding:12px 24px;'>{code}</span>"
        f"</div>"
        f"<p style='color:#666;font-size:13px;'>"
        f"验证码 {settings.VERIFY_CODE_EXPIRE_MINUTES} 分钟内有效。"
        f"如果不是您本人操作，请忽略此邮件。</p>"
        f"</div>"
    )

    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))
    return message


def _smtp_send_blocking(to_email: str, code: str) -> None:
    """同步发送邮件，在线程池中执行以避免阻塞事件循环。"""
    settings = get_settings()

    if not settings.SMTP_HOST or not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
        raise RuntimeError("邮件服务未配置")

    message = _build_message(to_email, code, settings)

    if settings.SMTP_USE_SSL:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            settings.SMTP_HOST, settings.SMTP_PORT, context=context, timeout=20
        ) as server:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM_EMAIL, [to_email], message.as_string())
    else:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM_EMAIL, [to_email], message.as_string())


async def send_verification_email(to_email: str, code: str) -> None:
    """异步发送验证码邮件（阻塞的 SMTP 调用放到线程池执行）。"""
    try:
        await asyncio.to_thread(_smtp_send_blocking, to_email, code)
        logger.info("Verification email sent to %s", to_email)
    except Exception as e:
        logger.exception("Failed to send verification email to %s", to_email)
        raise RuntimeError(f"邮件发送失败: {e}") from e
