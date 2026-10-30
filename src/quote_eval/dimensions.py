"""Read dimensions from a customer sentence. This does not quote.

Supported expressions, using this catalog's units:

- Lumber ``2×4``, ``2x4``, ``2 by 4``, ``2-by-4``, and ``two-by-four`` are a
  nominal cross-section: thickness 2 inches and width 4 inches. They are not a
  length.
- ``2×4×8``, ``2×4×10``, ``2×4×8-foot``, and ``2×4 by 10 feet`` add a length in
  feet. The third attached number is length_ft because this catalog stores
  lumber length only in feet. A separate bare number is not a length.
- Plywood ``4×8 feet``, ``4×8-foot``, and ``4 by 8 feet`` are width_ft and
  length_ft. ``23/32-inch`` is thickness. Feet are not converted to inches.
- When the request says plywood and gives ``4×8`` with no unit, the face size
  is also width_ft and length_ft. That is this catalog's only plywood sheet size.
- Quantity is a number attached to pieces, sheets, units, or rolls.
- Grade ``#2``, ``number 2``, and ``no. 2`` are the grade ``#2``. ``SPF`` is the species.
- Multiplication signs ``×``, ``✕``, ``✖``, and ``x`` are the same mark.
  Extra spaces are ignored.

Still ambiguous, so these stay missing:

- A bare number, including ``8`` taken from ``8 pieces``.
- ``2×4`` treated as ``2×4×8``. A missing lumber length is not filled in.
- ``4×8`` with no plywood word and no foot unit.
- ``4×8 inches``, or a conversion such as 4 feet written as 48 inches.
- ``2 by 4 by 8`` with no foot unit. The third ``by`` is not the ``×`` length.
- A number that is only a prefix or a piece of a longer number, such as 200
  inside 2000 or 20.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from quote_eval.models import SpecValue

_MULTIPLY = str.maketrans(
    {
        "×": "x",
        "✕": "x",
        "✖": "x",
        "╳": "x",
        "–": "-",
        "—": "-",
    }
)
_CROSS = r"(?<!\d)2\s*(?:x|by|-by)\s*-?\s*4(?!\d)"
_TWO = r"two[\s-]*by[\s-]*four"
_NOMINAL = rf"(?:{_TWO}|{_CROSS})"
_FOOT = r"(?:foot|feet|ft)"
_LUMBER_FOOT = re.compile(
    rf"{_NOMINAL}\s*(?:x|by|-by)\s*-?\s*(\d+)\s*-?\s*{_FOOT}\b"
)
_LUMBER_THIRD = re.compile(rf"{_NOMINAL}\s*x\s*(\d+)\b")
_CROSS_ONLY = re.compile(rf"(?:{_TWO}|{_CROSS})\b")
_PLY_FOOT = re.compile(rf"(?<!\d)(\d+)\s*(?:x|by)\s*(\d+)(?!\d)\s*-?\s*{_FOOT}\b")
_PLY_BARE = re.compile(
    rf"(?<!\d)(\d+)\s*(?:x|by)\s*(\d+)(?!\d)(?!\s*-?\s*(?:inch|inches)\b)"
)
_LENGTH_ONLY = re.compile(rf"(?<!\d)(\d+)(?!\d)\s*-?\s*{_FOOT}(?:\s+long)?\b")
_THICKNESS = re.compile(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)\s*-?\s*inch(?:es)?\b")
_QUANTITY = re.compile(
    r"(?<!\d)(\d+)(?!\d)\s*(?:pieces|piece|sheets|sheet|units|unit|rolls|roll)\b"
)
_GRADE = re.compile(r"(?:#\s*2|number\s*2|no\.\s*2)\b")
_DENIAL = re.compile(r"\b(?:no|not)\b|do not|don't")
_MODEL = re.compile(r"\bmodel\s+([A-Za-z0-9-]+)", re.IGNORECASE)


@dataclass(frozen=True)
class Reading:
    """Facts a documented expression states. Missing fields stay None."""

    product_type: str | None
    specs: dict[str, SpecValue]
    quantity: int | None
    model: str | None
    substitution_allowed: bool | None
    ambiguous: tuple[str, ...]


@dataclass(frozen=True)
class _Hit:
    start: int
    end: int
    kind: str
    data: dict[str, SpecValue | int]


def parse_customer_request(text: str) -> Reading:
    """Parse one sentence. The same rules apply to a short evidence span."""

    normalized = normalize_text(text)
    hits = _collect(normalized)
    chosen = _choose(hits)
    specs: dict[str, SpecValue] = {}
    quantity: int | None = None
    ambiguous: list[str] = []
    lengths: list[int] = []
    quantities: list[int] = []
    for hit in chosen:
        if hit.kind == "quantity":
            quantities.append(int(hit.data["quantity"]))
        elif hit.kind == "length":
            lengths.append(int(hit.data["length_ft"]))
        else:
            for key, value in hit.data.items():
                if key in specs and specs[key] != value:
                    ambiguous.append(key)
                else:
                    specs[key] = value
    if len(quantities) == 1:
        quantity = quantities[0]
    elif len(quantities) > 1:
        ambiguous.append("quantity")
    if len(lengths) == 1:
        specs["length_ft"] = lengths[0]
    elif len(lengths) > 1:
        ambiguous.append("length_ft")
    for key in ambiguous:
        specs.pop(key, None)
    product_type = _product_type(normalized, specs)
    return Reading(
        product_type=product_type,
        specs=specs,
        quantity=quantity,
        model=_model_id(text),
        substitution_allowed=substitution_from_text(normalized),
        ambiguous=tuple(sorted(set(ambiguous))),
    )


def normalize_text(text: str) -> str:
    return " ".join(text.translate(_MULTIPLY).casefold().split())


def substitution_from_text(text: str) -> bool | None:
    """True when a substitute is allowed, false when it is forbidden, else None.

    A denial such as "no substitutions" or "do not substitute" wins. The word
    inside "unavailable" is not a denial. Silence stays None.
    """

    normalized = normalize_text(text)
    talks = "equivalent" in normalized or "substitut" in normalized
    if not talks:
        return None
    if _DENIAL.search(normalized):
        return False
    return True


def canonical_grade(value: object) -> object:
    if not isinstance(value, str):
        return value
    if _GRADE.fullmatch(normalize_text(value)):
        return "#2"
    return value


def canonical_species(value: object) -> object:
    if isinstance(value, str) and normalize_text(value) == "spf":
        return "SPF"
    return value


def _collect(text: str) -> list[_Hit]:
    found: list[_Hit] = []
    for match in _LUMBER_FOOT.finditer(text):
        found.append(
            _Hit(
                match.start(),
                match.end(),
                "lumber",
                {"thickness_in": 2, "width_in": 4, "length_ft": int(match.group(1))},
            )
        )
    for match in _LUMBER_THIRD.finditer(text):
        found.append(
            _Hit(
                match.start(),
                match.end(),
                "lumber",
                {"thickness_in": 2, "width_in": 4, "length_ft": int(match.group(1))},
            )
        )
    for match in _CROSS_ONLY.finditer(text):
        found.append(
            _Hit(match.start(), match.end(), "cross", {"thickness_in": 2, "width_in": 4})
        )
    for match in _PLY_FOOT.finditer(text):
        found.append(
            _Hit(
                match.start(),
                match.end(),
                "ply",
                {"width_ft": int(match.group(1)), "length_ft": int(match.group(2))},
            )
        )
    if "plywood" in text:
        for match in _PLY_BARE.finditer(text):
            found.append(
                _Hit(
                    match.start(),
                    match.end(),
                    "ply",
                    {"width_ft": int(match.group(1)), "length_ft": int(match.group(2))},
                )
            )
    for match in _LENGTH_ONLY.finditer(text):
        found.append(
            _Hit(match.start(), match.end(), "length", {"length_ft": int(match.group(1))})
        )
    for match in _THICKNESS.finditer(text):
        found.append(
            _Hit(
                match.start(),
                match.end(),
                "thickness",
                {"thickness_in": f"{int(match.group(1))}/{int(match.group(2))}"},
            )
        )
    for match in _QUANTITY.finditer(text):
        found.append(
            _Hit(match.start(), match.end(), "quantity", {"quantity": int(match.group(1))})
        )
    grade = _GRADE.search(text)
    if grade:
        found.append(_Hit(grade.start(), grade.end(), "grade", {"grade": "#2"}))
    species = re.search(r"\bspf\b", text)
    if species:
        found.append(_Hit(species.start(), species.end(), "species", {"species": "SPF"}))
    return found


def _choose(hits: list[_Hit]) -> list[_Hit]:
    ordered = sorted(hits, key=lambda hit: (-(hit.end - hit.start), hit.start))
    chosen: list[_Hit] = []
    occupied: list[tuple[int, int]] = []
    for hit in ordered:
        if any(hit.start < end and start < hit.end for start, end in occupied):
            continue
        chosen.append(hit)
        occupied.append((hit.start, hit.end))
    return chosen


def _product_type(text: str, specs: dict[str, SpecValue]) -> str | None:
    if "plywood" in text:
        return "plywood"
    if "lumber" in text or "thickness_in" in specs and specs.get("thickness_in") == 2:
        return "lumber"
    if "two-by-four" in text or "two by four" in text:
        return "lumber"
    return None


def _model_id(text: str) -> str | None:
    match = _MODEL.search(text)
    if match is None:
        return None
    return match.group(1)
