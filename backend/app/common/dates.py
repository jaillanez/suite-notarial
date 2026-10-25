"""Fechas calendario en la zona de la Caja (los parámetros y vencimientos son locales)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Argentina/San_Juan")


def today_local() -> date:
    return datetime.now(LOCAL_TZ).date()
