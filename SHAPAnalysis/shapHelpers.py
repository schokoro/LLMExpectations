def getBitArray(i: int, bits: int) -> list[bool]:
    result = []
    for position in range(bits - 1, -1, -1):
        bit_value = (i >> position) & 1
        result.append(bool(bit_value))
    return result

