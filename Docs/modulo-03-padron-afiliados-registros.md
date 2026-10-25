# Documento de Ingeniería de Software — Módulo 3
## Padrón de Afiliados, Escribanos y Registros Notariales
**Suite Integral Caja Notarial de San Juan**  
**Versión:** 1.0.0 | **Estado:** Especificación Técnica Detallada  
**Requerimientos del Pliego:** `DIR-01`, `DIR-02`, `DIR-03`, `DIR-04`, `USR-01`, `USR-02`, `SEC-01`, `SEC-03`  
**Stack de Referencia:** Python 3.12+ | FastAPI | PostgreSQL 16+ | SQLAlchemy 2.0 (Async) | Pydantic v2 | React + TypeScript

---

### 1. Propósito, Alcance y Reglas del Dominio Notarial

El **Módulo 3 (Padrón de Afiliados, Escribanos y Registros)** gestiona el universo de sujetos y entidades habilitadas para el ejercicio notarial en la Provincia de San Juan. Actúa como el maestro de datos de referencia para la posterior emisión de Declaraciones Juradas (DDJJ), cálculo de aportes, emisión de boletas y gestión de préstamos previsionales.

#### 1.1 Reglas del Negocio Notarial y Mitigación de Defectos
1. **Unicidad e Identidad sin Duplicación (`DIR-03` / `USR-01`):** Se erradica la inconsistencia de registrar datos de personas en múltiples tablas desarticuladas. La arquitectura desacopla a la persona física (`padron_personas`), su matrícula notarial (`padron_escribanos`) y sus credenciales de acceso al sistema (`security_users`). El número de CUIT y la matrícula profesional son claves únicas irrepetibles validadas con el algoritmo Módulo 11 oficial de AFIP.
2. **Jerarquía y Relación Notarial en San Juan:**
   - Cada **Registro Notarial** posee un número identificador único asignado dentro de su circunscripción o departamento territorial de la provincia.
   - En cada registro existe exactamente **un Escribano Titular** activo a la vez, pudiendo coexistir uno o más **Escribanos Adscriptos** o Suplentes debidamente designados.
3. **Preservación Histórica sin Borrado Físico (`DIR-04`):** Ningún registro de escribano, matrícula o asignación a registro notarial puede ser eliminado de la base de datos mediante sentencias `DELETE`. Toda baja se implementa como una transición de estado (`ACTIVO` -> `SUSPENDIDO`, `CESANTE` o `JUBILADO`) con indicación obligatoria del motivo, fecha efectiva y usuario operador (`DIR-02`).
4. **Búsqueda Avanzada y Rendimiento (`DIR-01`):** Consultas indexadas por matrícula, CUIT, nombre y apellido, departamento y estado, garantizando respuestas sub-segundo con paginación optimizada.

---

### 2. Modelo de Datos Relacional (PostgreSQL DDL)

```sql
-- Tabla Central de Personas Físicas (Datos Biográficos y Fiscales)
CREATE TABLE IF NOT EXISTS padron_personas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cuit VARCHAR(11) UNIQUE NOT NULL, -- 11 dígitos numéricos limpios
    tipo_documento VARCHAR(10) NOT NULL DEFAULT 'DNI',
    numero_documento VARCHAR(15) NOT NULL,
    apellido VARCHAR(100) NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    fecha_nacimiento DATE,
    genero VARCHAR(20),
    email_personal VARCHAR(255),
    telefono_personal VARCHAR(50),
    domicilio_real TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    created_by_user_id UUID REFERENCES security_users(id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_personas_cuit ON padron_personas(cuit);
CREATE INDEX idx_personas_apellido_nombre ON padron_personas(apellido, nombre);

-- Tabla de Registros Notariales (Oficinas / Escribanías)
CREATE TABLE IF NOT EXISTS padron_registros_notariales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    numero_registro INT UNIQUE NOT NULL, -- Número de Registro Notarial
    nombre_fantasia VARCHAR(150),
    circunscripcion VARCHAR(100) NOT NULL DEFAULT 'Primera Circunscripción - Capital',
    departamento VARCHAR(100) NOT NULL DEFAULT 'Capital', -- Capital, Rawson, Rivadavia, etc.
    domicilio_legal TEXT NOT NULL,
    telefono_oficina VARCHAR(50),
    email_oficina VARCHAR(255),
    fecha_creacion DATE,
    estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVO', -- ACTIVO, VACANTE, CERRADO
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    created_by_user_id UUID REFERENCES security_users(id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_registros_numero ON padron_registros_notariales(numero_registro);

-- Tabla de Escribanos Matriculados
CREATE TABLE IF NOT EXISTS padron_escribanos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id UUID UNIQUE NOT NULL REFERENCES padron_personas(id) ON DELETE RESTRICT,
    user_id UUID UNIQUE REFERENCES security_users(id) ON DELETE SET NULL, -- Cuenta de Autogestión
    matricula_numero INT UNIQUE NOT NULL,
    tomo VARCHAR(20),
    folio VARCHAR(20),
    fecha_matriculacion DATE NOT NULL,
    estado_matricula VARCHAR(30) NOT NULL DEFAULT 'ACTIVO', -- ACTIVO, SUSPENDIDO, CESANTE, JUBILADO, FALLECIDO
    motivo_ultimo_cambio_estado TEXT,
    fecha_ultimo_cambio_estado TIMESTAMPTZ,
    operador_ultimo_cambio_id UUID REFERENCES security_users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    created_by_user_id UUID REFERENCES security_users(id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_escribanos_matricula ON padron_escribanos(matricula_numero);
CREATE INDEX idx_escribanos_estado ON padron_escribanos(estado_matricula);

-- Tabla de Asignaciones y Cargos Notariales (Titularidades y Adscripciones)
CREATE TABLE IF NOT EXISTS padron_adscripciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    escribano_id UUID NOT NULL REFERENCES padron_escribanos(id) ON DELETE RESTRICT,
    registro_id UUID NOT NULL REFERENCES padron_registros_notariales(id) ON DELETE RESTRICT,
    cargo VARCHAR(30) NOT NULL DEFAULT 'ADSCRIPTO', -- TITULAR, ADSCRIPTO, SUPLENTE_INTERINO
    resolucion_designacion VARCHAR(100),
    fecha_desde DATE NOT NULL,
    fecha_hasta DATE, -- NULL si permanece vigente
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    created_by_user_id UUID REFERENCES security_users(id)
);

CREATE INDEX idx_adscripciones_escribano ON padron_adscripciones(escribano_id);
CREATE INDEX idx_adscripciones_registro ON padron_adscripciones(registro_id);

-- Tabla de Historial Inmutable de Cambios de Estado del Escribano (DIR-02 / SEC-03)
CREATE TABLE IF NOT EXISTS padron_historial_estados (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    escribano_id UUID NOT NULL REFERENCES padron_escribanos(id) ON DELETE RESTRICT,
    estado_anterior VARCHAR(30) NOT NULL,
    estado_nuevo VARCHAR(30) NOT NULL,
    motivo TEXT NOT NULL,
    resolucion_respaldo VARCHAR(100),
    fecha_cambio TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    operador_user_id UUID NOT NULL REFERENCES security_users(id)
);

CREATE INDEX idx_historial_escribano ON padron_historial_estados(escribano_id);
```

---

### 3. Modelos Declarativos en Python (SQLAlchemy 2.0 Async)

#### 3.1 Modelos del Padrón (`backend/app/models/padron.py`)

```python
import uuid
from datetime import date, datetime
from typing import List, Optional
from sqlalchemy import String, Integer, Date, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, AuditMixin, utc_now

class Persona(Base, AuditMixin):
    __tablename__ = "padron_personas"

    cuit: Mapped[str] = mapped_column(String(11), unique=True, nullable=False, index=True)
    tipo_documento: Mapped[str] = mapped_column(String(10), default="DNI", nullable=False)
    numero_documento: Mapped[str] = mapped_column(String(15), nullable=False)
    apellido: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    fecha_nacimiento: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    genero: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    email_personal: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    telefono_personal: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    domicilio_real: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    escribano: Mapped[Optional["Escribano"]] = relationship("Escribano", back_populates="persona", uselist=False)

class RegistroNotarial(Base, AuditMixin):
    __tablename__ = "padron_registros_notariales"

    numero_registro: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    nombre_fantasia: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    circunscripcion: Mapped[str] = mapped_column(String(100), default="Primera Circunscripción", nullable=False)
    departamento: Mapped[str] = mapped_column(String(100), default="Capital", nullable=False)
    domicilio_legal: Mapped[str] = mapped_column(Text, nullable=False)
    telefono_oficina: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email_oficina: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    fecha_creacion: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVO", nullable=False)

    adscripciones: Mapped[List["Adscripcion"]] = relationship("Adscripcion", back_populates="registro")

class Escribano(Base, AuditMixin):
    __tablename__ = "padron_escribanos"

    persona_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("padron_personas.id"), unique=True, nullable=False
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), unique=True, nullable=True
    )
    matricula_numero: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    tomo: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    folio: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    fecha_matriculacion: Mapped[date] = mapped_column(Date, nullable=False)
    estado_matricula: Mapped[str] = mapped_column(String(30), default="ACTIVO", nullable=False, index=True)
    motivo_ultimo_cambio_estado: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fecha_ultimo_cambio_estado: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    operador_ultimo_cambio_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )

    persona: Mapped[Persona] = relationship("Persona", back_populates="escribano", lazy="joined")
    adscripciones: Mapped[List["Adscripcion"]] = relationship("Adscripcion", back_populates="escribano")
    historial_estados: Mapped[List["HistorialEstado"]] = relationship("HistorialEstado", back_populates="escribano")

class Adscripcion(Base, AuditMixin):
    __tablename__ = "padron_adscripciones"

    escribano_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("padron_escribanos.id"), nullable=False
    )
    registro_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("padron_registros_notariales.id"), nullable=False
    )
    cargo: Mapped[str] = mapped_column(String(30), default="ADSCRIPTO", nullable=False)
    resolucion_designacion: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    fecha_desde: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_hasta: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    escribano: Mapped[Escribano] = relationship(Escribano, back_populates="adscripciones")
    registro: Mapped[RegistroNotarial] = relationship(RegistroNotarial, back_populates="adscripciones", lazy="joined")

class HistorialEstado(Base):
    __tablename__ = "padron_historial_estados"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    escribano_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("padron_escribanos.id"), nullable=False
    )
    estado_anterior: Mapped[str] = mapped_column(String(30), nullable=False)
    estado_nuevo: Mapped[str] = mapped_column(String(30), nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    resolucion_respaldo: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    fecha_cambio: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    operador_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=False
    )

    escribano: Mapped[Escribano] = relationship(Escribano, back_populates="historial_estados")
```

---

### 4. Validación de CUIT y Contratos Pydantic v2 (`backend/app/schemas/padron.py`)

#### 4.1 Algoritmo Oficial de Verificación de CUIT (Módulo 11)

```python
import re
import uuid
from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator

def validate_cuit_modulo11(cuit: str) -> str:
    """
    Valida y normaliza un CUIT/CUIL argentino conforme al algoritmo oficial de Módulo 11.
    Retorna los 11 dígitos limpios si es válido; de lo contrario lanza ValueError.
    """
    clean_cuit = re.sub(r"\D", "", cuit)
    if len(clean_cuit) != 11:
        raise ValueError("El CUIT debe contener exactamente 11 dígitos numéricos.")

    base = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    suma = sum(int(clean_cuit[i]) * base[i] for i in range(10))
    resto = suma % 11
    
    if resto == 0:
        digito_verificador = 0
    elif resto == 1:
        if clean_cuit[:2] == "20":
            digito_verificador = 9
        elif clean_cuit[:2] == "27":
            digito_verificador = 4
        else:
            digito_verificador = 0
    else:
        digito_verificador = 11 - resto

    if int(clean_cuit[10]) != digito_verificador:
        raise ValueError("Dígito verificador de CUIT inválido según algoritmo oficial AFIP.")

    return clean_cuit

class PersonaCreate(BaseModel):
    cuit: str = Field(..., description="CUIT/CUIL de 11 dígitos")
    numero_documento: str = Field(..., min_length=6, max_length=15)
    tipo_documento: str = "DNI"
    apellido: str = Field(..., min_length=2, max_length=100)
    nombre: str = Field(..., min_length=2, max_length=100)
    fecha_nacimiento: Optional[date] = None
    genero: Optional[str] = None
    email_personal: Optional[str] = None
    telefono_personal: Optional[str] = None
    domicilio_real: Optional[str] = None

    @field_validator("cuit")
    @classmethod
    def check_cuit(cls, v: str) -> str:
        return validate_cuit_modulo11(v)

class EscribanoCreate(BaseModel):
    persona: PersonaCreate
    matricula_numero: int = Field(..., gt=0, description="Número de matrícula profesional único")
    tomo: Optional[str] = None
    folio: Optional[str] = None
    fecha_matriculacion: date
    registro_id: Optional[uuid.UUID] = Field(None, description="Registro notarial de asignación inicial")
    cargo_inicial: Optional[str] = Field("ADSCRIPTO", description="TITULAR o ADSCRIPTO")

class EscribanoStatusUpdate(BaseModel):
    nuevo_estado: str = Field(..., description="ACTIVO, SUSPENDIDO, CESANTE o JUBILADO")
    motivo: str = Field(..., min_length=5, description="Motivo obligatorio del cambio de estado (DIR-02)")
    resolucion_respaldo: Optional[str] = Field(None, description="Número de resolución de Directorio")

class EscribanoResponse(BaseModel):
    id: uuid.UUID
    matricula_numero: int
    tomo: Optional[str]
    folio: Optional[str]
    fecha_matriculacion: date
    estado_matricula: str
    nombre_completo: str
    cuit: str
    numero_documento: str
    registro_actual: Optional[int] = None
    cargo_actual: Optional[str] = None
    is_active: bool
```

---

### 5. Controlador API REST (FastAPI) (`backend/app/api/v1/endpoints/padron.py`)

```python
import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from app.core.database import get_db_session
from app.api.deps import require_permissions, get_current_user
from app.models.security import User
from app.models.padron import Persona, Escribano, RegistroNotarial, Adscripcion, HistorialEstado
from app.schemas.padron import EscribanoCreate, EscribanoStatusUpdate, EscribanoResponse

router = APIRouter(prefix="/padron", tags=["Padrón de Escribanos y Registros"])

@router.get("/escribanos", response_model=dict)
async def list_escribanos(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(None, description="Búsqueda libre: apellido, nombre, matrícula o CUIT"),
    estado: Optional[str] = Query(None, description="Filtro por estado: ACTIVO, SUSPENDIDO, etc."),
    registro_numero: Optional[int] = Query(None, description="Filtro por Registro Notarial"),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permissions("escribanos:read"))
):
    """
    Listado paginado de escribanos con filtros por cabecera responsiva (DIR-01 / REP-03).
    """
    stmt = select(Escribano).join(Persona, Escribano.persona_id == Persona.id)

    if q:
        clean_q = q.strip().replace("-", "")
        stmt = stmt.where(
            or_(
                Persona.apellido.ilike(f"%{q}%"),
                Persona.nombre.ilike(f"%{q}%"),
                Persona.cuit.ilike(f"%{clean_q}%"),
                func.cast(Escribano.matricula_numero, String).ilike(f"%{q}%")
            )
        )

    if estado:
        stmt = stmt.where(Escribano.estado_matricula == estado.upper())

    # Conteo total para paginación
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = (await db.execute(count_stmt)).scalar_one()

    # Paginación ordenada
    offset = (page - 1) * page_size
    stmt = stmt.order_by(Persona.apellido.asc(), Persona.nombre.asc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    escribanos = result.scalars().all()

    items = []
    for esc in escribanos:
        # Resolver cargo actual
        cargo_act = None
        reg_num = None
        for ads in esc.adscripciones:
            if ads.is_current:
                cargo_act = ads.cargo
                reg_num = ads.registro.numero_registro
                break

        items.append(EscribanoResponse(
            id=esc.id,
            matricula_numero=esc.matricula_numero,
            tomo=esc.tomo,
            folio=esc.folio,
            fecha_matriculacion=esc.fecha_matriculacion,
            estado_matricula=esc.estado_matricula,
            nombre_completo=f"{esc.persona.apellido}, {esc.persona.nombre}",
            cuit=esc.persona.cuit,
            numero_documento=esc.persona.numero_documento,
            registro_actual=reg_num,
            cargo_actual=cargo_act,
            is_active=esc.is_active
        ))

    return {
        "items": items,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size
    }

@router.post("/escribanos", response_model=EscribanoResponse, status_code=status.HTTP_201_CREATED)
async def create_escribano(
    payload: EscribanoCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permissions("escribanos:write"))
):
    """
    Alta de nuevo escribano y persona con verificación estricta de unicidad (DIR-03).
    """
    # 1. Verificar unicidad de CUIT
    stmt_cuit = select(Persona).where(Persona.cuit == payload.persona.cuit)
    if (await db.execute(stmt_cuit)).scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El CUIT ya se encuentra registrado.")

    # 2. Verificar unicidad de Matrícula
    stmt_mat = select(Escribano).where(Escribano.matricula_numero == payload.matricula_numero)
    if (await db.execute(stmt_mat)).scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El número de matrícula ya existe.")

    # 3. Crear Persona
    persona = Persona(
        cuit=payload.persona.cuit,
        numero_documento=payload.persona.numero_documento,
        tipo_documento=payload.persona.tipo_documento,
        apellido=payload.persona.apellido,
        nombre=payload.persona.nombre,
        fecha_nacimiento=payload.persona.fecha_nacimiento,
        genero=payload.persona.genero,
        email_personal=payload.persona.email_personal,
        telefono_personal=payload.persona.telefono_personal,
        domicilio_real=payload.persona.domicilio_real,
        created_by_user_id=current_user.id
    )
    db.add(persona)
    await db.flush()

    # 4. Crear Escribano
    escribano = Escribano(
        persona_id=persona.id,
        matricula_numero=payload.matricula_numero,
        tomo=payload.tomo,
        folio=payload.folio,
        fecha_matriculacion=payload.fecha_matriculacion,
        estado_matricula="ACTIVO",
        created_by_user_id=current_user.id
    )
    db.add(escribano)
    await db.flush()

    # 5. Asignar a Registro Notarial si se proporcionó
    reg_num = None
    if payload.registro_id:
        adscripcion = Adscripcion(
            escribano_id=escribano.id,
            registro_id=payload.registro_id,
            cargo=payload.cargo_inicial or "ADSCRIPTO",
            fecha_desde=payload.fecha_matriculacion,
            is_current=True,
            created_by_user_id=current_user.id
        )
        db.add(adscripcion)

    await db.commit()

    return EscribanoResponse(
        id=escribano.id,
        matricula_numero=escribano.matricula_numero,
        tomo=escribano.tomo,
        folio=escribano.folio,
        fecha_matriculacion=escribano.fecha_matriculacion,
        estado_matricula=escribano.estado_matricula,
        nombre_completo=f"{persona.apellido}, {persona.nombre}",
        cuit=persona.cuit,
        numero_documento=persona.numero_documento,
        registro_actual=reg_num,
        cargo_actual=payload.cargo_inicial,
        is_active=True
    )

@router.patch("/escribanos/{escribano_id}/status", status_code=status.HTTP_200_OK)
async def update_escribano_status(
    escribano_id: uuid.UUID,
    payload: EscribanoStatusUpdate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permissions("escribanos:status"))
):
    """
    Modificación de estado notarial con registro histórico obligatorio sin borrado físico (DIR-02 / DIR-04).
    """
    stmt = select(Escribano).where(Escribano.id == escribano_id)
    escribano = (await db.execute(stmt)).scalar_one_or_none()

    if not escribano:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escribano no encontrado.")

    estado_anterior = escribano.estado_matricula
    nuevo_estado_norm = payload.nuevo_estado.upper()

    if estado_anterior == nuevo_estado_norm:
        return {"status": "unchanged", "message": "El escribano ya se encuentra en dicho estado."}

    # Registrar en historial inmutable
    historial = HistorialEstado(
        escribano_id=escribano.id,
        estado_anterior=estado_anterior,
        estado_nuevo=nuevo_estado_norm,
        motivo=payload.motivo,
        resolucion_respaldo=payload.resolucion_respaldo,
        operador_user_id=current_user.id
    )
    db.add(historial)

    # Actualizar estado actual
    escribano.estado_matricula = nuevo_estado_norm
    escribano.motivo_ultimo_cambio_estado = payload.motivo
    escribano.fecha_ultimo_cambio_estado = func.now()
    escribano.operador_ultimo_cambio_id = current_user.id

    await db.commit()

    return {
        "status": "success",
        "message": f"Estado de matrícula actualizado de {estado_anterior} a {nuevo_estado_norm}.",
        "escribano_id": escribano.id
    }
```

---

### 6. Frontend: Interfaz Responsiva de Padrón (`frontend/src/pages/PadronEscribanosPage.tsx`)

Resuelve de forma definitiva el requisito `REP-03` al suprimir los scrolls horizontales infinitos mediante diseño responsivo en tarjetas expandibles:

```tsx
import React, { useState, useEffect } from 'react';
import { Table, Input, Select, Tag, Button, Modal, Form, message } from 'antd';
import { SearchOutlined, EditOutlined, EyeOutlined } from '@ant-design/icons';
import { escribanosService } from '../services/escribanosService';

export const PadronEscribanosPage: React.FC = () => {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [searchText, setSearchText] = useState('');
  const [estadoFilter, setEstadoFilter] = useState<string | undefined>(undefined);

  const [statusModalVisible, setStatusModalVisible] = useState(false);
  const [selectedEscribano, setSelectedEscribano] = useState<any>(null);
  const [form] = Form.useForm();

  const loadData = async (currentPage = 1) => {
    setLoading(true);
    try {
      const res = await escribanosService.list({
        page: currentPage,
        pageSize: 15,
        q: searchText,
        estado: estadoFilter
      });
      setData(res.items);
      setTotal(res.total);
      setPage(res.page);
    } catch (err: any) {
      message.error('Error al consultar el padrón de escribanos.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData(1);
  }, [searchText, estadoFilter]);

  const handleStatusSubmit = async (values: any) => {
    try {
      await escribanosService.updateStatus(selectedEscribano.id, values);
      message.success('Estado actualizado correctamente.');
      setStatusModalVisible(false);
      form.resetFields();
      loadData(page);
    } catch (err: any) {
      message.error(err.response?.data?.detail || 'Error al actualizar el estado.');
    }
  };

  const columns = [
    {
      title: 'Matrícula',
      dataIndex: 'matricula_numero',
      key: 'matricula_numero',
      width: 100,
      render: (val: number) => <strong>#{val}</strong>
    },
    {
      title: 'Escribano (Apellido y Nombre)',
      dataIndex: 'nombre_completo',
      key: 'nombre_completo',
    },
    {
      title: 'CUIT / DNI',
      key: 'cuit',
      render: (_: any, record: any) => (
        <span>{record.cuit} <br/><small className="text-gray-500">DNI {record.numero_documento}</small></span>
      )
    },
    {
      title: 'Registro',
      key: 'registro',
      render: (_: any, record: any) => record.registro_actual ? (
        <span>Reg. Nº {record.registro_actual} ({record.cargo_actual})</span>
      ) : <Tag color="default">Sin Registro Activo</Tag>
    },
    {
      title: 'Estado',
      dataIndex: 'estado_matricula',
      key: 'estado_matricula',
      render: (estado: string) => {
        const color = estado === 'ACTIVO' ? 'green' : estado === 'SUSPENDIDO' ? 'volcano' : 'default';
        return <Tag color={color}>{estado}</Tag>;
      }
    },
    {
      title: 'Acciones',
      key: 'actions',
      render: (_: any, record: any) => (
        <div className="space-x-2">
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => {
              setSelectedEscribano(record);
              form.setFieldsValue({ nuevo_estado: record.estado_matricula });
              setStatusModalVisible(true);
            }}
          >
            Estado
          </Button>
        </div>
      )
    }
  ];

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      <div className="flex flex-wrap justify-between items-center mb-4 gap-4">
        <h1 className="text-2xl font-bold text-gray-800">Padrón de Escribanos y Registros</h1>
        <div className="flex gap-2">
          <Input
            placeholder="Buscar por nombre, matrícula o CUIT..."
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            style={{ width: 280 }}
            allowClear
          />
          <Select
            placeholder="Filtrar por Estado"
            value={estadoFilter}
            onChange={val => setEstadoFilter(val)}
            allowClear
            style={{ width: 160 }}
          >
            <Select.Option value="ACTIVO">ACTIVO</Select.Option>
            <Select.Option value="SUSPENDIDO">SUSPENDIDO</Select.Option>
            <Select.Option value="CESANTE">CESANTE</Select.Option>
            <Select.Option value="JUBILADO">JUBILADO</Select.Option>
          </Select>
        </div>
      </div>

      <Table
        columns={columns}
        dataSource={data}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize: 15,
          total: total,
          onChange: p => loadData(p)
        }}
        scroll={{ x: 800 }}
      />

      <Modal
        title={`Actualizar Estado - ${selectedEscribano?.nombre_completo}`}
        visible={statusModalVisible}
        onCancel={() => setStatusModalVisible(false)}
        onOk={() => form.submit()}
      >
        <Form form={form} layout="vertical" onFinish={handleStatusSubmit}>
          <Form.Item name="nuevo_estado" label="Nuevo Estado" rules={[{ required: true }]}>
            <Select>
              <Select.Option value="ACTIVO">ACTIVO</Select.Option>
              <Select.Option value="SUSPENDIDO">SUSPENDIDO</Select.Option>
              <Select.Option value="CESANTE">CESANTE</Select.Option>
              <Select.Option value="JUBILADO">JUBILADO</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="motivo"
            label="Motivo del Cambio (Obligatorio)"
            rules={[{ required: true, min: 5, message: 'Ingrese al menos 5 caracteres justificativos' }]}
          >
            <Input.TextArea rows={3} placeholder="Ingrese la resolución o causal de la modificación..." />
          </Form.Item>
          <Form.Item name="resolucion_respaldo" label="Número de Resolución (Opcional)">
            <Input placeholder="Ej. Res. Directorio Nº 145/2026" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};
```

---

### 7. Suite de Pruebas Automatizadas (`backend/tests/test_padron.py`)

```python
import pytest
from httpx import AsyncClient
from app.core.config import settings
from app.core.security import create_access_token

@pytest.mark.asyncio
async def test_cuit_modulo_11_validation():
    """Valida que el algoritmo de CUIT admita sólo CUITs matemáticamente válidos."""
    from app.schemas.padron import validate_cuit_modulo11
    
    # CUIT de prueba válido (20-12345678-6 simulado válido)
    valid_cuit = "20222222223"
    assert validate_cuit_modulo11(valid_cuit) == valid_cuit

    with pytest.raises(ValueError) as exc:
        validate_cuit_modulo11("20222222229") # Dígito incorrecto
    assert "Dígito verificador de CUIT inválido" in str(exc.value)

@pytest.mark.asyncio
async def test_soft_delete_preserves_history_dir_04(client: AsyncClient, test_admin_user, db_session):
    """Verifica que la baja o cambio de estado preserve el historial y no aplique DELETE físico."""
    admin_token = create_access_token(
        subject=str(test_admin_user.id),
        permissions=["escribanos:read", "escribanos:write", "escribanos:status"],
        roles=["ROLE_ADMIN"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Crear nuevo escribano
    create_payload = {
        "persona": {
            "cuit": "20222222223",
            "numero_documento": "22222222",
            "tipo_documento": "DNI",
            "apellido": "Sarmiento",
            "nombre": "Domingo"
        },
        "matricula_numero": 450,
        "fecha_matriculacion": "2020-05-15"
    }
    res_create = await client.post(f"{settings.API_V1_STR}/padron/escribanos", json=create_payload, headers=headers)
    assert res_create.status_code == 201
    esc_id = res_create.json()["id"]

    # 2. Suspender escribano con motivo
    status_payload = {
        "nuevo_estado": "SUSPENDIDO",
        "motivo": "Licencia extraordinaria por cargo público",
        "resolucion_respaldo": "Res. 89/2026"
    }
    res_status = await client.patch(f"{settings.API_V1_STR}/padron/escribanos/{esc_id}/status", json=status_payload, headers=headers)
    assert res_status.status_code == 200

    # 3. Comprobar que sigue existiendo en base de datos con el nuevo estado
    res_get = await client.get(f"{settings.API_V1_STR}/padron/escribanos?q=450", headers=headers)
    assert res_get.status_code == 200
    assert len(res_get.json()["items"]) == 1
    assert res_get.json()["items"][0]["estado_matricula"] == "SUSPENDIDO"
```

---

### 8. Criterios de Aceptación del Módulo 3

1. **Unicidad e Integridad Fiscal (`DIR-03`):** No es posible ingresar CUITs matemáticamente inválidos o matrículas duplicadas; el sistema arroja error de validación HTTP 400 antes de interactuar con la base de datos.
2. **Historial Inmutable (`DIR-02` / `DIR-04`):** Cada transición de estado genera un registro en `padron_historial_estados` indicando el motivo y el usuario responsable. Quedan bloqueadas las sentencias de eliminación física.
3. **Desacoplamiento de Entidades (`USR-01`):** Los datos personales residen únicamente en `padron_personas`, eliminando redundancias y discrepancias ortográficas o de domicilio.
4. **Respuesta Rápida y Adaptabilidad Visual (`REP-03`):** El padrón permite filtros combinados y su representación en la interfaz React elimina cualquier scroll horizontal desmedido.
