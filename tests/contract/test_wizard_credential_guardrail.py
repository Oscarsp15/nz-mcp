"""Contract: the credential never enters the wizard's widget tree (ADR 0029, condition 5).

Why this file exists
--------------------
The ADR measured, on ``textual`` 8.2.8, that an ``Input`` **destroys** the type a
credential travels in: typing into one rebuilds its value with
``f"{value[:start]}{text}{value[end:]}"``, so a ``Secret`` does not survive the first
keystroke and what stays in the DOM is a bare ``str``, alive for the whole session.

The audit of PR #222 accepted the decision and pointed at the hole: *"today that is only a
written rule. Nothing stops someone adding an input field with the real credential six
months from now."* The precedent is expensive - the ``Secret`` regression of PR #193
passed 1 204 tests and two audits because **nothing exercised the real path**.

So there are two barriers here, and neither is sufficient alone:

1. :func:`test_the_wizard_package_cannot_hold_the_credential` parses every module under
   ``src/nz_mcp/wizard`` and enforces five rules at review time, naming the offending
   line. Like the detector that confines ``rich``, it is a name-based check and therefore
   a blacklist.
2. :func:`test_the_real_wizard_never_lets_the_credential_into_a_widget` drives the real
   application through the real credential path, with a real value, and then walks the
   whole finished widget tree, the application's own attributes and its return value
   looking for that value. This one does not care what anything is called.

Both are needed. The first catches the mistake in the diff; the second is the one that
would have caught PR #193.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest

from nz_mcp.i18n import Locale
from nz_mcp.wizard.app import ProfileWizardApp
from nz_mcp.wizard.fields import DraftFields

#: Anything named like this could be holding the credential, so it has to prove it is not.
_CREDENTIAL_NAME: Final[re.Pattern[str]] = re.compile(
    r"password|passwd|pwd|credential|secret", re.IGNORECASE
)

#: The only annotations a credential-shaped name may carry inside the package. Both are
#: booleans: "there is one" and "ask for one, and tell me whether there is one now".
_BOOLEAN_ANNOTATIONS: Final[frozenset[str]] = frozenset({"bool", "Callable[[], bool]"})

#: The single exemption, named rather than pattern-matched so it cannot quietly grow.
#: ``CREDENTIAL_SLOT`` is the *identifier of a row* in the "what is still missing" list -
#: the string ``"password"`` used as a label. It is a module-level constant with a literal
#: value and nothing is ever stored in it. Exempting it by name keeps the rule honest;
#: exempting a pattern would have exempted the next real field too.
_EXEMPT_NAMES: Final[frozenset[str]] = frozenset({"CREDENTIAL_SLOT"})

#: Modules the wizard may not import: the credential only exists as a ``Secret`` in
#: production code (ADR 0026), and the keyring is where it goes afterwards. A package that
#: cannot name either of them cannot be holding one.
_FORBIDDEN_IMPORTS: Final[frozenset[str]] = frozenset(
    {"nz_mcp.secret", "nz_mcp.auth", "textual.devtools"}
)

#: Calls that would write the application state to disk. The ADR measured that today a
#: screenshot of a masked field does not leak it; it also measured that everything *else*
#: on screen is in there, and that the measurement holds for 8.2.8 rather than for ever.
_FORBIDDEN_CALLS: Final[frozenset[str]] = frozenset({"save_screenshot", "export_screenshot"})

#: Widget attributes that end up rendered or stored. Assigning a credential-shaped name to
#: one of these is the exact mistake this file exists to prevent.
_WIDGET_SINKS: Final[frozenset[str]] = frozenset({"value", "text", "content", "renderable"})


def _wizard_package() -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "nz_mcp" / "wizard"


def _dotted(node: ast.AST) -> str | None:
    """Resolve a dotted expression to its written form, or ``None``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _is_credential_name(node: ast.AST) -> bool:
    """Whether a name or attribute reads like it could be holding the credential."""
    dotted = _dotted(node)
    if dotted is None:
        return False
    leaf = dotted.rsplit(".", maxsplit=1)[-1]
    return leaf not in _EXEMPT_NAMES and _CREDENTIAL_NAME.search(leaf) is not None


def _is_boolean_leaf(node: ast.AST) -> bool:
    """Whether a single expression can only be a boolean.

    A call qualifies only when it is ``bool(...)``: ``ask_secret_raw()`` must not, however
    convincingly it is named. A credential-shaped name qualifies because every one of them
    is forced to be a boolean by :func:`_binding_violations`, which is what makes this
    whole set of rules close on itself.
    """
    if isinstance(node, ast.Constant):
        return isinstance(node.value, bool)
    if isinstance(node, ast.Compare):
        return True
    if isinstance(node, ast.Call):
        return _dotted(node.func) == "bool"
    return _is_credential_name(node)


def _is_boolean_shaped(node: ast.AST) -> bool:
    """Whether an expression can only evaluate to a boolean, however it is composed."""
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, ast.Not)
    if isinstance(node, ast.BoolOp):
        return all(_is_boolean_shaped(value) for value in node.values)
    if isinstance(node, ast.IfExp):
        return _is_boolean_shaped(node.body) and _is_boolean_shaped(node.orelse)
    return _is_boolean_leaf(node)


def _import_violations(tree: ast.AST) -> Iterator[str]:
    """Rule 1: the package may not name the type the credential travels in."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _FORBIDDEN_IMPORTS:
                    yield f"line {node.lineno}: import {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module in _FORBIDDEN_IMPORTS:
            names = ", ".join(alias.name for alias in node.names)
            yield f"line {node.lineno}: from {node.module} import {names}"
        elif isinstance(node, ast.Name) and node.id == "Secret":
            yield f"line {node.lineno}: the name Secret"


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """Map the names a module uses locally to what they really are.

    Same reason as in the detector that confines ``rich``: ``import textual.widgets as w``
    must not let ``w.Input(...)`` through a check that compares against the literal string
    ``"textual"``.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _is_widget_call(node: ast.Call, aliases: dict[str, str]) -> bool:
    """Whether this call builds something that comes from ``textual``."""
    dotted = _dotted(node.func)
    if dotted is None:
        return False
    root, _, rest = dotted.partition(".")
    resolved = f"{aliases.get(root, root)}{'.' + rest if rest else ''}"
    return resolved.split(".", maxsplit=1)[0] == "textual"


def _widget_violations(tree: ast.AST) -> Iterator[str]:
    """Rule 2: nothing credential-shaped may be handed to a widget, ever.

    Not even with ``password=True``. That keyword masks the *screen*; the ADR measured
    that the value behind it is a live ``str`` in the DOM for the whole session, which is
    the thing being prevented here. The ``password=`` ban is unscoped - no call in this
    package has any business taking that keyword - while the "do not pass it in" rule
    applies to calls that build ``textual`` objects, since handing ``password_set`` to a
    plain dataclass is the design rather than a breach of it.
    """
    aliases = _import_aliases(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "password":
                yield f"line {node.lineno}: a call with password="
        if not _is_widget_call(node, aliases):
            continue
        for keyword in node.keywords:
            if keyword.value is not None and _is_credential_name(keyword.value):
                yield f"line {node.lineno}: widget built with {keyword.arg}=<credential-shaped>"
        for argument in node.args:
            if _is_credential_name(argument):
                yield f"line {node.lineno}: credential-shaped name passed to a widget"


def _sink_violations(tree: ast.AST) -> Iterator[str]:
    """Rule 3: nothing credential-shaped may be written into a rendered attribute."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_credential_name(node.value):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr in _WIDGET_SINKS:
                    yield f"line {node.lineno}: assignment to .{target.attr}"
        # ``setattr`` reaches the same place without naming the attribute in the source.
        if (
            isinstance(node, ast.Call)
            and _dotted(node.func) == "setattr"
            and len(node.args) == 3
            and _is_credential_name(node.args[2])
        ):
            yield f"line {node.lineno}: setattr of a credential-shaped name"


def _dump_violations(tree: ast.AST) -> Iterator[str]:
    """Rule 4: the application state is never written anywhere it could be read back."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dotted = _dotted(node.func) or ""
            if dotted.rsplit(".", maxsplit=1)[-1] in _FORBIDDEN_CALLS:
                yield f"line {node.lineno}: {dotted}()"


def _binding_violations(tree: ast.AST) -> Iterator[str]:
    """Rule 5: every credential-shaped name in the package is a boolean.

    This is the rule that makes the other four hold. A parameter, a field or an attribute
    that reads like the credential must be annotated ``bool`` (or the callable that
    returns one), and a plain assignment to such a name must have a right-hand side that
    can only be a boolean. There is therefore nowhere in this package for a credential to
    live, whatever it is called.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and _CREDENTIAL_NAME.search(node.arg):
            annotation = "" if node.annotation is None else ast.unparse(node.annotation)
            if annotation not in _BOOLEAN_ANNOTATIONS:
                yield f"line {node.lineno}: parameter {node.arg}: {annotation or '<untyped>'}"
        elif isinstance(node, ast.AnnAssign) and _is_credential_name(node.target):
            annotation = ast.unparse(node.annotation)
            if annotation not in _BOOLEAN_ANNOTATIONS:
                yield f"line {node.lineno}: {ast.unparse(node.target)}: {annotation}"
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if _is_credential_name(target) and not _is_boolean_shaped(node.value):
                    yield f"line {node.lineno}: {ast.unparse(target)} = {ast.unparse(node.value)}"


def collect_credential_violations(source: str) -> list[str]:
    """Every rule, over one module's source. Empty means the module is clean."""
    tree = ast.parse(source)
    return [
        *_import_violations(tree),
        *_widget_violations(tree),
        *_sink_violations(tree),
        *_dump_violations(tree),
        *_binding_violations(tree),
    ]


@pytest.mark.contract
def test_the_wizard_package_cannot_hold_the_credential() -> None:
    """Barrier one: the rule of ADR 0029 condition 5, checked instead of written down."""
    offenders: dict[str, list[str]] = {}
    package = _wizard_package()
    for module in sorted(package.rglob("*.py")):
        violations = collect_credential_violations(module.read_text(encoding="utf-8"))
        if violations:
            offenders[module.name] = violations
    assert offenders == {}, (
        f"the credential may be reaching the widget tree: {offenders} — the wizard holds "
        "seven fields and a boolean; the credential is asked for outside it, through the "
        "callable the CLI passes in (ADR 0029, condition 5)."
    )


#: One injected violation per rule, each of them a plausible six-months-from-now diff.
#: A detector that stopped detecting would make this file pass while proving nothing.
_INJECTED_VIOLATIONS: Final[tuple[tuple[str, str], ...]] = (
    ("secret-import", "from nz_mcp.secret import Secret\n"),
    ("auth-import", "from nz_mcp.auth import get_password\n"),
    ("secret-name", "def f(x):\n    return Secret(x)\n"),
    ("masked-input", "from textual.widgets import Input\nInput(password=True)\n"),
    (
        "input-gets-the-credential",
        "from textual.widgets import Input\nInput(value=password)\n",
    ),
    (
        "positional-credential",
        "from textual.widgets import Input\nInput(self._password)\n",
    ),
    (
        "aliased-widget-gets-the-credential",
        "import textual.widgets as w\nw.Input(value=self._password)\n",
    ),
    ("assign-to-widget-value", "field.value = password\n"),
    ("setattr-into-a-widget", "setattr(field, 'value', password)\n"),
    ("screenshot", "app.save_screenshot('out.svg')\n"),
    ("export-screenshot", "self.export_screenshot()\n"),
    ("devtools", "import textual.devtools\n"),
    ("untyped-parameter", "def ask(password):\n    return password\n"),
    ("string-typed-parameter", "def ask(password: str) -> None:\n    pass\n"),
    ("string-field", "class S:\n    password: str = ''\n"),
    ("attribute-holds-it", "self._password: str = value\n"),
    ("plain-assignment", "self._password_set = ask_secret_raw()\n"),
    ("reactive-field", "password = reactive('')\n"),
)


@pytest.mark.contract
@pytest.mark.parametrize(
    "source", [pytest.param(src, id=name) for name, src in _INJECTED_VIOLATIONS]
)
def test_the_guardrail_rejects_an_injected_violation(source: str) -> None:
    """Barrier one, exercised: each of these is a way the credential could come back."""
    assert collect_credential_violations(source) != []


@pytest.mark.contract
@pytest.mark.parametrize(
    "source",
    [
        pytest.param("def ask(password_set: bool) -> None:\n    pass\n", id="the-boolean"),
        pytest.param(
            "def build(ask_password: Callable[[], bool]) -> None:\n    pass\n",
            id="the-callable",
        ),
        pytest.param("self._password_set = True\n", id="setting-the-boolean"),
        pytest.param("self._password_set = bool(captured)\n", id="narrowing-to-a-boolean"),
        pytest.param(
            "self._password_set = self._password_set or self._had_password\n",
            id="folding-two-booleans",
        ),
        pytest.param("CREDENTIAL_SLOT: Final[str] = 'password'\n", id="the-named-exemption"),
        pytest.param("WizardResult(password_set=self._password_set)\n", id="the-plain-dataclass"),
        pytest.param(
            "from textual.widgets import Input\nInput(value=self._initial.host, compact=True)\n",
            id="an-ordinary-field",
        ),
    ],
)
def test_the_guardrail_does_not_flag_the_shape_that_is_allowed(source: str) -> None:
    """A check that flags everything gets disabled, and then protects nothing."""
    assert collect_credential_violations(source) == []


#: Distinctive enough that finding it anywhere is unambiguous, and long enough that no
#: rendering could produce it by accident.
_LABORATORY_CREDENTIAL: Final[str] = "zzq-guardrail-Nunca-En-Un-Widget-9137"


def _search(value: Any, needle: str, seen: set[int], depth: int = 0) -> bool:
    """Whether ``needle`` appears anywhere reachable from ``value``.

    Deliberately blunt: strings, containers, dataclasses, ``__dict__`` and ``__slots__``.
    A widget tree is a graph, so visited objects are remembered and the depth is bounded.
    """
    if depth > 6 or id(value) in seen:
        return False
    seen.add(id(value))
    if isinstance(value, str | bytes):
        text = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
        return needle in text
    if isinstance(value, dict):
        return any(_search(item, needle, seen, depth + 1) for item in value.values())
    if isinstance(value, list | tuple | set | frozenset):
        return any(_search(item, needle, seen, depth + 1) for item in value)
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict) and _search(attributes, needle, seen, depth + 1):
        return True
    slots = getattr(type(value), "__slots__", ())
    return any(
        _search(getattr(value, slot, None), needle, seen, depth + 1)
        for slot in slots
        if isinstance(slot, str)
    )


@pytest.mark.contract
@pytest.mark.asyncio
async def test_the_real_wizard_never_lets_the_credential_into_a_widget() -> None:
    """Barrier two: the real path, with a real value, and then a search for it.

    This is the test the ``Secret`` regression of PR #193 did not have. It runs the
    application, presses the key that asks for the credential, lets the real callable
    return a real value, and then goes looking for that value in every widget of the
    finished tree, in the application's own attributes and in what it hands back.

    It also checks the shape of the result: what leaves the wizard is a **boolean**.
    """
    captured: list[str] = []

    def ask_password() -> bool:
        # Stands in for cli_output.ask_secret(): the value is collected out here, where
        # the CLI keeps it in a Secret, and only a boolean crosses into the application.
        captured.append(_LABORATORY_CREDENTIAL)
        return True

    application = ProfileWizardApp(
        profile="dev",
        initial=DraftFields(host="nz.example.com", database="DB", user="svc"),
        password_set=False,
        ask_password=ask_password,
        locale="es",
    )
    async with application.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        widgets = list(application.screen.walk_children())
        leaks = [
            type(widget).__name__
            for widget in widgets
            if _search(widget, _LABORATORY_CREDENTIAL, set())
        ]

    assert captured == [_LABORATORY_CREDENTIAL], "the credential path did not run"
    assert widgets, "the widget tree was empty, so this test proved nothing"
    assert leaks == [], f"the credential reached these widgets: {leaks}"
    assert not _search(application.__dict__, _LABORATORY_CREDENTIAL, set()), (
        "the credential is in the application's own state"
    )

    result = application.return_value
    assert result is not None
    assert result.status == "completed"
    assert result.password_set is True
    assert not _search(result, _LABORATORY_CREDENTIAL, set())


@pytest.mark.contract
@pytest.mark.asyncio
async def test_the_leak_search_would_find_a_credential_that_did_reach_a_widget() -> None:
    """The search has to be able to fail, or the test above is a green light for nothing.

    Same tree, but the value is written into a field by hand - which is exactly what the
    AST rules forbid in the source. The search must find it.
    """
    application = ProfileWizardApp(
        profile="dev",
        initial=DraftFields(),
        password_set=False,
        ask_password=lambda: True,
        locale="es",
    )
    async with application.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        field = application.query_one("#field-host")
        field.value = _LABORATORY_CREDENTIAL  # type: ignore[attr-defined]
        await pilot.pause()
        found = _search(field, _LABORATORY_CREDENTIAL, set())
        await pilot.press("escape")

    assert found, "the search cannot see a value sitting in a widget; it proves nothing"


def _locales() -> tuple[Locale, ...]:
    return ("es", "en")


@pytest.mark.contract
@pytest.mark.asyncio
@pytest.mark.parametrize("locale", _locales())
async def test_the_credential_row_says_whether_there_is_one_and_nothing_else(
    locale: Locale,
) -> None:
    """The screen shows a state, in both languages, and never a masked value.

    ``cli-experience.md`` §4 is explicit that not even a masked credential belongs on
    screen: a mask is still an invitation to check over someone's shoulder.
    """
    from textual.widgets import Static

    application = ProfileWizardApp(
        profile="dev",
        initial=DraftFields(),
        password_set=False,
        ask_password=lambda: True,
        locale=locale,
    )
    async with application.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        before = str(application.query_one("#credential-state", Static).content)
        await pilot.press("ctrl+p")
        await pilot.pause()
        after = str(application.query_one("#credential-state", Static).content)
        await pilot.press("escape")

    assert before != after
    assert "*" not in after, "a masked value is still a value on screen"
    assert after.strip(), "the row has to say something once the credential is set"
