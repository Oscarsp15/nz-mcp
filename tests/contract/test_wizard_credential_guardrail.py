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

Why this file is an allowlist, and not a list of forbidden names
----------------------------------------------------------------
The first version of this check chased suspicious names: anything called ``password``,
``secret``, ``credential``. The audit of PR #223 broke it in one line, by calling the
credential ``auth_material`` and putting it straight into an ``Input``. Zero of the five
rules fired. It also got past them through a dictionary and through the return value of a
function with an innocent name.

That is not a bug in the rules, it is what a blacklist **is**. The same thing happened to
the stdout barrier a few hours earlier, and it was fixed the same way it is fixed here:
stop naming what is forbidden and start naming what is allowed. There, the protocol moved
to a private descriptor nothing else could name. Here, the package's whole surface is
enumerated:

============ =========================================================================
Allowlist    What it pins
============ =========================================================================
``IMPORTS``  the modules the package may import at all
``PARAMS``   every parameter of every function, by name **and** annotation
``STATE``    every attribute the application may hold, by name and annotation
``FIELDS``   every field of ``DraftFields``, which is the only data object here
``MODULE``   every module-level name the package may define
``WIDGETS``  the expressions allowed to carry content into a widget
============ =========================================================================

Those six are exhaustive: a value inside this package has to come from an import, a
parameter, an attribute, a data field or a module constant. There is no seventh way. So a
credential cannot be **held** here regardless of what it is called - which is the property
the rename attack disproved for the old rules and cannot disprove for these. Renaming it
does not help, because the name is not what is being checked: the *slot* is, and there are
no free slots.

The cost is deliberate. Adding a field, a parameter or an import to the wizard means
editing a list in this file, on purpose, in a diff a reviewer sees.

Two barriers, not one
---------------------
1. :func:`test_the_wizard_package_cannot_hold_the_credential` - the six allowlists above,
   at review time, naming the offending line.
2. :func:`test_the_real_wizard_never_lets_the_credential_into_a_widget` drives the real
   application through the real credential path, with a real value, and then walks the
   whole finished widget tree, the application's own attributes and its return value
   looking for that value. This one does not care what anything is called either, and it
   is the one that would have caught PR #193.

And the property that makes both of them belt-and-braces rather than the only defence:
the single door into this package is ``ask_password: Callable[[], bool]``, which by its
own type cannot carry the credential across. The type contract is the barrier; these tests
are what stops someone widening the door without noticing.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest

from nz_mcp.i18n import Locale
from nz_mcp.wizard.app import ProfileWizardApp
from nz_mcp.wizard.fields import DraftFields

# --- the six allowlists -------------------------------------------------------
#
# Every entry below was added by a person who thought about it. That is the point: the
# lists are short because the package is small, and they stay short because growing one
# is a visible edit.

#: Modules ``src/nz_mcp/wizard/`` may import. Matched on the dotted prefix, so
#: ``textual.widgets`` is covered by ``textual``.
#:
#: None of these can produce a credential. ``nz_mcp.config`` reads ``profiles.toml``,
#: which by design never contains the password - it lives in the OS keyring - and
#: ``nz_mcp.i18n`` is a dictionary of static text. ``nz_mcp.auth``, ``nz_mcp.secret``,
#: ``keyring`` and ``os`` are not on the list, so they cannot be imported, and no
#: renaming gets round that.
_ALLOWED_IMPORTS: Final[frozenset[str]] = frozenset(
    {
        "__future__",
        "collections.abc",
        "dataclasses",
        "typing",
        "textual",
        "nz_mcp.config",
        "nz_mcp.i18n",
        "nz_mcp.wizard",
    }
)

#: Every parameter of every function in the package, as ``(name, annotation)``. This is
#: the door: a value that is not a module-level constant has to come through one of these.
#: ``ask_password`` is the only one that touches the credential at all, and its type says
#: it hands back a **boolean**.
_ALLOWED_PARAMETERS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        # nz_mcp.wizard.fields - the shared rules
        ("slot", "str"),
        ("value", "str"),
        ("raw", "str"),
        ("draft", "DraftFields"),
        ("password_set", "bool"),
        ("previous", "dict[str, object]"),
        # nz_mcp.wizard.app / __init__ - building and running the screen
        ("profile", "str"),
        ("initial", "DraftFields"),
        ("ask_password", "Callable[[], bool]"),
        ("locale", "Locale"),
        ("event", "events.Resize"),
        ("event", "Input.Changed"),
        ("event", "Input.Submitted"),
        ("event", "events.DescendantFocus"),
        ("status", "WizardStatus"),
    }
)

#: Parameter names that carry no value of their own.
_STRUCTURAL_PARAMETERS: Final[frozenset[str]] = frozenset({"self", "cls"})

#: Every attribute :class:`ProfileWizardApp` may hold, with its annotation and whether its
#: value is allowed to be drawn on screen. This is the application's entire state model,
#: and ADR 0029 condition 5 clause 1 is the line that says ``bool`` next to the credential.
_ALLOWED_APP_STATE: Final[dict[str, tuple[str, bool]]] = {
    "_profile": ("str", True),
    "_initial": ("DraftFields", True),
    "_password_set": ("bool", False),
    "_ask_password": ("Callable[[], bool]", False),
    "_locale": ("Locale", True),
    "_mounted": ("bool", False),
}

#: Every field of :class:`DraftFields`, which is the only object in this package that
#: holds what a person typed. Adding an eighth is a conscious edit of this line - and the
#: rename attack of PR #223 is exactly a field being added without one.
_ALLOWED_DRAFT_FIELDS: Final[dict[str, str]] = {
    "host": "str",
    "port": "str",
    "database": "str",
    "user": "str",
    "mode": "str",
    "security_level": "str",
    "ca_certs": "str",
}

#: Every module-level name the package may define. Without this, a constant would be a
#: seventh way to hold a value, outside every other list.
_ALLOWED_MODULE_NAMES: Final[frozenset[str]] = frozenset(
    {
        # nz_mcp.wizard.fields
        "MODES",
        "CREDENTIAL_SLOT",
        "MIN_WIDTH",
        "MIN_HEIGHT",
        "WizardStatus",
        "FIELD_SPECS",
        "FIELD_KEYS",
        "_MAX_PORT",
        "_SLOT_LABEL_KEYS",
        "_SHAPE_ERROR_KEYS",
        # nz_mcp.wizard.app
        "_FIELD_ID_PREFIX",
        # nz_mcp.wizard
        "__all__",
    }
)

#: Keyword arguments of a widget that carry structure rather than content: identifiers,
#: CSS classes and booleans. Everything else passed to a widget is content and has to be
#: an allowed source.
_STRUCTURAL_WIDGET_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "id",
        "classes",
        "name",
        "compact",
        "markup",
        "select_on_focus",
        "disabled",
        "expand",
        "shrink",
        "show",
    }
)

#: The one function whose result may be drawn: the i18n catalog lookup. Its positional
#: arguments choose a catalog entry and a language; its keyword arguments are interpolated
#: into the text, so those are checked like any other content.
_CATALOG_LOOKUP: Final[str] = "t"

#: Carved out of an allowed package. ``textual`` is on the import allowlist because the
#: wizard is built with it, and a prefix match would let its developer tooling in with it;
#: clause 3 of ADR 0029 condition 5 says the wizard does not run under devtools.
_CARVED_OUT_IMPORTS: Final[frozenset[str]] = frozenset({"textual.devtools"})


def _wizard_package() -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "nz_mcp" / "wizard"


def _dotted(node: ast.AST) -> str | None:
    """Resolve a dotted expression to its written form, or ``None``.

    ``None`` for anything that is not a plain name or attribute chain - a subscript, a
    call, a comprehension. Those simply are not allowed sources, so failing to name them
    is the correct answer rather than a gap: this function feeds an allowlist, and an
    unnameable expression is not on it.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """Map the names a module uses locally to what they really are."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _resolved(dotted: str, aliases: dict[str, str]) -> str:
    root, _, rest = dotted.partition(".")
    resolved = aliases.get(root, root)
    return f"{resolved}.{rest}" if rest else resolved


def _draft_typed_names(tree: ast.AST) -> frozenset[str]:
    """Names annotated ``DraftFields`` in this module, plus the state attributes that are.

    A read off one of these is a read of a draft field, and :data:`_ALLOWED_DRAFT_FIELDS`
    pins what those fields are - so the read is safe by construction, whatever the field
    happens to be called at the call site.
    """
    names = {
        f"self.{attr}"
        for attr, (annotation, _) in _ALLOWED_APP_STATE.items()
        if annotation == "DraftFields"
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            if ast.unparse(node.annotation) == "DraftFields":
                names.add(node.arg)
        elif isinstance(node, ast.AnnAssign) and ast.unparse(node.annotation) == "DraftFields":
            target = _dotted(node.target)
            if target is not None:
                names.add(target)
    return frozenset(names)


# --- rule 1: imports ----------------------------------------------------------


def _import_violations(tree: ast.AST) -> Iterator[str]:
    """Only the listed modules may be imported. Everything else is a violation."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        modules = (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
        )
        for module in modules:
            allowed = any(
                module == prefix or module.startswith(f"{prefix}.") for prefix in _ALLOWED_IMPORTS
            )
            if module in _CARVED_OUT_IMPORTS:
                yield f"line {node.lineno}: imports {module!r}, carved out of an allowed package"
            elif not allowed:
                yield f"line {node.lineno}: imports {module!r}, which is not on the allowlist"


# --- rule 2: parameters -------------------------------------------------------


def _parameter_violations(tree: ast.AST) -> Iterator[str]:
    """Every parameter has to be a listed ``(name, annotation)`` pair.

    This is the door into the package. A credential can only get in as an argument, and
    the only argument that goes anywhere near one promises a ``bool``.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.arg) or node.arg in _STRUCTURAL_PARAMETERS:
            continue
        annotation = "" if node.annotation is None else ast.unparse(node.annotation)
        if (node.arg, annotation) not in _ALLOWED_PARAMETERS:
            shown = annotation or "<untyped>"
            yield f"line {node.lineno}: parameter {node.arg}: {shown} is not on the allowlist"


# --- rule 3: the application's state model ------------------------------------


def _state_violations(tree: ast.AST) -> Iterator[str]:
    """Every ``self.<attr>`` assignment has to be a listed attribute of the listed type."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        targets = list(node.targets) if isinstance(node, ast.Assign) else [node.target]
        annotation = ast.unparse(node.annotation) if isinstance(node, ast.AnnAssign) else ""
        for target in targets:
            dotted = _dotted(target)
            if dotted is None or not dotted.startswith("self."):
                continue
            attribute = dotted.removeprefix("self.")
            if attribute not in _ALLOWED_APP_STATE:
                yield f"line {node.lineno}: self.{attribute} is not on the state allowlist"
            elif annotation and annotation != _ALLOWED_APP_STATE[attribute][0]:
                expected = _ALLOWED_APP_STATE[attribute][0]
                yield f"line {node.lineno}: self.{attribute}: {annotation}, expected {expected}"


# --- rule 4: the data object --------------------------------------------------


def _draft_field_violations(tree: ast.AST) -> Iterator[str]:
    """``DraftFields`` has to declare exactly the listed fields, with the listed types."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "DraftFields":
            continue
        declared: dict[str, str] = {
            statement.target.id: ast.unparse(statement.annotation)
            for statement in node.body
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
        }
        for name, annotation in declared.items():
            if name not in _ALLOWED_DRAFT_FIELDS:
                yield f"line {node.lineno}: DraftFields.{name} is not on the field allowlist"
            elif annotation != _ALLOWED_DRAFT_FIELDS[name]:
                expected = _ALLOWED_DRAFT_FIELDS[name]
                yield f"line {node.lineno}: DraftFields.{name}: {annotation}, expected {expected}"
        for missing in _ALLOWED_DRAFT_FIELDS.keys() - declared.keys():
            yield f"line {node.lineno}: DraftFields no longer declares {missing}"


# --- rule 5: module-level names -----------------------------------------------


def _module_name_violations(tree: ast.AST) -> Iterator[str]:
    """A module-level constant would be a place to hold a value outside every other list."""
    if not isinstance(tree, ast.Module):
        return
    for node in tree.body:
        targets = (
            [node.target]
            if isinstance(node, ast.AnnAssign)
            else list(node.targets)
            if isinstance(node, ast.Assign)
            else []
        )
        for target in targets:
            name = _dotted(target)
            if name is not None and name not in _ALLOWED_MODULE_NAMES:
                yield f"line {node.lineno}: module-level {name} is not on the allowlist"


# --- rule 6: what may be drawn ------------------------------------------------


def _is_widget_call(node: ast.Call, aliases: dict[str, str]) -> bool:
    """Whether this call builds something that comes from ``textual``."""
    dotted = _dotted(node.func)
    return dotted is not None and _resolved(dotted, aliases).split(".")[0] == "textual"


def _is_allowed_content(node: ast.expr, aliases: dict[str, str], drafts: frozenset[str]) -> bool:
    """Whether an expression is on the allowlist of things a widget may be given.

    Four shapes, and nothing else. A subscript (``state["password"]``), a call to anything
    but the catalog (``fetch_it()``), an attribute of something that is not a draft - all
    of them fall through to ``False``, which is the whole difference from the version the
    audit broke.
    """
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str | bool | int) or node.value is None
    if isinstance(node, ast.JoinedStr):
        return all(
            _is_allowed_content(part.value, aliases, drafts)
            for part in node.values
            if isinstance(part, ast.FormattedValue)
        )
    if isinstance(node, ast.Call):
        return _is_allowed_call(node, aliases, drafts)
    return _is_allowed_read(_dotted(node), drafts)


def _is_allowed_read(dotted: str | None, drafts: frozenset[str]) -> bool:
    """Whether a plain name or attribute chain is something a widget may be given."""
    if dotted is None:
        return False
    if dotted in drafts:
        return True
    base, _, attribute = dotted.rpartition(".")
    if base in drafts:
        # A field of a draft. The field allowlist says which fields can exist at all.
        return attribute in _ALLOWED_DRAFT_FIELDS
    if base == "self":
        return _ALLOWED_APP_STATE.get(attribute, ("", False))[1]
    # Anything else - a bare local, a spec attribute, an unknown object - is not a source.
    return False


def _is_allowed_call(node: ast.Call, aliases: dict[str, str], drafts: frozenset[str]) -> bool:
    """The catalog lookup, and ``getattr`` on a draft. Nothing else may be drawn."""
    dotted = _dotted(node.func)
    if dotted == _CATALOG_LOOKUP:
        # Positional arguments select the entry and the language; keyword arguments are
        # interpolated into it, so they are content and are checked as such.
        return all(
            keyword.value is None or _is_allowed_content(keyword.value, aliases, drafts)
            for keyword in node.keywords
        )
    if dotted == "getattr" and node.args:
        # ``getattr(<a draft>, ...)`` can only ever reach one of the allowed fields.
        return _dotted(node.args[0]) in drafts
    return False


def _widget_content_violations(tree: ast.AST) -> Iterator[str]:
    """Every non-structural argument of a widget has to be an allowed content source."""
    aliases = _import_aliases(tree)
    drafts = _draft_typed_names(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_widget_call(node, aliases):
            continue
        for argument in node.args:
            if not _is_allowed_content(argument, aliases, drafts):
                shown = ast.unparse(argument)
                yield f"line {node.lineno}: widget given {shown}, which is not an allowed source"
        for keyword in node.keywords:
            if keyword.arg in _STRUCTURAL_WIDGET_KEYWORDS or keyword.value is None:
                continue
            if not _is_allowed_content(keyword.value, aliases, drafts):
                shown = f"{keyword.arg}={ast.unparse(keyword.value)}"
                yield f"line {node.lineno}: widget given {shown}, which is not an allowed source"


# --- extras -------------------------------------------------------------------

#: Calls that would write the application state where it could be read back. Not part of
#: the allowlist argument - clause 3 of ADR 0029 condition 5 is a separate promise - but
#: cheap to keep, and the ADR asked for it in writing.
_FORBIDDEN_DUMPS: Final[frozenset[str]] = frozenset({"save_screenshot", "export_screenshot"})


def _dump_violations(tree: ast.AST) -> Iterator[str]:
    """Clause 3 of ADR 0029 condition 5: no screenshots, no devtools, in production."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dotted = _dotted(node.func) or ""
            if dotted.rsplit(".", maxsplit=1)[-1] in _FORBIDDEN_DUMPS:
                yield f"line {node.lineno}: {dotted}()"
        elif isinstance(node, ast.Call | ast.keyword) and getattr(node, "arg", None) == "password":
            yield f"line {node.lineno}: a call with password="


def collect_credential_violations(source: str) -> list[str]:
    """Every allowlist, over one module's source. Empty means the module is clean."""
    tree = ast.parse(source)
    return [
        *_import_violations(tree),
        *_parameter_violations(tree),
        *_state_violations(tree),
        *_draft_field_violations(tree),
        *_module_name_violations(tree),
        *_widget_content_violations(tree),
        *_dump_violations(tree),
    ]


@pytest.mark.contract
def test_the_wizard_package_cannot_hold_the_credential() -> None:
    """Barrier one: six allowlists that leave the credential nowhere to live."""
    offenders: dict[str, list[str]] = {}
    package = _wizard_package()
    for module in sorted(package.rglob("*.py")):
        violations = collect_credential_violations(module.read_text(encoding="utf-8"))
        if violations:
            offenders[module.name] = violations
    assert offenders == {}, (
        f"the wizard package grew a slot the allowlists do not know about: {offenders} — "
        "if the addition is legitimate, add it to the list in this file on purpose "
        "(ADR 0029, condition 5)."
    )


#: One injected diff per way in, including the three the audit of PR #223 used to walk
#: straight past the previous version of this check. A rule that stopped ruling would make
#: this file pass while proving nothing.
_INJECTED_VIOLATIONS: Final[tuple[tuple[str, str], ...]] = (
    # The three evasions the audit demonstrated. None of them mentions a suspicious word.
    (
        "renamed-and-put-in-a-widget",
        "from textual.widgets import Input\nInput(value=self._initial.auth_material)\n",
    ),
    (
        "renamed-as-a-draft-field",
        "@dataclass\nclass DraftFields:\n    host: str = ''\n    auth_material: str = ''\n",
    ),
    (
        "renamed-as-a-parameter",
        "def build(auth_material: str) -> None:\n    pass\n",
    ),
    (
        "through-a-dictionary",
        "from textual.widgets import Input\nInput(value=state['password'])\n",
    ),
    (
        "through-a-renamed-dictionary",
        "from textual.widgets import Input\nInput(value=cache['whatever'])\n",
    ),
    (
        "through-the-return-of-a-function",
        "from textual.widgets import Input\nInput(value=fetch_it())\n",
    ),
    # The ways the old blacklist did catch, kept so the coverage never narrows.
    ("secret-import", "from nz_mcp.secret import Secret\n"),
    ("auth-import", "from nz_mcp.auth import get_password\n"),
    ("keyring-import", "import keyring\n"),
    ("os-import", "import os\n"),
    ("devtools-import", "import textual.devtools\n"),
    ("masked-input", "from textual.widgets import Input\nInput(password=True)\n"),
    (
        "aliased-widget-gets-it",
        "import textual.widgets as w\nw.Input(value=self._password)\n",
    ),
    ("screenshot", "app.save_screenshot('out.svg')\n"),
    ("export-screenshot", "self.export_screenshot()\n"),
    (
        "an-attribute-that-is-not-on-the-state-list",
        "class A:\n    def f(self) -> None:\n        self._auth_material = value\n",
    ),
    ("a-module-level-constant", "AUTH_MATERIAL = 'x'\n"),
    ("an-untyped-parameter", "def ask(anything):\n    return anything\n"),
    (
        "a-catalog-placeholder-carrying-it",
        "from textual.widgets import Static\nStatic(t('KEY', locale, value=fetch_it()))\n",
    ),
)


@pytest.mark.contract
@pytest.mark.parametrize(
    "source", [pytest.param(src, id=name) for name, src in _INJECTED_VIOLATIONS]
)
def test_the_guardrail_rejects_an_injected_violation(source: str) -> None:
    """Barrier one, exercised. Three of these are the audit's own evasions of PR #223."""
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
        pytest.param(
            "class A:\n    def f(self) -> None:\n        self._password_set = True\n",
            id="setting-the-boolean",
        ),
        pytest.param("CREDENTIAL_SLOT = 'password'\n", id="a-listed-module-constant"),
        pytest.param(
            "from textual.widgets import Input\nInput(value=self._initial.host, compact=True)\n",
            id="a-declared-draft-field",
        ),
        pytest.param(
            "from textual.widgets import Static\nStatic(t('KEY', locale), id='title')\n",
            id="a-catalog-lookup",
        ),
        pytest.param(
            "from textual.widgets import Input\nInput(value=getattr(self._initial, spec.key))\n",
            id="any-field-of-a-draft",
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
