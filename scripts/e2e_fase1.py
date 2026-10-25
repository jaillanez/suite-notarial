#!/usr/bin/env python3
"""Prueba punta a punta de la Fase 1 contra el stack local (make dev) y Mailpit.

Recorre: login → 2FA obligatorio → alta de TOTP → acción protegida → cierre de sesión →
ingreso con código de recuperación → suspensión auditada → recuperación de clave por correo.

Uso (desde la raíz, con `make db migrate seed-dev` y `make dev` corriendo):
    backend/.venv/bin/python scripts/e2e_fase1.py --web http://localhost:5173

Requiere DEV_SEED_PASSWORD en backend/.env. Solo para desarrollo: modifica datos locales.
"""

import argparse
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pyotp

HEADERS = {"X-Requested-With": "XMLHttpRequest"}
ADMIN = "admin@suite-notarial.example"
ESCRIBANO = "escribano@suite-notarial.example"


def seed_password() -> str:
    env = Path(__file__).resolve().parents[1] / "backend" / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEV_SEED_PASSWORD="):
            return line.split("=", 1)[1].strip()
    sys.exit("Falta DEV_SEED_PASSWORD en backend/.env")


def step(message: str) -> None:
    sys.stdout.write(f"✔ {message}\n")


def check(condition: bool, message: str) -> None:
    if not condition:
        sys.exit(f"✘ {message}")


def latest_mail(mailpit: str, to: str, subject_prefix: str, since: datetime) -> str:
    """Último correo que coincide, recibido después de `since` (ignora corridas anteriores)."""
    for _ in range(20):
        messages = httpx.get(f"{mailpit}/api/v1/messages").json()["messages"]
        for m in messages:
            created = datetime.fromisoformat(m["Created"].replace("Z", "+00:00"))
            if (
                created >= since
                and m["To"][0]["Address"] == to
                and m["Subject"].startswith(subject_prefix)
            ):
                return str(httpx.get(f"{mailpit}/api/v1/message/{m['ID']}").json()["Text"])
        time.sleep(0.5)
    sys.exit(f"✘ No llegó a Mailpit el correo '{subject_prefix}' para {to}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", default="http://localhost:5173")
    parser.add_argument("--mailpit", default="http://localhost:8025")
    args = parser.parse_args()
    password = seed_password()
    api = f"{args.web}/api/v1"

    with httpx.Client(headers=HEADERS) as admin:
        r = admin.post(f"{api}/auth/login", json={"identifier": ADMIN, "password": password})
        check(r.status_code == 200, f"login admin: {r.text}")
        user = r.json()["user"]
        if user["mfa_enabled"]:
            sys.exit("✘ El admin ya tiene 2FA: recreá la base local (ver README) y reintentá.")
        check(admin.get(f"{api}/users").status_code == 403, "sin 2FA el admin no debe operar")
        step("Admin sin 2FA queda bloqueado (403) hasta activarlo")

        secret = admin.post(f"{api}/auth/mfa/setup").json()["secret"]
        totp = pyotp.TOTP(secret)
        r = admin.post(f"{api}/auth/mfa/enable", json={"code": totp.now()})
        check(r.status_code == 200, f"enable 2FA: {r.text}")
        recovery = r.json()["recovery_codes"]
        check(len(recovery) == 10, "se esperaban 10 códigos de recuperación")
        check(admin.get(f"{api}/users").status_code == 200, "con 2FA el admin debe operar")
        step("2FA activado; la acción protegida /users responde 200")
        check(admin.post(f"{api}/auth/logout").status_code == 204, "logout")
        check(admin.get(f"{api}/auth/me").status_code == 401, "tras logout no hay sesión")
        step("Logout revoca la sesión")

        r = admin.post(f"{api}/auth/login", json={"identifier": ADMIN, "password": password})
        check(r.json()["status"] == "mfa_required", "el segundo ingreso debe pedir 2FA")
        r = admin.post(f"{api}/auth/login/mfa", json={"code": recovery[0]})
        check(r.status_code == 200, f"login con código de recuperación: {r.text}")
        step("Ingreso con contraseña + código de recuperación")

        users = admin.get(f"{api}/users", params={"q": "escribano"}).json()["items"]
        escribano_id = users[0]["id"]
        r = admin.patch(
            f"{api}/users/{escribano_id}/status",
            json={"is_active": False, "reason": "Prueba E2E Fase 1"},
        )
        check(r.status_code == 200 and r.json()["is_active"] is False, "suspensión")
        r = admin.get(f"{api}/audit/security-logs", params={"event_type": "USER_STATUS_CHANGED"})
        entry = r.json()["items"][0]
        check(entry["old_value"]["is_active"] is True, "auditoría con valor anterior")
        check(entry["new_value"]["is_active"] is False, "auditoría con valor nuevo")
        step("Suspensión auditada con actor, IP y valores anterior/nuevo")
        admin.patch(
            f"{api}/users/{escribano_id}/status",
            json={"is_active": True, "reason": "Fin de la prueba E2E"},
        )

    with httpx.Client(headers=HEADERS) as anon:
        started = datetime.now(UTC)
        r = anon.post(f"{api}/auth/password-reset/request", json={"identifier": ESCRIBANO})
        r2 = anon.post(
            f"{api}/auth/password-reset/request", json={"identifier": "nadie@example.com"}
        )
        check(r.json() == r2.json(), "respuesta idéntica para cuentas inexistentes")
        text = latest_mail(args.mailpit, ESCRIBANO, "Restablecer tu contraseña", started)
        match = re.search(r"(https?://\S+)/restablecer-clave#token=([\w-]+)", text)
        check(match is not None, "el correo trae el enlace")
        assert match is not None
        check("localhost:8080" not in text, "nunca el host heredado del sistema anterior")
        step(f"Correo en Mailpit con enlace bajo PUBLIC_WEB_URL ({match.group(1)})")
        token = match.group(2)
        new_password = "Protocolo-E2E-2026!"
        r = anon.post(
            f"{api}/auth/password-reset/confirm",
            json={"token": token, "new_password": new_password},
        )
        check(r.status_code == 200, f"confirmación: {r.text}")
        r = anon.post(
            f"{api}/auth/password-reset/confirm",
            json={"token": token, "new_password": "Otra-Clave-E2E-2026!"},
        )
        check(r.status_code == 400, "el token es de un solo uso")
        step("Token de un solo uso: el segundo uso es rechazado")
        latest_mail(args.mailpit, ESCRIBANO, "Se cambió tu contraseña", started)
        r = anon.post(
            f"{api}/auth/login", json={"identifier": ESCRIBANO, "password": new_password}
        )
        check(r.status_code == 200, "login con la contraseña nueva")
        check(anon.get(f"{api}/users").status_code == 403, "el escribano no administra usuarios")
        step("Login con la clave nueva; el escribano recibe 403 en /users")

    sys.stdout.write("\nFlujo Fase 1 completo.\n")


if __name__ == "__main__":
    main()
