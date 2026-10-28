"""Small formatting helpers shared by the CLI and the report."""


def f1(x):
    return "-" if x is None else f"{x:.1f}"


def short_name(name):
    parts = [w for w in name.split() if w.rstrip(".") not in ("Jr", "Sr", "II", "III", "IV")]
    return parts[-1]


def inj(pl):
    return "" if pl.injury == "ACTIVE" else f" [{pl.injury}]"


def table(header, rows, text_cols=1):
    """Markdown table; the first text_cols columns are left-aligned, the rest right-aligned."""
    print("| " + " | ".join(header) + " |")
    print("|" + "|".join(":--" if i < text_cols else "--:" for i in range(len(header))) + "|")
    for r in rows:
        print("| " + " | ".join(r) + " |")
