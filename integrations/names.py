"""Choose collision-free user names without blocking creation."""
import secrets


def unique_name(name, exists, limit):
    if not exists(name):
        return name
    for _ in range(100):
        candidate = name[:limit - 5] + '-' + str(1000 + secrets.randbelow(9000))
        if not exists(candidate):
            return candidate
    raise ValueError('Could not generate an available name; please try again')
