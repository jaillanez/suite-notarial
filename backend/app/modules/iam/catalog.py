"""Catálogo de permisos atómicos y roles (Módulo 2, §2).

Fuente de verdad en código; la migración `fase1_iam` siembra una copia congelada y un test
verifica que la base coincida. La asignación rol → permisos es una propuesta técnica a validar
por la Caja: TODO(negocio) confirmar la matriz con Administración antes de producción.
"""

from dataclasses import dataclass
from enum import StrEnum


class Perm(StrEnum):
    USERS_READ = "users:read"
    USERS_WRITE = "users:write"
    USERS_SUSPEND = "users:suspend"
    ROLES_MANAGE = "roles:manage"
    ESCRIBANOS_READ = "escribanos:read"
    ESCRIBANOS_WRITE = "escribanos:write"
    ESCRIBANOS_STATUS = "escribanos:status"
    DDJJ_READ_OWN = "ddjj:read_own"
    DDJJ_CREATE_OWN = "ddjj:create_own"
    DDJJ_READ_ALL = "ddjj:read_all"
    DDJJ_APPROVE = "ddjj:approve"
    BOLETAS_READ_OWN = "boletas:read_own"
    BOLETAS_READ_ALL = "boletas:read_all"
    COMPROBANTES_UPLOAD = "comprobantes:upload"
    COMPROBANTES_VERIFY = "comprobantes:verify"
    PARAMETERS_READ = "parameters:read"
    PARAMETERS_WRITE = "parameters:write"
    REPORTS_FINANCIAL = "reports:financial"
    AUDIT_READ = "audit:read"
    CMS_PUBLISH = "cms:publish"


PERMISSION_DESCRIPTIONS: dict[Perm, str] = {
    Perm.USERS_READ: "Consultar listados y detalles de usuarios",
    Perm.USERS_WRITE: "Crear y editar usuarios",
    Perm.USERS_SUSPEND: "Suspender y reactivar cuentas de usuario",
    Perm.ROLES_MANAGE: "Asignar roles y modificar permisos",
    Perm.ESCRIBANOS_READ: "Consultar afiliados y registros notariales",
    Perm.ESCRIBANOS_WRITE: "Alta y modificación de escribanos y matrículas",
    Perm.ESCRIBANOS_STATUS: "Modificar el estado de matrícula",
    Perm.DDJJ_READ_OWN: "Consultar declaraciones juradas propias",
    Perm.DDJJ_CREATE_OWN: "Presentar declaración jurada mensual",
    Perm.DDJJ_READ_ALL: "Consultar declaraciones juradas de cualquier escribano",
    Perm.DDJJ_APPROVE: "Confirmar y asentar liquidaciones",
    Perm.BOLETAS_READ_OWN: "Descargar boletas propias",
    Perm.BOLETAS_READ_ALL: "Consultar y emitir boletas de cualquier escribano",
    Perm.COMPROBANTES_UPLOAD: "Adjuntar comprobantes de pago",
    Perm.COMPROBANTES_VERIFY: "Revisar y conciliar comprobantes de pago",
    Perm.PARAMETERS_READ: "Consultar parámetros previsionales vigentes",
    Perm.PARAMETERS_WRITE: "Crear o actualizar parámetros y vigencias",
    Perm.REPORTS_FINANCIAL: "Ver y exportar reportes de recaudación y deuda",
    Perm.AUDIT_READ: "Ver registros de auditoría",
    Perm.CMS_PUBLISH: "Publicar contenidos institucionales",
}


@dataclass(frozen=True)
class RoleDef:
    code: str
    name: str
    description: str
    mfa_required: bool
    permissions: frozenset[Perm]


_OWN = frozenset(
    {Perm.DDJJ_READ_OWN, Perm.DDJJ_CREATE_OWN, Perm.BOLETAS_READ_OWN, Perm.COMPROBANTES_UPLOAD}
)

ROLES: tuple[RoleDef, ...] = (
    RoleDef(
        "ROLE_ADMIN",
        "Administrador del Sistema",
        "Gestión técnica integral: usuarios, roles, parámetros y auditoría.",
        True,
        frozenset(Perm) - _OWN,
    ),
    RoleDef(
        "ROLE_CAJA",
        "Administración de Caja",
        "Padrón, recepción de DDJJ, boletas, novedades y parámetros operativos.",
        True,
        frozenset(
            {
                Perm.USERS_READ,
                Perm.ESCRIBANOS_READ,
                Perm.ESCRIBANOS_WRITE,
                Perm.ESCRIBANOS_STATUS,
                Perm.DDJJ_READ_ALL,
                Perm.DDJJ_APPROVE,
                Perm.BOLETAS_READ_ALL,
                Perm.PARAMETERS_READ,
                Perm.CMS_PUBLISH,
            }
        ),
    ),
    RoleDef(
        "ROLE_TESORERIA",
        "Tesorería y Cobranzas",
        "Conciliación de comprobantes, reportes contables y financieros.",
        True,
        frozenset(
            {
                Perm.ESCRIBANOS_READ,
                Perm.DDJJ_READ_ALL,
                Perm.BOLETAS_READ_ALL,
                Perm.COMPROBANTES_VERIFY,
                Perm.PARAMETERS_READ,
                Perm.REPORTS_FINANCIAL,
            }
        ),
    ),
    RoleDef(
        "ROLE_ESCRIBANO",
        "Escribano / Afiliado",
        "Autogestión: DDJJ mensuales, boletas, comprobantes y trámites propios.",
        False,
        _OWN,
    ),
    RoleDef(
        "ROLE_AUDITOR",
        "Auditoría y Fiscalización",
        "Consulta de solo lectura de registros, parámetros y auditoría.",
        True,
        frozenset(
            {
                Perm.USERS_READ,
                Perm.ESCRIBANOS_READ,
                Perm.DDJJ_READ_ALL,
                Perm.BOLETAS_READ_ALL,
                Perm.PARAMETERS_READ,
                Perm.REPORTS_FINANCIAL,
                Perm.AUDIT_READ,
            }
        ),
    ),
    RoleDef(
        "ROLE_PUBLICO",
        "Usuario Público",
        "Acceso a contenidos institucionales públicos.",
        False,
        frozenset(),
    ),
)

ROLES_BY_CODE: dict[str, RoleDef] = {r.code: r for r in ROLES}

# Permisos que dan acceso a datos de terceros, finanzas o auditoría: el rol que los tenga debe
# exigir 2FA. Lo verifica tests/test_iam_catalog.py.
SENSITIVE_PERMISSIONS: frozenset[Perm] = frozenset(
    {
        Perm.USERS_WRITE,
        Perm.USERS_SUSPEND,
        Perm.ROLES_MANAGE,
        Perm.ESCRIBANOS_WRITE,
        Perm.ESCRIBANOS_STATUS,
        Perm.DDJJ_READ_ALL,
        Perm.DDJJ_APPROVE,
        Perm.BOLETAS_READ_ALL,
        Perm.COMPROBANTES_VERIFY,
        Perm.PARAMETERS_WRITE,
        Perm.REPORTS_FINANCIAL,
        Perm.AUDIT_READ,
        Perm.CMS_PUBLISH,
    }
)
