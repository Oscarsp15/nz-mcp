"""The shared visual layer (ADR 0032, decisions 5 and 6): one sheet, two themes, measured.

What is checked here:

- the sheet is the only source of colour: both screens load it, and no module of a screen
  fixes a colour by hand. That last one is structural - over the AST, using the framework's
  own colour parser - and not a list of forbidden names, because a name is walked past by
  renaming and a shape is not;
- every text/background pair each theme declares clears 4.5:1 (WCAG 2.1), with the ratio
  computed here rather than trusted, and the pairs the ADR tabulates come out at the number
  the ADR wrote down;
- the two themes declare the same variables, so no token exists in one and not the other;
- every ``$variable`` the sheet names resolves in both themes, and the sheet itself holds
  no colour value;
- the sheet is reachable the way an installed package reaches its data;
- F2 outlives the screen that pressed it.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import fields
from importlib import resources
from pathlib import Path
from typing import Final

import pytest
from textual.color import Color, ColorParseError
from textual.theme import Theme
from textual.widgets import Static

from nz_mcp.tui import NZ_DARK, NZ_LIGHT, STYLESHEET, THEMES, ThemedApp
from nz_mcp.wizard import DraftFields
from nz_mcp.wizard.app import ProfileWizardApp

# --- the measurement -----------------------------------------------------------

#: WCAG 2.1 floor for text that carries meaning (ADR 0032, decision 6).
_FLOOR: Final[float] = 4.5

#: The roles that are read, and the surfaces they can be read on. Bands carry only the
#: two roles the sheet ever writes on them.
_TEXT_ROLES: Final[tuple[str, ...]] = (
    "foreground",
    "text-muted",
    "accent",
    "success",
    "warning",
    "error",
)
_SURFACES: Final[tuple[str, ...]] = ("background", "surface", "panel")
_BAND_ROLES: Final[tuple[str, ...]] = ("foreground", "accent")
_BANDS: Final[tuple[str, ...]] = ("band-idle", "band-focus")
#: Selected text in a field: the foreground is the only role drawn on it.
_SELECTION: Final[str] = "input-selection-background"


def _channel(value: int) -> float:
    """sRGB channel to linear light, per WCAG 2.1 relative luminance."""
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(text: str, background: str) -> float:
    """WCAG 2.1 contrast ratio between two ``#RRGGBB`` values, 1.0 to 21.0."""
    lighter, darker = sorted((_luminance(text), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _palette(theme: Theme) -> dict[str, str]:
    """Every colour a theme declares, by role: the dataclass fields plus its variables."""
    declared = {
        field.name: value
        for field in fields(theme)
        if isinstance(value := getattr(theme, field.name), str) and value.startswith("#")
    }
    return {**declared, **theme.variables}


def _pairs() -> Iterator[tuple[str, str, str]]:
    for theme in THEMES:
        for surface in _SURFACES:
            for role in _TEXT_ROLES:
                yield theme.name, role, surface
        for band in _BANDS:
            for role in _BAND_ROLES:
                yield theme.name, role, band
        yield theme.name, "foreground", _SELECTION


def _theme(name: str) -> Theme:
    return next(theme for theme in THEMES if theme.name == name)


def test_the_ratio_is_the_wcag_one() -> None:
    """Black on white is 21:1 and a colour on itself is 1:1; anything else is a bug here."""
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast_ratio("#FFFFFF", "#000000") == pytest.approx(21.0)
    assert contrast_ratio("#5EEAD4", "#5EEAD4") == pytest.approx(1.0)


@pytest.mark.parametrize(("theme_name", "role", "surface"), list(_pairs()))
def test_every_declared_pair_clears_the_floor(theme_name: str, role: str, surface: str) -> None:
    """Everything that carries meaning clears 4.5:1 on every surface it can land on."""
    palette = _palette(_theme(theme_name))
    ratio = contrast_ratio(palette[role], palette[surface])
    assert ratio >= _FLOOR, f"{theme_name}: {role} on {surface} is {ratio:.2f}:1"


#: The numbers ADR 0032, decision 6, wrote down. They are the baseline: if a tone changes,
#: the number changes and it shows here.
_ADR_BASELINE: Final[tuple[tuple[str, str, str, float], ...]] = (
    ("nz-dark", "foreground", "background", 13.47),
    ("nz-dark", "accent", "background", 12.24),
    ("nz-dark", "success", "background", 10.39),
    ("nz-dark", "warning", "background", 10.85),
    ("nz-dark", "error", "background", 6.55),
    ("nz-light", "foreground", "background", 15.22),
    ("nz-light", "foreground", "surface", 17.50),
    ("nz-light", "foreground", "panel", 12.91),
    ("nz-light", "accent", "background", 5.47),
    ("nz-light", "accent", "surface", 6.29),
    ("nz-light", "accent", "panel", 4.64),
    ("nz-light", "success", "background", 6.12),
    ("nz-light", "success", "surface", 7.04),
    ("nz-light", "success", "panel", 5.20),
    ("nz-light", "warning", "background", 6.09),
    ("nz-light", "warning", "surface", 7.00),
    ("nz-light", "warning", "panel", 5.17),
    ("nz-light", "error", "background", 5.56),
    ("nz-light", "error", "surface", 6.39),
    ("nz-light", "error", "panel", 4.71),
)


@pytest.mark.parametrize(("theme_name", "role", "surface", "expected"), _ADR_BASELINE)
def test_the_measured_ratios_are_the_ones_the_adr_tabulates(
    theme_name: str, role: str, surface: str, expected: float
) -> None:
    palette = _palette(_theme(theme_name))
    assert round(contrast_ratio(palette[role], palette[surface]), 2) == pytest.approx(
        expected, abs=0.01
    )


# --- the two themes are one system ------------------------------------------------


def test_both_themes_declare_the_same_variables() -> None:
    """No token defined in one theme and missing from the other."""
    assert set(NZ_DARK.variables) == set(NZ_LIGHT.variables)
    assert set(_palette(NZ_DARK)) == set(_palette(NZ_LIGHT))


def test_one_accent_only() -> None:
    """Textual asks for a primary; the product has one accent, so they are the same colour."""
    for theme in THEMES:
        assert theme.primary == theme.accent


def test_light_is_designed_and_not_inverted() -> None:
    """Decision 5: in light the cards sit above the background and the fields below it.

    In dark everything rises from the background instead. Inverting one theme to get the
    other would break exactly this ordering.
    """
    light = _palette(NZ_LIGHT)
    assert _luminance(light["surface"]) > _luminance(light["background"])
    assert _luminance(light["panel"]) < _luminance(light["background"])
    dark = _palette(NZ_DARK)
    assert _luminance(dark["surface"]) > _luminance(dark["background"])
    assert _luminance(dark["panel"]) > _luminance(dark["surface"])


# --- the sheet -----------------------------------------------------------------


def _sheet_source() -> str:
    """The sheet with its comments stripped: what the framework reads, not the prose."""
    return re.sub(r"/\*.*?\*/", "", STYLESHEET.read_text(encoding="utf-8"), flags=re.DOTALL)


def _sheet_values() -> Iterator[str]:
    """Every declaration value in the sheet."""
    for match in re.finditer(r":\s*([^;{}]+);", _sheet_source()):
        yield match.group(1).strip()


def _is_colour(token: str) -> bool:
    """Whether the framework would read this token as a colour that is actually drawn."""
    try:
        return Color.parse(token).a > 0
    except ColorParseError:
        return False


def test_every_variable_the_sheet_names_resolves_in_both_themes() -> None:
    """A ``$token`` the theme does not define fails at start-up, in the user's terminal."""
    named = set(re.findall(r"\$([a-z][a-z0-9-]*)", _sheet_source()))
    assert named, "the sheet names no variable at all"
    for theme in THEMES:
        defined = set(theme.to_color_system().generate()) | set(theme.variables)
        assert named <= defined, f"{theme.name} does not define {sorted(named - defined)}"


def test_the_sheet_holds_no_colour_value() -> None:
    """Rule 1 of the sheet: colours enter as variables, never as values."""
    literal = [
        token
        for value in _sheet_values()
        for token in value.split()
        if not token.startswith("$") and _is_colour(token)
    ]
    assert literal == []


def test_the_sheet_ships_with_the_package() -> None:
    """Risk 5 of ADR 0032: a file that is not ``.py`` is forgotten by packaging, at home."""
    packaged = resources.files("nz_mcp.tui").joinpath("nz.tcss")
    assert packaged.is_file()
    assert packaged.read_text(encoding="utf-8") == STYLESHEET.read_text(encoding="utf-8")


def test_the_screen_loads_the_one_sheet() -> None:
    assert issubclass(ProfileWizardApp, ThemedApp)
    assert ProfileWizardApp.CSS_PATH == STYLESHEET
    assert "CSS" not in vars(ProfileWizardApp), "ProfileWizardApp carries its own CSS"


# --- no widget decides a colour (structural) -----------------------------------------

#: The packages whose modules draw a screen. ``tui`` is where the palette lives, on purpose.
#: ADR 0035 removed the menu and "Ver perfiles"; the wizard is the only screen left.
_SCREEN_PACKAGES: Final[tuple[str, ...]] = ("wizard",)

#: The class attributes through which Textual accepts a stylesheet from code, or a second
#: sheet from a file: a screen inherits ``CSS_PATH`` and never declares its own.
_INLINE_CSS_ATTRIBUTES: Final[frozenset[str]] = frozenset({"CSS", "DEFAULT_CSS", "CSS_PATH"})

#: The methods that feed styles in at run time: inline CSS on a widget, a source added to
#: the application's stylesheet.
_STYLE_INJECTION_METHODS: Final[frozenset[str]] = frozenset({"set_styles", "add_source"})

#: The functional forms, which the tokeniser below would break apart.
_COLOUR_FUNCTION: Final[re.Pattern[str]] = re.compile(r"\b(?:rgba?|hsla?)\(")

#: What separates tokens inside a string: whitespace, the punctuation of a stylesheet and
#: the brackets of Rich markup (``[bold red]``, ``[on red]``, ``[#ff0000]``).
_TOKEN_BREAK: Final[re.Pattern[str]] = re.compile(r"[\s;:,{}()\[\]\"']+")


def _docstrings(tree: ast.AST) -> set[int]:
    """Ids of the constants that are docstrings: prose, not values."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def _mentions_colour(text: str) -> bool:
    if _COLOUR_FUNCTION.search(text):
        return True
    return any(_is_colour(token) for token in _TOKEN_BREAK.split(text) if token)


def _through_styles(node: ast.expr) -> bool:
    """Whether an attribute chain goes through ``.styles`` - the inline style API."""
    while isinstance(node, ast.Attribute):
        if node.attr == "styles":
            return True
        node = node.value
    return False


def _call_violations(node: ast.Call) -> Iterator[str]:
    """The calls that decide a colour: a style fed in, a style set by name, a colour built."""
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if isinstance(func, ast.Attribute) and name in _STYLE_INJECTION_METHODS:
        yield f"{name}()"
    if name == "setattr" and node.args and _is_styles(node.args[0]):
        yield "setattr() on styles"
    if name == "Color":
        yield "Color() built in code"


def _is_styles(node: ast.expr) -> bool:
    """Whether an expression is a ``styles`` object, bare or reached through an attribute."""
    if isinstance(node, ast.Name):
        return node.id == "styles"
    return _through_styles(node)


def collect_colour_violations(source: str) -> list[str]:
    """Every place a module of a screen decides a colour. Empty means it does not."""
    tree = ast.parse(source)
    prose = _docstrings(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for statement in node.body:
                targets = (
                    [statement.target]
                    if isinstance(statement, ast.AnnAssign)
                    else list(statement.targets)
                    if isinstance(statement, ast.Assign)
                    else []
                )
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in _INLINE_CSS_ATTRIBUTES:
                        found.append(f"line {statement.lineno}: {node.name}.{target.id}")
        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = [node.target] if not isinstance(node, ast.Assign) else node.targets
            for target in targets:
                if isinstance(target, ast.Attribute) and _through_styles(target):
                    found.append(f"line {node.lineno}: {ast.unparse(target)} assigned")
        elif isinstance(node, ast.Call):
            found.extend(f"line {node.lineno}: {reason}" for reason in _call_violations(node))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in prose
            and _mentions_colour(node.value)
        ):
            found.append(f"line {node.lineno}: colour literal {node.value!r}")
    return found


def _screen_modules() -> list[Path]:
    root = Path(__file__).resolve().parents[2] / "src" / "nz_mcp"
    return sorted(path for package in _SCREEN_PACKAGES for path in (root / package).rglob("*.py"))


def test_no_module_of_a_screen_decides_a_colour() -> None:
    """The rule of ADR 0032, decision 5, enforced: colour enters by theme variable, always."""
    modules = _screen_modules()
    assert len(modules) >= 2, "the screen packages were not found"
    offenders = {
        module.name: violations
        for module in modules
        if (violations := collect_colour_violations(module.read_text(encoding="utf-8")))
    }
    assert offenders == {}


_INJECTED: Final[tuple[tuple[str, str], ...]] = (
    ("class-css", 'class X:\n    CSS = "Screen { color: red; }"\n'),
    ("class-css-annotated", 'class X:\n    CSS: ClassVar[str] = "#a { }"\n'),
    ("default-css", 'class X:\n    DEFAULT_CSS = "X { height: 1; }"\n'),
    ("styles-background", 'self.styles.background = "red"\n'),
    ("styles-color-from-name", "w.styles.color = accent\n"),
    ("styles-nested", 'self.query_one(X).styles.background = "#fff"\n'),
    ("styles-augmented", "w.styles.opacity += 1\n"),
    ("set-styles", 'w.set_styles("color: red")\n'),
    ("hex-literal", 'ACCENT = "#5EEAD4"\n'),
    ("short-hex", 'x = "#fff"\n'),
    ("rgb-literal", 'x = "rgb(1, 2, 3)"\n'),
    ("hsl-literal", 'x = "hsl(1, 2%, 3%)"\n'),
    ("named-colour", 'x = "tomato"\n'),
    ("ansi-colour", 'x = "ansi_red"\n'),
    ("colour-inside-text", 'x = "background: teal;"\n'),
    # Rich markup: the audit of PR #247 found these walked straight past the tokeniser.
    ("markup-bold-red", 'Static("[bold red]error[/]")\n'),
    ("markup-red", 'x = "[red]"\n'),
    ("markup-on-red", 'x = "[on red]"\n'),
    ("markup-hex", 'x = "[#ff0000]"\n'),
    ("markup-ansi", 'x = "[ansi_red]"\n'),
    ("colour-constructor", "c = Color(255, 0, 0)\n"),
    ("colour-constructor-qualified", "c = textual.color.Color(1, 2, 3)\n"),
    ("setattr-on-styles", 'setattr(self.styles, "background", value)\n'),
    ("css-path-in-a-screen", 'class X:\n    CSS_PATH = "other.tcss"\n'),
    ("stylesheet-add-source", 'self.stylesheet.add_source("X { }")\n'),
)


@pytest.mark.parametrize(("case", "source"), _INJECTED, ids=[case for case, _ in _INJECTED])
def test_the_structural_check_catches_each_way_of_deciding_a_colour(case: str, source: str) -> None:
    assert collect_colour_violations(source) != [], case


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('"""A teal accent, #10171A, on a red surface."""\n', id="docstring"),
        pytest.param('yield Static("", id="describe", markup=False)\n', id="widget-id"),
        pytest.param('status.set_classes("-ready")\n', id="state-class"),
        pytest.param('t("CLI.MENU_KEYS", self._locale)\n', id="catalog-key"),
        pytest.param('Binding("escape", "cancel", "", show=False)\n', id="binding"),
        pytest.param("transparent = 0\n", id="a-name-is-not-a-string"),
    ],
)
def test_the_structural_check_lets_the_ordinary_shapes_through(source: str) -> None:
    assert collect_colour_violations(source) == []


# --- F2 persists on the one screen left --------------------------------------------


def _wizard() -> ProfileWizardApp:
    return ProfileWizardApp(
        profile="dev",
        initial=DraftFields(host="nz.example.com", database="PROD", user="svc"),
        password_set=True,
        ask_password=lambda: True,
        credential=_Sink(),
        locale="es",
    )


class _Sink:
    def insert(self, index: int, character: str) -> None:
        del index, character

    def remove(self, start: int, stop: int) -> None:
        del start, stop

    def clear(self) -> None:
        return None


@pytest.mark.asyncio
async def test_the_theme_chosen_with_f2_is_the_one_the_screen_keeps() -> None:
    """ADR 0035 left the wizard as the one full-screen surface; F2 still has to hold."""
    wizard = _wizard()
    async with wizard.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert wizard.theme == NZ_DARK.name
        await pilot.press("f2")
        await pilot.pause()
        assert wizard.theme == NZ_LIGHT.name
        assert wizard.screen.styles.background == Color.parse(NZ_LIGHT.background or "")
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_what_a_widget_draws_is_what_the_theme_declares() -> None:
    """The field-error log is coloured by the sheet from the theme, and by nothing else."""
    wizard = ProfileWizardApp(
        profile="dev",
        initial=DraftFields(),
        password_set=False,
        ask_password=lambda: True,
        credential=_Sink(),
        locale="es",
    )
    async with wizard.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        explain = wizard.query_one("#explain", Static)
        assert str(explain.content) != "", "an incomplete draft has to report something"
        # Textual's colour system, not the raw declared value: rendering derives "error"
        # from it and rounds by a shade (measured: #F87171 renders as #F77171), which the
        # WCAG measurement in this file does not see because it reads the dataclass field
        # directly. What is checked here is that no code in the wizard substitutes a third
        # value of its own - the sheet's variable is what reaches the screen either way.
        assert explain.styles.color == Color.parse(NZ_DARK.to_color_system().generate()["error"])
        await pilot.press("f2")
        await pilot.pause()
        assert explain.styles.color == Color.parse(NZ_LIGHT.to_color_system().generate()["error"])
        await pilot.press("escape")
