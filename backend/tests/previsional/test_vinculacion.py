"""Vínculo nombre de la planilla → escribano del padrón (sin base de datos)."""

import uuid

from app.modules.previsional.catalog import Vinculacion
from app.modules.previsional.vinculacion import Candidato, Vinculador, normalizar

A, B, C, D = (uuid.uuid4() for _ in range(4))


def _vinculador() -> Vinculador:
    return Vinculador(
        [
            Candidato(A, "Prueba Ana Sintética"),
            Candidato(B, "Ejemplo Gómez Luis Alberto"),
            Candidato(C, "Ficticio Pedro Santos"),
            Candidato(D, "Ficticio Pedro Sebastián"),
        ]
    )


def test_normalizar() -> None:
    assert normalizar("  MUÑOZ   de la  Peña, José-María. ") == "munoz de la pena jose maria"
    assert normalizar("...") == ""


def test_exacta_ignora_tildes_mayusculas_y_espacios() -> None:
    r = _vinculador().vincular("PRUEBA  ana SINTETICA")
    assert (r.escribano_id, r.vinculacion) == (A, Vinculacion.EXACTA)


def test_aproximada_solo_si_es_unica() -> None:
    r = _vinculador().vincular("EJEMPLO GOMEZ Luis")
    assert (r.escribano_id, r.vinculacion) == (B, Vinculacion.APROXIMADA)
    # La inicial vale por una palabra, pero acá hay dos «Ficticio Pedro S…»: no se vincula.
    ambiguo = _vinculador().vincular("FICTICIO Pedro S.")
    assert ambiguo.escribano_id is None and ambiguo.ambiguo
    unico = Vinculador([Candidato(C, "Ficticio Pedro Santos")]).vincular("FICTICIO Pedro S.")
    assert (unico.escribano_id, unico.vinculacion) == (C, Vinculacion.APROXIMADA)


def test_sin_coincidencia_o_insuficiente() -> None:
    v = _vinculador()
    assert v.vincular("OTRO Nombre").escribano_id is None
    assert not v.vincular("OTRO Nombre").ambiguo
    # Una sola palabra no identifica a nadie, aunque esté contenida.
    assert v.vincular("Ficticio").escribano_id is None
    assert v.vincular("  ").escribano_id is None
    # Una palabra de la planilla que no está en el padrón descarta el candidato.
    assert v.vincular("PRUEBA Ana María").escribano_id is None


def test_exacta_repetida_es_ambigua() -> None:
    v = Vinculador([Candidato(A, "Uno Dos"), Candidato(B, "UNO dos")])
    r = v.vincular("uno dos")
    assert r.escribano_id is None and r.ambiguo
