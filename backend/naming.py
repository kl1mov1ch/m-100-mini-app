import unicodedata
from collections import defaultdict


def project_name_key(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().replace("ё", "е").split())


def unique_project_name(name, existing):
    base = " ".join(unicodedata.normalize("NFKC", name).split())
    names = {project_name_key(value) for value in existing}
    candidate = base
    counter = 2
    while project_name_key(candidate) in names:
        suffix = f" ({counter})"
        candidate = base[: 100 - len(suffix)] + suffix
        counter += 1
    return candidate


def normalize_existing_project_names(projects):
    reserved = defaultdict(list)
    seen = defaultdict(set)
    changes = []
    for project in projects:
        reserved[project.owner_id].append(project.name)
    for project in projects:
        owner = project.owner_id
        if project_name_key(project.name) in seen[owner]:
            before = project.name
            project.name = unique_project_name(before, reserved[owner])
            reserved[owner].append(project.name)
            changes.append((project, before))
        seen[owner].add(project_name_key(project.name))
    return changes
