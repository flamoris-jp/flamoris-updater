import re
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    errors = []
    for path in [*root.glob("*.md"), *root.joinpath("docs").rglob("*.md")]:
        for destination in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            if destination.startswith(("http:", "https:", "mailto:", "#")):
                continue
            target = destination.split("#", 1)[0]
            if target and not (path.parent / target).exists():
                errors.append(str(path.relative_to(root)) + ": " + target)
    if errors:
        raise SystemExit("\n".join(errors))
    print("Local documentation links verified")


if __name__ == "__main__":
    main()
