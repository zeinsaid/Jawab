"""Text edits to a knowledge base's markdown (spec section 7, "Applying a saved entry").

Pure functions: they return the new markdown and never parse or save it. The caller runs
`parse_kb()` on the result and only saves it if that succeeds.
"""

import re

LEARNED_SECTION = "## Learned from the owner"
ENTRY_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VISIBILITIES = ("public", "internal")
MAX_ENTRY_CHARS = 4000

_HEADING = re.compile(r"^### (\S+)\s*$")
_SECTION = re.compile(r"^## Learned from the owner\s*$")


STATUSES = ("placeholder", "confirmed", "learned")


def meta_line(visibility: str, status: str = "learned") -> str:
    return f"**Visibility:** {visibility} · **Status:** {status}"


def entry_problems(entry_id: str, visibility: str, text: str) -> list[str]:
    """Plain-language problems with an entry the owner wants to save (empty if it's fine)."""
    problems = []
    if not ENTRY_ID.match(entry_id):
        problems.append("The ID must be lowercase words joined by hyphens, like holiday-christmas.")
    if visibility not in VISIBILITIES:
        problems.append("Visibility must be public or internal.")
    if not text.strip():
        problems.append("The entry text is empty.")
    elif len(text) > MAX_ENTRY_CHARS:
        problems.append(f"The entry text is too long (at most {MAX_ENTRY_CHARS} characters).")
    lines = text.splitlines()
    if any(line.lstrip().startswith("#") for line in lines):
        problems.append("No line of the text may start with '#'.")
    if any(line.strip() == "---" for line in lines):
        problems.append("No line of the text may be only '---'.")
    return problems


def free_id(entry_id: str, taken) -> str:
    """A new entry needs an unused ID: if it's taken, append -2 (then -3, ...)."""
    if entry_id not in taken:
        return entry_id
    n = 2
    while f"{entry_id}-{n}" in taken:
        n += 1
    return f"{entry_id}-{n}"


def add_entry(markdown: str, entry_id: str, visibility: str, text: str) -> str:
    """Append the entry to the "Learned from the owner" section, creating it at the end if missing."""
    block = [f"### {entry_id}", meta_line(visibility), "", *text.strip().splitlines()]
    lines = markdown.rstrip("\n").splitlines()

    start = next((i for i, line in enumerate(lines) if _SECTION.match(line)), None)
    if start is None:
        return "\n".join([*lines, "", "---", "", LEARNED_SECTION, "", *block]) + "\n"

    # The section ends at the next '---' or '## ' line (normally it's the last one in the file).
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() == "---" or lines[i].startswith("## ")), len(lines))
    before = lines[:end]
    while before and not before[-1].strip():
        before.pop()
    after = lines[end:]
    return "\n".join([*before, "", *block, *([""] + after if after else [])]) + "\n"


def update_entry(markdown: str, entry_id: str, visibility: str, text: str,
                 status: str = "learned") -> tuple[str, str]:
    """Replace an entry's body and set its status (learned by default: a saved answer).
    Returns (new markdown, old body text).

    The body is everything between the meta line and the next heading or '---', as in parse_kb.
    Raises KeyError if the entry isn't there.
    """
    lines = markdown.splitlines()
    heading = next((i for i, line in enumerate(lines)
                    if (m := _HEADING.match(line)) and m.group(1) == entry_id), None)
    if heading is None:
        raise KeyError(entry_id)
    meta = heading + 1
    while meta < len(lines) and not lines[meta].strip():
        meta += 1
    if meta >= len(lines):
        raise KeyError(entry_id)

    end = meta + 1
    while end < len(lines) and not lines[end].startswith("#") and lines[end].strip() != "---":
        end += 1
    old_body = "\n".join(lines[meta + 1:end]).strip()
    tail = lines[end:]
    new_lines = [*lines[:meta], meta_line(visibility, status), "", *text.strip().splitlines(), *([""] + tail if tail else [])]
    return "\n".join(new_lines) + ("\n" if markdown.endswith("\n") else ""), old_body
