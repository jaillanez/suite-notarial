import pytest

from app.modules.iam.passwords import WeakPasswordError, check_password_policy


def test_password_policy_messages() -> None:
    with pytest.raises(WeakPasswordError) as contains:
        check_password_policy("Escribano-Nueva-2026!", email="escribano@suite-notarial.example")
    assert str(contains.value) == "La contraseña no puede contener tu usuario de correo."

    with pytest.raises(WeakPasswordError) as weak:
        check_password_policy("corta")
    assert str(weak.value).startswith("La contraseña debe tener al menos 10 caracteres")
