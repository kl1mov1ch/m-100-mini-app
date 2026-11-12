import unicodedata


def unique_project_name(name, existing):
    def key(value):
        return " ".join(unicodedata.normalize("NFKC", value).casefold().replace("ё", "е").split())

    base = " ".join(unicodedata.normalize("NFKC", name).split())
    names = {key(value) for value in existing}
    candidate = base
    counter = 2
    while key(candidate) in names:
        suffix = f" ({counter})"
        candidate = base[: 100 - len(suffix)] + suffix
        counter += 1
    return candidate
