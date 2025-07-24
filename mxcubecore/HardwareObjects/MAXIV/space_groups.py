from dataclasses import dataclass


@dataclass
class SpaceGroup:
    full_name: str
    number: int


SPACE_GROUPS = {
    "P1": SpaceGroup("P 1", 1),
    "P2": SpaceGroup("P 1 2 1", 3),
    "P21": SpaceGroup("P 1 21 1", 4),
    "C2": SpaceGroup("C 1 2 1", 5),
    "P222": SpaceGroup("P 2 2 2", 16),
    "P2221": SpaceGroup("P 2 2 21", 17),
    "P21212": SpaceGroup("P 21 21 2", 18),
    "P212121": SpaceGroup("P 21 21 21", 19),
    "C2221": SpaceGroup("C 2 2 21", 20),
    "C222": SpaceGroup("C 2 2 2", 21),
    "F222": SpaceGroup("F 2 2 2", 22),
    "I222": SpaceGroup("I 2 2 2", 23),
    "I212121": SpaceGroup("I 21 21 21", 24),
    "P4": SpaceGroup("P 4", 75),
    "P41": SpaceGroup("P 41", 76),
    "P42": SpaceGroup("P 42", 77),
    "P43": SpaceGroup("P 43", 78),
    "I4": SpaceGroup("I 4", 79),
    "I41": SpaceGroup("I 41", 80),
    "P422": SpaceGroup("P 4 2 2", 89),
    "P4212": SpaceGroup("P 4 21 2", 90),
    "P4122": SpaceGroup("P 41 2 2", 91),
    "P41212": SpaceGroup("P 41 21 2", 92),
    "P4222": SpaceGroup("P 42 2 2", 93),
    "P42212": SpaceGroup("P 42 21 2", 94),
    "P4322": SpaceGroup("P 43 2 2", 95),
    "P43212": SpaceGroup("P 43 21 2", 96),
    "I422": SpaceGroup("I 4 2 2", 97),
    "I4122": SpaceGroup("I 41 2 2", 98),
    "P3": SpaceGroup("P 3", 143),
    "P31": SpaceGroup("P 31", 144),
    "P32": SpaceGroup("P 32", 145),
    "H3": SpaceGroup("H 3", 146),
    # accordingly to https://en.wikipedia.org/wiki/List_of_space_groups 146 is R3 R 3
    "P312": SpaceGroup("P 3 1 2", 149),
    "P321": SpaceGroup("P 3 2 1", 150),
    "P3112": SpaceGroup("P 31 1 2", 151),
    "P3121": SpaceGroup("P 31 2 1", 152),
    "P3212": SpaceGroup("P 32 1 2", 153),
    "P3221": SpaceGroup("P 32 2 1", 154),
    "H32": SpaceGroup("H 3 2", 155),
    # accordingly to https://en.wikipedia.org/wiki/List_of_space_groups 155 is R32 R 3 2
    "P6": SpaceGroup("P 6", 168),
    "P61": SpaceGroup("P 61", 169),
    "P65": SpaceGroup("P 65", 170),
    "P62": SpaceGroup("P 62", 171),
    "P64": SpaceGroup("P 64", 172),
    "P63": SpaceGroup("P 63", 173),
    "P622": SpaceGroup("P 6 2 2", 177),
    "P6122": SpaceGroup("P 61 2 2", 178),
    "P6522": SpaceGroup("P 65 2 2", 179),
    "P6222": SpaceGroup("P 62 2 2", 180),
    "P6422": SpaceGroup("P 64 2 2", 181),
    "P6322": SpaceGroup("P 63 2 2", 182),
    "P23": SpaceGroup("P 2 3", 195),
    "F23": SpaceGroup("F 2 3", 196),
    "I23": SpaceGroup("I 2 3", 197),
    "P213": SpaceGroup("P 21 3", 198),
    "I213": SpaceGroup("I 21 3", 199),
    "P432": SpaceGroup("P 4 3 2", 207),
    "P4232": SpaceGroup("P 42 3 2", 208),
    "F432": SpaceGroup("F 4 3 2", 209),
    "F4132": SpaceGroup("F 41 3 2", 210),
    "I432": SpaceGroup("I 4 3 2", 211),
    "P4332": SpaceGroup("P 43 3 2", 212),
    "P4132": SpaceGroup("P 41 3 2", 213),
    "I4132": SpaceGroup("I 41 3 2", 214),
}


def _get_space_group(short_name: str) -> SpaceGroup:
    try:
        space_group = SPACE_GROUPS[short_name.upper()]
    except KeyError as exc:
        msg = (
            f"Unknown space group short name: {short_name}, "
            f"available short names: {list(SPACE_GROUPS.keys())}",
        )
        raise ValueError(msg) from exc
    return space_group


def get_full_name(short_name: str) -> str:
    return _get_space_group(short_name).full_name


def get_number(short_name: str) -> int:
    return _get_space_group(short_name).number
