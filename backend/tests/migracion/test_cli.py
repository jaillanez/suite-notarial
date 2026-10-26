"""Consola de la migración: lo que no escribe en la base."""

from pathlib import Path

import pytest

from app.modules.migracion import cli


def test_genera_un_lote_sintetico(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["sintetico", "--salida", str(tmp_path), "--registros", "3"]) == 0
    assert {p.name for p in tmp_path.iterdir()} == {
        "registros.csv",
        "escribanos.csv",
        "cargos.csv",
        "boletas.csv",
        "pagos.csv",
        "control.csv",
    }
    assert "Lote sintético" in capsys.readouterr().out


def test_la_reversa_exige_confirmacion(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["reversa", "--respaldo", str(tmp_path / "x.dump")]) == 2
    assert "--confirmo-reversa" in capsys.readouterr().err


def test_lote_invalido_no_toca_la_base(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cli.main(["simulacro", "--lote", str(tmp_path), "--operador", "nadie@ejemplo.test"])
    assert codigo == 2
    assert "Falta registros.csv" in capsys.readouterr().err
