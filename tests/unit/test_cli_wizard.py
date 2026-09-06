"""Guided wizard: didactic prompts, pre-save validation ladder and its escape hatches."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nz_mcp.auth import get_password
from nz_mcp.cli import app
from nz_mcp.config import get_profile, list_profile_names, load_profiles_file
from nz_mcp.errors import ConnectionError as NzConnectionError
from nz_mcp.errors import CredentialNotFoundError

runner = CliRunner()

_GOOD_HOST = "nz.example.com"
_BAD_HOST = "unreachable.example.com"

_ROWS: dict[str, list[tuple[str, str]]] = {
    "databases": [("DB", "ADMIN")],
    "schemas": [("DBO", "ADMIN")],
}


def _kind(sql: str) -> str:
    upper = sql.upper()
    if "VERSION()" in upper:
        return "version"
    if "_V_DATABASE" in upper:
        return "databases"
    return "schemas"


class _Cursor:
    def __init__(self, rows: dict[str, list[tuple[str, str]]]) -> None:
        self._rows = rows
        self._kind = "version"

    def execute(self, sql: str, params: tuple[str | None, str | None] | None = None) -> None:
        self._kind = _kind(sql)

    def fetchone(self) -> tuple[str]:
        return ("NPS 11.2.1.11",)

    def fetchall(self) -> list[tuple[str, str]]:
        return self._rows.get(self._kind, [])

    def close(self) -> None:
        pass


class _Conn:
    def __init__(self, rows: dict[str, list[tuple[str, str]]]) -> None:
        self._rows = rows
        self.closed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self._rows)

    def close(self) -> None:
        self.closed = True


def _patch_connection(
    monkeypatch: pytest.MonkeyPatch,
    rows: dict[str, list[tuple[str, str]]] | None = None,
) -> None:
    """Connections to _BAD_HOST fail; every other host answers with ``rows``."""
    answer = _ROWS if rows is None else rows

    def _open(profile: object, _password: str) -> _Conn:
        host = getattr(profile, "host", "")
        if host == _BAD_HOST:
            raise NzConnectionError(
                host=host, port=5480, database="DB", user="svc", detail="no route to host"
            )
        return _Conn(answer)

    monkeypatch.setattr("nz_mcp.profile_check.open_connection", _open)


def _answers(
    *,
    host: str = _GOOD_HOST,
    port: str = "5480",
    database: str = "DB",
    user: str = "svc",
    password: str = "pw123456",  # noqa: S107 - fixture value, not a real credential
    mode: str = "read",
    security: str = "2",
    ca_certs: str = "",
    validate: str = "y",
    extra: tuple[str, ...] = (),
) -> str:
    """Render the answers in prompt order, ending with the post-failure choices."""
    steps = [host, port, database, user, password, password, mode, security, ca_certs, validate]
    steps.extend(extra)
    return "\n".join(steps) + "\n"


@pytest.fixture(autouse=True)
def spanish_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NZ_MCP_LANG", "es")


def test_wizard_explains_mode_and_security_before_asking(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    result = runner.invoke(app, ["add-profile", "dev"], input=_answers())
    assert result.exit_code == 0
    out = result.stderr
    assert "El modo limita lo que la IA podrá hacer" in out
    assert "'admin' añade DDL" in out
    assert "El nivel de seguridad decide si la conexión viaja cifrada" in out
    assert "bundle CA" in out


def test_wizard_persists_security_level_and_ca_certs(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    result = runner.invoke(
        app, ["add-profile", "dev"], input=_answers(security="3", ca_certs="/etc/ssl/nz.pem")
    )
    assert result.exit_code == 0
    profile = get_profile("dev", path=tmp_profiles)
    assert profile.security_level == 3
    assert profile.ca_certs == "/etc/ssl/nz.pem"


def test_wizard_skips_ca_certs_on_empty_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    result = runner.invoke(app, ["add-profile", "dev"], input=_answers())
    assert result.exit_code == 0
    assert get_profile("dev", path=tmp_profiles).ca_certs is None


def test_wizard_reprompts_invalid_security_level(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    result = runner.invoke(app, ["add-profile", "dev"], input=_answers(security="9\n2"))
    assert result.exit_code == 0
    assert "Nivel de seguridad inválido" in result.stdout + result.stderr
    assert get_profile("dev", path=tmp_profiles).security_level == 2


def test_wizard_reprompts_invalid_mode(monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path) -> None:
    _patch_connection(monkeypatch)
    result = runner.invoke(app, ["add-profile", "dev"], input=_answers(mode="root\nwrite"))
    assert result.exit_code == 0
    assert "Modo inválido" in result.stdout + result.stderr
    assert get_profile("dev", path=tmp_profiles).mode == "write"


def test_wizard_reports_the_three_levels_and_prints_the_claude_config(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    result = runner.invoke(app, ["add-profile", "dev", "--active"], input=_answers())
    assert result.exit_code == 0
    ladder = result.stderr
    assert "1/3 Conexión: OK" in ladder
    assert "2/3 Lectura del catálogo: OK" in ladder
    assert "3/3 Visibilidad en DB: OK" in ladder
    assert "los tres niveles han pasado" in ladder
    assert "nz-mcp probe-catalog --profile dev" in ladder
    # The snippet is payload: it stays on stdout so it can be redirected to a file.
    assert '"NZ_MCP_PROFILE": "dev"' in result.stdout
    assert get_password("dev") == "pw123456"


def test_wizard_can_skip_validation_entirely(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    result = runner.invoke(app, ["add-profile", "dev"], input=_answers(validate="n"))
    assert result.exit_code == 0
    assert "Validación omitida" in result.stderr
    assert "1/3" not in result.stdout + result.stderr
    assert list_profile_names(tmp_profiles) == ["dev"]


def test_connect_failure_lets_the_user_save_anyway(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    result = runner.invoke(
        app, ["add-profile", "dev"], input=_answers(host=_BAD_HOST, extra=("g",))
    )
    assert result.exit_code == 0
    combined = result.stdout + result.stderr
    assert "1/3 Conexión: FALLA" in combined
    assert "no route to host" in combined
    assert "2/3 Lectura del catálogo: omitido" in combined
    assert "Guardado pese al fallo de validación" in combined
    assert get_profile("dev", path=tmp_profiles).host == _BAD_HOST
    assert get_password("dev") == "pw123456"


def test_cancelling_after_a_failure_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    result = runner.invoke(
        app, ["add-profile", "dev"], input=_answers(host=_BAD_HOST, extra=("x",))
    )
    assert result.exit_code == 1
    assert "Cancelado" in result.stdout + result.stderr
    assert list_profile_names(tmp_profiles) == []
    with pytest.raises(CredentialNotFoundError):
        get_password("dev")


def test_fixing_one_field_keeps_every_other_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    result = runner.invoke(
        app,
        ["add-profile", "dev"],
        input=_answers(host=_BAD_HOST, extra=("c", "host", _GOOD_HOST)),
    )
    assert result.exit_code == 0
    profile = get_profile("dev", path=tmp_profiles)
    assert profile.host == _GOOD_HOST
    # Nothing else was asked again: database, user and password survived the failure.
    assert profile.database == "DB"
    assert profile.user == "svc"
    assert get_password("dev") == "pw123456"


def test_retry_after_a_failure_reruns_the_ladder(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    result = runner.invoke(
        app, ["add-profile", "dev"], input=_answers(host=_BAD_HOST, extra=("r", "g"))
    )
    assert result.exit_code == 0
    combined = result.stdout + result.stderr
    assert combined.count("1/3 Conexión: FALLA") == 2
    assert get_profile("dev", path=tmp_profiles).host == _BAD_HOST


def test_invalid_menu_choice_is_rejected_without_losing_data(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    result = runner.invoke(
        app, ["add-profile", "dev"], input=_answers(host=_BAD_HOST, extra=("z", "g"))
    )
    assert result.exit_code == 0
    assert "Opción no válida" in result.stdout + result.stderr
    assert get_profile("dev", path=tmp_profiles).user == "svc"


def test_unknown_field_name_is_rejected_and_asked_again(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    result = runner.invoke(
        app,
        ["add-profile", "dev"],
        input=_answers(host=_BAD_HOST, extra=("c", "hostname", "host", _GOOD_HOST)),
    )
    assert result.exit_code == 0
    assert "Campo desconocido" in result.stdout + result.stderr
    assert get_profile("dev", path=tmp_profiles).host == _GOOD_HOST


def test_catalog_read_without_databases_is_explained(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch, {"databases": [], "schemas": []})
    result = runner.invoke(app, ["add-profile", "dev"], input=_answers(extra=("g",)))
    assert result.exit_code == 0
    combined = result.stdout + result.stderr
    assert "1/3 Conexión: OK" in combined
    assert "2/3 Lectura del catálogo: FALLA" in combined
    assert "no tiene permisos reales de lectura" in combined
    assert "3/3 Visibilidad en DB: omitido" in combined


def test_default_database_without_schemas_is_explained(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch, {"databases": [("DB", "ADMIN")], "schemas": []})
    result = runner.invoke(app, ["add-profile", "dev"], input=_answers(extra=("g",)))
    assert result.exit_code == 0
    combined = result.stdout + result.stderr
    assert "2/3 Lectura del catálogo: OK" in combined
    assert "3/3 Visibilidad en DB: FALLA" in combined
    assert "no ve ningún esquema" in combined


def test_overwriting_defaults_to_the_current_values(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    # Only the host is retyped; every other prompt is accepted with its default.
    keep = _answers(
        host="nz-new.example.com",
        port="",
        database="",
        user="",
        mode="",
        security="",
        ca_certs="",
    )
    result = runner.invoke(app, ["add-profile", "dev"], input="y\n" + keep)
    assert result.exit_code == 0
    profile = get_profile("dev", path=two_profiles)
    assert profile.host == "nz-new.example.com"
    assert profile.database == "DEV"
    assert profile.user == "svc_dev"
    assert profile.mode == "read"


def test_init_uses_the_same_guided_wizard(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    result = runner.invoke(app, ["init"], input="lab\n" + _answers())
    assert result.exit_code == 0
    assert "primer perfil" in result.stderr
    assert list_profile_names(tmp_profiles) == ["lab"]
    assert load_profiles_file(tmp_profiles).active == "lab"


@pytest.mark.parametrize(
    ("field", "answers", "attribute", "expected"),
    [
        ("port", ("5481",), "port", 5481),
        ("database", ("OTHER",), "database", "OTHER"),
        ("user", ("svc2",), "user", "svc2"),
        ("mode", ("admin",), "mode", "admin"),
        ("security_level", ("3",), "security_level", 3),
        ("ca_certs", ("/etc/ssl/nz.pem",), "ca_certs", "/etc/ssl/nz.pem"),
    ],
)
def test_every_field_can_be_fixed_after_a_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_profiles: Path,
    field: str,
    answers: tuple[str, ...],
    attribute: str,
    expected: object,
) -> None:
    _patch_connection(monkeypatch)
    extra = ("c", field, *answers, "g")
    result = runner.invoke(app, ["add-profile", "dev"], input=_answers(host=_BAD_HOST, extra=extra))
    assert result.exit_code == 0
    assert getattr(get_profile("dev", path=tmp_profiles), attribute) == expected


def test_password_can_be_fixed_after_a_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _patch_connection(monkeypatch)
    extra = ("c", "password", "newpw12345", "newpw12345", "g")
    result = runner.invoke(app, ["add-profile", "dev"], input=_answers(host=_BAD_HOST, extra=extra))
    assert result.exit_code == 0
    assert get_password("dev") == "newpw12345"
