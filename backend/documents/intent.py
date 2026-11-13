"""Resolve requested engineering disciplines, including small typing errors."""

import re
from difflib import SequenceMatcher

import snowballstemmer

from .profile import load_template


def requested_categories(query):
    value = str(query or "").casefold().replace("ё", "е")
    if "кроме" in value or re.search(r"все\s+(?:направления|категории|разделы)", value):
        return set()
    stemmer = snowballstemmer.stemmer("russian")
    words = stemmer.stemWords(re.findall(r"[а-я]+", value))
    result = set()
    for category, terms in load_template()["query_terms"].items():
        for term in stemmer.stemWords(list(terms)):
            if any(
                word == term
                or (
                    min(len(word), len(term)) >= 6
                    and SequenceMatcher(None, word, term).ratio() >= 0.9
                )
                for word in words
            ):
                result.add(category)
    return result


def select_works(works, query):
    categories = requested_categories(query)
    commissioning = bool(re.search(r"налад|пуск", str(query or ""), re.I))
    return [
        work
        for work in works
        if (not categories or work.get("category") in categories)
        and (
            commissioning
            or not re.search(
                r"пуск.?налад|пуско.?налад|^настройк|^статическ\w*\s+балансиров",
                " ".join([work.get("section", ""), work.get("subsection", ""), work["name"]]),
                re.I,
            )
        )
    ]
