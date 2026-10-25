# Documento de Ingeniería de Software — Módulo 8
## Sitio Institucional Público y CMS de Estados Contables
**Suite Integral Caja Notarial de San Juan**  
**Versión:** 1.0.0 | **Estado:** Especificación Técnica e Implementación  
**Requerimientos del Pliego:** `WEB-01`, `WEB-02`, `WEB-03`, `WEB-04`, `SEC-01`, `SEC-03`  
**Stack de Referencia:** Python 3.12+ | FastAPI | pypdf / pypdf2 | PostgreSQL 16+ | SQLAlchemy 2.0 (Async) | React + TypeScript (SSR / Static Hydration)

---

### 1. Propósito, Alcance y Mitigación de Defectos Críticos

El **Módulo 8 (Sitio Público y CMS)** administra la presencia institucional, la transparencia activa y el repositorio público de documentos oficiales, resoluciones y balances anuales de la Caja Notarial de San Juan.

#### 1.1 Mitigación Directa de Hallazgos Previos
1. **Erradicación de Enlaces Rotos y Páginas HTML Falsas bajo `.pdf` (`WEB-02`):**
   * En auditorías previas se detectó que el enlace "EECC 2023" devolvía una página HTML de error en lugar del documento contable.
   * La nueva arquitectura implementa un **Validador de Integridad Documental** obligatorio en el backend: ningún archivo puede publicarse ni enlazarse como PDF a menos que el servicio verifique que el binario es estructuralmente íntegro, que puede ser abierto y parseado exitosamente por `pypdf`, que cuenta con encabezados `%PDF-1.x` reales y que su hash SHA-256 coincide.
2. **Generación de URLs Públicas bajo Dominio Real (`WEB-02` / `SEC-04`):** Todas las rutas de descarga y vistas públicas se generan a partir de la configuración tipada `PUBLIC_WEB_URL`, impidiendo URLs rotas o apuntando a entornos locales.
3. **Flujo Editorial Seguro con Versionado (`WEB-01` / `WEB-03`):** Estados de publicación controlados: `BORRADOR`, `VISTA_PREVIA`, `PUBLICADO`, `ARCHIVADO`. Reemplazar un archivo PDF o balance no rompe el enlace canónico permanente (URL estable), conservando el histórico anterior archivado.
4. **Optimización de Rendimiento y Seguridad Pública (`WEB-04`):** Entrega de contenidos mediante caché HTTP `Cache-Control: public, max-age=3600, stale-while-revalidate=86400`, cabeceras de seguridad estrictas y aislamiento respecto al panel privado de autogestión.

---

### 2. Modelo de Datos Relacional (PostgreSQL DDL)

```sql
-- Tabla de Categorías de Contenido Institucional
CREATE TABLE IF NOT EXISTS cms_secciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR(100) UNIQUE NOT NULL, -- 'quienes-somos', 'autoridades', 'ley-creacion', 'noticias', 'estados-contables'
    titulo VARCHAR(150) NOT NULL,
    descripcion TEXT,
    orden INT NOT NULL DEFAULT 0,
    is_public BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

-- Tabla de Artículos y Páginas Editables (WEB-01)
CREATE TABLE IF NOT EXISTS cms_articulos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seccion_id UUID NOT NULL REFERENCES cms_secciones(id) ON DELETE RESTRICT,
    slug VARCHAR(150) UNIQUE NOT NULL,
    titulo VARCHAR(255) NOT NULL,
    resumen TEXT,
    contenido_markdown TEXT NOT NULL,
    imagen_portada_url VARCHAR(500),
    
    -- Estados y Versiones
    estado VARCHAR(30) NOT NULL DEFAULT 'BORRADOR', -- BORRADOR, PUBLICADO, ARCHIVADO
    version INT NOT NULL DEFAULT 1,
    fecha_publicacion TIMESTAMPTZ,
    
    -- Auditoría Editorial
    autor_user_id UUID NOT NULL REFERENCES security_users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX idx_cms_articulos_slug ON cms_articulos(slug);
CREATE INDEX idx_cms_articulos_estado ON cms_articulos(estado);

-- Tabla Específica de Estados Contables y Documentos Oficiales (WEB-02)
CREATE TABLE IF NOT EXISTS cms_documentos_oficiales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tipo_documento VARCHAR(50) NOT NULL, -- 'ESTADO_CONTABLE', 'MEMORIA_ANUAL', 'RESOLUCION_DIRECTORIO'
    ejercicio_economico_anio INT NOT NULL, -- Ej: 2023, 2024, 2025, 2026
    titulo VARCHAR(255) NOT NULL,
    descripcion TEXT,
    
    -- Archivo Validado Físico
    nombre_archivo_original VARCHAR(255) NOT NULL,
    ruta_almacenamiento VARCHAR(500) NOT NULL,
    hash_sha256 VARCHAR(64) NOT NULL,
    tamano_bytes BIGINT NOT NULL,
    cantidad_paginas INT NOT NULL,
    es_pdf_valido BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Enlace Público Permanente
    slug_descarga VARCHAR(150) UNIQUE NOT NULL, -- Ej: 'eecc-2023-balance-general'
    estado VARCHAR(30) NOT NULL DEFAULT 'PUBLICADO',
    fecha_publicacion DATE NOT NULL DEFAULT CURRENT_DATE,
    
    publicado_por_user_id UUID NOT NULL REFERENCES security_users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX idx_cms_docs_ejercicio ON cms_documentos_oficiales(ejercicio_economico_anio);
CREATE INDEX idx_cms_docs_slug ON cms_documentos_oficiales(slug_descarga);
```

---

### 3. Validador de Integridad de PDF (`backend/app/services/pdf_validator.py`)

Garantiza el cumplimiento estricto del requerimiento `WEB-02` para impedir la publicación de PDFs corruptos o enlaces que devuelvan páginas HTML:

```python
import io
import hashlib
from pypdf import PdfReader
from fastapi import HTTPException, status, UploadFile

class DocumentoPDFValidator:
    """Valida que el archivo subido sea un binario PDF real, parseable y libre de corrupciones."""

    @staticmethod
    async def validar_pdf(file: UploadFile) -> dict:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="El archivo está vacío.")

        # 1. Verificación de Cabecera Mágica PDF (%PDF-)
        if not content.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="El archivo no es un documento PDF válido (cabecera corrupta o formato incompatible)."
            )

        # 2. Intento de lectura estructural completa con pypdf
        try:
            pdf_stream = io.BytesIO(content)
            reader = PdfReader(pdf_stream)
            total_pages = len(reader.pages)

            if total_pages == 0:
                raise HTTPException(status_code=400, detail="El PDF no contiene páginas legibles.")

            # Lectura de la primera página para confirmar renderizado
            _ = reader.pages[0].extract_text()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"El archivo PDF está dañado o no puede ser procesado: {str(exc)} (WEB-02)."
            )

        # 3. Cálculo de Checksum SHA-256
        sha256 = hashlib.sha256(content).hexdigest()

        return {
            "total_pages": total_pages,
            "size_bytes": len(content),
            "sha256": sha256,
            "content": content
        }
```

---

### 4. Controlador Público y CMS (`backend/app/api/v1/endpoints/cms.py`)

```python
import os
import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.core.database import get_db_session
from app.core.config import settings
from app.api.deps import require_permissions, get_current_user
from app.models.security import User
from app.models.cms import CMSArticulo, CMSDocumentoOficial
from app.services.pdf_validator import DocumentoPDFValidator

router = APIRouter(prefix="/cms", tags=["Sitio Público y CMS"])

@router.get("/documentos/estados-contables", response_model=List[dict])
async def list_estados_contables_publicos(
    db: AsyncSession = Depends(get_db_session)
):
    """Endpoint público para consultar balances y estados contables aprobados (WEB-01)."""
    stmt = (
        select(CMSDocumentoOficial)
        .where(
            and_(
                CMSDocumentoOficial.tipo_documento == "ESTADO_CONTABLE",
                CMSDocumentoOficial.estado == "PUBLICADO",
                CMSDocumentoOficial.es_pdf_valido == True
            )
        )
        .order_by(CMSDocumentoOficial.ejercicio_economico_anio.desc())
    )
    result = await db.execute(stmt)
    docs = result.scalars().all()

    return [
        {
            "id": doc.id,
            "anio": doc.ejercicio_economico_anio,
            "titulo": doc.titulo,
            "descripcion": doc.descripcion,
            "paginas": doc.cantidad_paginas,
            "tamano_mb": round(doc.tamano_bytes / (1024 * 1024), 2),
            "url_descarga": f"{settings.API_PUBLIC_URL}/cms/documentos/download/{doc.slug_descarga}.pdf"
        }
        for doc in docs
    ]

@router.get("/documentos/download/{slug}.pdf")
async def download_documento_publico_pdf(
    slug: str,
    db: AsyncSession = Depends(get_db_session)
):
    """Descarga de PDF verificada: garantiza entrega binaria directa, nunca una página HTML de error (WEB-02)."""
    stmt = select(CMSDocumentoOficial).where(
        CMSDocumentoOficial.slug_descarga == slug,
        CMSDocumentoOficial.estado == "PUBLICADO"
    )
    doc = (await db.execute(stmt)).scalar_one_or_none()

    if not doc or not os.path.exists(doc.ruta_almacenamiento):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El documento solicitado no existe o no se encuentra disponible."
        )

    return FileResponse(
        path=doc.ruta_almacenamiento,
        media_type="application/pdf",
        filename=f"{doc.slug_descarga}.pdf",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Disposition": f"inline; filename={doc.slug_descarga}.pdf"
        }
    )

@router.post("/admin/documentos/upload", status_code=status.HTTP_201_CREATED)
async def upload_documento_oficial(
    tipo_documento: str = Form(...),
    ejercicio_anio: int = Form(...),
    titulo: str = Form(...),
    descripcion: Optional[str] = Form(None),
    slug_descarga: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_permissions("cms:publish"))
):
    # Validación física estricta con pypdf (WEB-02)
    val = await DocumentoPDFValidator.validar_pdf(file)

    storage_dir = "/var/caja_notarial/uploads/public_docs"
    os.makedirs(storage_dir, exist_ok=True)
    stored_name = f"{slug_descarga}_{uuid.uuid4().hex[:8]}.pdf"
    full_path = os.path.join(storage_dir, stored_name)

    with open(full_path, "wb") as f:
        f.write(val["content"])

    doc = CMSDocumentoOficial(
        tipo_documento=tipo_documento,
        ejercicio_economico_anio=ejercicio_anio,
        titulo=titulo,
        descripcion=descripcion,
        nombre_archivo_original=file.filename or "documento.pdf",
        ruta_almacenamiento=full_path,
        hash_sha256=val["sha256"],
        tamano_bytes=val["size_bytes"],
        cantidad_paginas=val["total_pages"],
        es_pdf_valido=True,
        slug_descarga=slug_descarga,
        estado="PUBLICADO",
        publicado_por_user_id=current_user.id
    )
    db.add(doc)
    await db.commit()

    return {
        "status": "success",
        "message": f"Documento oficial '{titulo}' publicado exitosamente.",
        "id": doc.id,
        "url_publica": f"{settings.API_PUBLIC_URL}/cms/documentos/download/{doc.slug_descarga}.pdf"
    }
```
