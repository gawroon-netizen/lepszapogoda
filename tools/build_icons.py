"""Generate the 12 weather icons (SPEC §6, §15) as SVG from shared shapes. Run: python -m tools.build_icons"""

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "web" / "app" / "static" / "icons"


def sun(x=32, y=30, r=10):
    rays = "".join(
        f'<rect x="-1.6" y="-{r + 8}" width="3.2" height="5" rx="1.6" transform="translate({x} {y}) rotate({a})"/>'
        for a in range(0, 360, 45)
    )
    return f'<g fill="#f5b301"><circle cx="{x}" cy="{y}" r="{r}"/>{rays}</g>'


def cloud(c="#9aa5b1", dx=0, dy=0, s=1.0):
    # a simple cloud: three bumps on a flat base, scaled around (32, 40)
    return (
        f'<g transform="translate({32 + dx} {38 + dy}) scale({s}) translate(-32 -38)"><path fill="{c}" '
        'd="M14 46a9 9 0 0 1 1.5-17.9A13 13 0 0 1 40 22a11 11 0 0 1 12.5 9.2A8 8 0 0 1 50 46z"/></g>'
    )


def drops(n, color="#3d8bfd", y=50):
    xs = {1: [32], 2: [26, 38], 3: [22, 32, 42]}[n]
    return "".join(
        f'<path fill="{color}" d="M{x} {y}c-2 3-3.5 5-3.5 7a3.5 3.5 0 0 0 7 0c0-2-1.5-4-3.5-7z"/>' for x in xs
    )


def flakes(xs=(24, 40), y=55):
    out = ""
    for x in xs:
        out += f'<g stroke="#5aa9e6" stroke-width="2" stroke-linecap="round" transform="translate({x} {y})">'
        out += "".join(f'<line x1="0" y1="-5" x2="0" y2="5" transform="rotate({a})"/>' for a in (0, 60, 120))
        out += "</g>"
    return out


BOLT = '<path fill="#f59e0b" d="M34 44l-8 12h6l-3 8 10-13h-6l4-7z"/>'
WIND = (
    '<g fill="none" stroke="#6b7785" stroke-width="3.5" stroke-linecap="round">'
    '<path d="M8 26h30a6 6 0 1 0-6-6"/><path d="M8 36h40a6 6 0 1 1-6 6"/><path d="M8 46h22"/></g>'
)

ICONS = {
    "slonecznie": sun(32, 32, 12),
    "malo-chmur": sun(24, 24, 9) + cloud("#c3cbd4", 8, 6, 0.75),
    "czesciowe": sun(22, 22, 9) + cloud("#9aa5b1", 4, 2, 0.95),
    "pochmurno": cloud("#c3cbd4", -6, -6, 0.8) + cloud("#9aa5b1", 4, 2, 0.95),
    "zachmurzenie": cloud("#9aa5b1", -6, -6, 0.85) + cloud("#6b7785", 3, 2, 1.0),
    "mzawka": cloud("#9aa5b1", 0, -6) + drops(1),
    "deszcz": cloud("#7d8996", 0, -6) + drops(2),
    "ulewa": cloud("#5c6773", 0, -6) + drops(3, "#2563eb"),
    "snieg": cloud("#9aa5b1", 0, -6) + flakes(),
    "deszcz-snieg": cloud("#9aa5b1", 0, -6) + drops(1, y=50).replace("M32", "M24") + flakes((40,)),
    "burza": cloud("#5c6773", 0, -8) + BOLT,
    "wietrznie": WIND,
}

LOGO = sun(24, 26, 9) + cloud("#3d8bfd", 6, 4, 0.9)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in {**ICONS, "logo": LOGO}.items():
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">{body}</svg>\n'
        (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
    print(f"{len(ICONS)} icons + logo written to {OUT}")


if __name__ == "__main__":
    main()
