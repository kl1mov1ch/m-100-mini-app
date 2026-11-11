import re
import subprocess
from pathlib import Path


def main():
    result = subprocess.run(
        ["git", "diff", "--cached", "--diff-filter=ACMRT", "--name-only", "-z"],
        capture_output=True,
        check=True,
    )
    names = result.stdout.decode("utf-8").strip("\0").split("\0")
    failures = []
    patterns = (
        r"sk-[A-Za-z0-9_-]{20,}",
        r"\b\d{7,12}:[A-Za-z0-9_-]{30,}\b",
        r"https://[^\s/]+/rest/\d+/[A-Za-z0-9]{10,}",
        r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
        r"bitrix24public\.com/[a-zA-Z0-9.-]+/sheet/[a-zA-Z0-9]+",
    )
    for name in filter(None, names):
        path = Path(name)
        if name.startswith(("data/", "backups/", "deploy/secrets/")) or path.suffix in {
            ".sqlite3",
            ".xlsx",
            ".pem",
            ".key",
        }:
            failures.append(name)
            continue
        contents = subprocess.run(
            ["git", "show", f":{name}"], capture_output=True, check=True
        ).stdout.decode("utf-8")
        if any(re.search(pattern, contents) for pattern in patterns):
            failures.append(name)
    if failures:
        raise SystemExit("Проверьте файлы перед публикацией: " + ", ".join(failures))
    print(
        f"Проверено файлов: {len(names)}. Ключи, базы и публичные ссылки на рабочие таблицы не обнаружены."
    )


if __name__ == "__main__":
    main()
