ENCODE_MAP = {
    "A": "O", "B": "M", "C": "K", "D": "T", "E": "U", "F": "V", "G": "J",
    "H": "R", "I": "Y", "J": "Q", "K": "L", "L": "P", "M": "N", "N": "S",
    "O": "A", "P": "D", "Q": "Z", "R": "H", "S": "G", "T": "E", "U": "I",
    "V": "F", "W": "X", "X": "C", "Y": "B", "Z": "W",
}
DECODE_MAP = {value: key for key, value in ENCODE_MAP.items()}


def _translate(text, mapping):
    output = []
    for char in text:
        upper = char.upper()
        if upper not in mapping:
            output.append(char)
            continue
        translated = mapping[upper]
        output.append(translated.lower() if char.islower() else translated)
    return "".join(output)


def encode(text):
    return _translate(text, ENCODE_MAP)


def decode(text):
    return _translate(text, DECODE_MAP)
