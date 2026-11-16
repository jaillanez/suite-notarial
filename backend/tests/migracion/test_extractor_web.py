"""Extracción de los actos del sitio web anterior (volcado MySQL) a `actos.csv`.

El volcado es sintético: misma estructura que el del proveedor anterior, con registros y
escribanos del lote sintético. Nunca datos reales.
"""

import csv
from collections.abc import Callable
from pathlib import Path

import pytest

from app.modules.migracion import extractor_web, formato, homologacion
from app.modules.migracion.validacion import Existentes, validar


def _leer(directorio: Path, archivo: str) -> list[dict[str, str]]:
    with (directorio / archivo).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def _sql(valor: str | None) -> str:
    if valor is None:
        return "NULL"
    return "'" + valor.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n") + "'"


def _insert(tabla: str, columnas: list[str], filas: list[list[str | None]]) -> str:
    cols = ", ".join(f"`{c}`" for c in columnas)
    valores = ",\n".join("(" + ", ".join(_sql(v) for v in fila) + ")" for fila in filas)
    return f"INSERT INTO `{tabla}` ({cols}) VALUES\n{valores};\n"


DETALLE = [
    "id",
    "id_ddjj_aporte",
    "tipo_protocolo",
    "escritura_nro",
    "escritura_folio",
    "fecha",
    "naturaleza_acto",
    "base_imponible",
    "aporte_porcentaje",
    "aporte_fijo",
    "aporte_excento",
    "idnotario",
    "notario_autorizado",
    "aporte_titular",
    "aporte_adscripto",
    "aporte_a_cargo",
    "fecha_gra",
    "estado",
]


@pytest.fixture
def base(lote: Callable[..., Path]) -> Path:
    return lote("base", actos=False)


def _volcado(base: Path, tmp_path: Path) -> Path:
    escribanos = _leer(base, "escribanos.csv")
    con_cuit = [e for e in escribanos if e["cuit"]]
    primero, segundo, tercero = con_cuit[0], con_cuit[1], con_cuit[2]
    # Nombre único en el lote (los sintéticos se repiten): el de la coincidencia por nombre.
    tercero["apellido"], tercero["nombre"] = "Únicoapellido", "Nombre Único"
    with (base / "escribanos.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(escribanos[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(escribanos)
    # El sitio tiene al segundo con otro prefijo de CUIT (mismo documento) y al tercero con un
    # CUIT que la Caja no tiene, pero con el mismo nombre.
    cuit_prefijo = ("27" if segundo["cuit"][:2] != "27" else "20") + segundo["cuit"][2:]
    cuit_otro = "20999999993"
    sql = [
        "-- volcado sintético\nSET NAMES utf8mb4;\n",
        _insert(
            "registro_notarial",
            ["id", "domicilio", "telefono", "email", "numero", "estado"],
            [["1", "Calle; con punto y coma", "", "", " 700", "1"], ["2", "", "", "", "701", "1"]],
        ),
        _insert(
            "sitio_web_personas",
            ["id", "cuit", "apellido", "nombre", "clave"],
            [
                ["1", cuit_otro, "UNICOAPELLIDO", "nombre unico", "no-se-migra"],
                ["2", "20888888885", "Desconocido", "Nadie", None],
            ],
        ),
        _insert(
            "ddjj_aportes",
            ["id", "idregistronotarial", "cuit_notario", "anio", "mes", "boleta_generada"],
            [
                ["10", "1", primero["cuit"], "2026", "8", "1"],
                ["11", "2", segundo["cuit"], "2026", "09", "1"],
                ["12", "2", segundo["cuit"], "2026", "10", "0"],  # borrador
            ],
        ),
        _insert(
            "ddjj_aportes_detalles",
            DETALLE,
            [
                # Venta con base, del primero por CUIT; texto con comillas y salto de línea.
                [
                    "1",
                    "10",
                    "1",
                    "5",
                    "12",
                    "2026-08-03",
                    "VENTA O'NEILL\ny cesión",
                    "1000000.00",
                    "4000.00",
                    "0.00",
                    "0",
                    primero["cuit"],
                    "Titular",
                    "4000.00",
                    "0.00",
                    "0.00",
                    "",
                    "0",
                ],
                # Poder del segundo, por documento (otro prefijo de CUIT).
                [
                    "2",
                    "11",
                    "2",
                    "6",
                    "13",
                    "0000-00-00",
                    "PODER",
                    "0.00",
                    "0.00",
                    "7130.00",
                    "0",
                    cuit_prefijo,
                    "Adscripto",
                    "0.00",
                    "7130.00",
                    "0.00",
                    "",
                    "0",
                ],
                # Del tercero, por nombre del sitio.
                [
                    "3",
                    "11",
                    "1",
                    "7",
                    "14",
                    "2026-09-10",
                    "HIPOTECA",
                    "0.00",
                    "0.00",
                    "0.00",
                    "1",
                    cuit_otro,
                    "A Cargo",
                    "0.00",
                    "0.00",
                    "0.00",
                    "",
                    "0",
                ],
                # Escribano que no se identifica: queda «a completar».
                [
                    "4",
                    "11",
                    "1",
                    "8",
                    "15",
                    "2026-09-11",
                    "DONACION",
                    "0.00",
                    "0.00",
                    "5000.00",
                    "0",
                    "20888888885",
                    "Titular",
                    "5000.00",
                    "0.00",
                    "0.00",
                    "",
                    "0",
                ],
                # Borrado en el origen, renglón vacío y acto de un borrador: no se migran.
                [
                    "5",
                    "10",
                    "1",
                    "9",
                    "16",
                    "2026-08-04",
                    "BORRADO",
                    "0.00",
                    "0.00",
                    "10.00",
                    "0",
                    primero["cuit"],
                    "Titular",
                    "10.00",
                    "0.00",
                    "0.00",
                    "",
                    "1",
                ],
                [
                    "6",
                    "10",
                    "",
                    "",
                    "",
                    "2026-08-30",
                    "",
                    "0.00",
                    "0.00",
                    "0.00",
                    "0",
                    primero["cuit"],
                    "Titular",
                    "0.00",
                    "0.00",
                    "0.00",
                    "",
                    "0",
                ],
                [
                    "7",
                    "12",
                    "1",
                    "1",
                    "1",
                    "2026-10-01",
                    "EN BORRADOR",
                    "0.00",
                    "0.00",
                    "99.00",
                    "0",
                    segundo["cuit"],
                    "Titular",
                    "99.00",
                    "0.00",
                    "0.00",
                    "",
                    "0",
                ],
            ],
        ),
    ]
    archivo = tmp_path / "volcado.sql"
    archivo.write_text("".join(sql), encoding="utf-8")
    return archivo


def test_lee_los_insert_sin_ejecutarlos() -> None:
    texto = _insert("t", ["a", "b", "c"], [["1", "x'y, (z)\nw", None], ["2", "\\", "3"]])
    filas = extractor_web.leer_volcado(texto, ("t",))["t"]
    assert filas == [{"a": "1", "b": "x'y, (z)\nw", "c": ""}, {"a": "2", "b": "\\", "c": "3"}]
    with pytest.raises(extractor_web.VolcadoInvalidoError):
        extractor_web.leer_volcado("INSERT INTO `t` (`a`) VALUES ('sin cerrar", ("t",))


def test_arma_el_lote_con_los_actos(base: Path, tmp_path: Path) -> None:
    salida = tmp_path / "v5"
    resumen = extractor_web.armar_lote(_volcado(base, tmp_path), base, salida)
    assert (resumen.actos, resumen.declaraciones) == (4, 2)
    assert (resumen.borrados, resumen.de_borradores, resumen.vacios) == (1, 1, 1)
    assert resumen.escribano_por_cuit == 1
    assert resumen.escribano_por_documento == 1
    assert resumen.escribano_por_nombre == 1
    assert resumen.escribano_a_completar == 1
    assert str(resumen.importe) == "16130.00"

    actos = {a["codigo_legado"]: a for a in _leer(salida, "actos.csv")}
    assert set(actos) == {"ACT-WEB-1", "ACT-WEB-2", "ACT-WEB-3", "ACT-WEB-4"}
    venta = actos["ACT-WEB-1"]
    assert venta["numero_registro"] == "700"
    assert venta["periodo"] == "2026-08"
    assert venta["naturaleza"] == "VENTA O'NEILL y cesión"
    assert (venta["base_imponible"], venta["aporte_variable"], venta["aporte_fijo"]) == (
        "1000000.00",
        "4000.00",
        "",
    )
    assert venta["tipo_protocolo"] == "GENERAL"
    assert actos["ACT-WEB-2"]["fecha_acto"] == ""
    assert actos["ACT-WEB-2"]["tipo_protocolo"] == "AUXILIAR"
    assert actos["ACT-WEB-3"]["exento"] == "SI"
    assert actos["ACT-WEB-4"]["escribano"] == ""
    assert actos["ACT-WEB-4"]["escribano_origen"] == "Desconocido, Nadie (CUIT 20888888885)"

    # El resto del lote es el de base, y control.csv declara los actos.
    for archivo in ("registros.csv", "boletas.csv", "pagos.csv"):
        assert (salida / archivo).read_bytes() == (base / archivo).read_bytes()
    control = {f["entidad"]: f for f in _leer(salida, "control.csv")}
    assert (control["actos"]["filas"], control["actos"]["importe"]) == ("4", "16130.00")

    # El lote armado valida: los cuatro actos se cargan.
    st = validar(formato.leer_lote(salida), homologacion.cargar(), Existentes())
    assert st.bloqueantes() == 0
    assert {a.codigo for a in st.actos} == set(actos)
    assert {a.codigo for a in st.actos if a.escribano is None} == {"ACT-WEB-4"}
    assert next(a for a in st.actos if a.codigo == "ACT-WEB-3").cargo == "SUPLENTE_INTERINO"


def test_no_pisa_un_lote(base: Path, lote: Callable[..., Path], tmp_path: Path) -> None:
    volcado = _volcado(base, tmp_path)
    salida = tmp_path / "ocupado"
    salida.mkdir()
    (salida / "algo.csv").write_text("x", encoding="utf-8")
    with pytest.raises(extractor_web.VolcadoInvalidoError, match="directorio vacío"):
        extractor_web.armar_lote(volcado, base, salida)
    with pytest.raises(extractor_web.VolcadoInvalidoError, match="ya trae actos"):
        extractor_web.armar_lote(volcado, lote("con"), tmp_path / "otro")


def test_consola(base: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    volcado = _volcado(base, tmp_path)
    argumentos = ["--volcado", str(volcado), "--lote-base", str(base)]
    assert extractor_web.main([*argumentos, "--salida", str(tmp_path / "v5")]) == 0
    salida = capsys.readouterr().out
    assert "actos: 4 en 2 DDJJ presentadas" in salida
    assert "a completar: Desconocido, Nadie (CUIT 20888888885): 1" in salida
