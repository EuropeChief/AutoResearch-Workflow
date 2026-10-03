"""Synthetic input for entrypoint trials, not a recommended scientific baseline."""


def solve(numbers):
    result = []
    for number in numbers:
        index = len(result)
        result.append(number)
        while index and result[index-1] > number:
            result[index] = result[index-1]
            index -= 1
        result[index] = number
    return result
