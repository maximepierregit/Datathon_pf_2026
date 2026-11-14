"""Generate the mascot SVG set from shared parts.

Every pose reuses the same body, scarf, face and outline; a pose only picks
eyes, mouth, hands, props and extras.  Run:  python3 assets/mascot/build.py
"""
from math import hypot
from pathlib import Path

OUT = Path(__file__).parent / "svg"

NAVY = "#1c2140"
RED = "#d63738"
RED_DARK = "#b52a2e"
RED_LIGHT = "#e65a52"
CREAM = "#fdf5ea"
WHITE = "#ffffff"
PINK = "#e8606a"
BEIGE = "#f1dcbc"
BEIGE_DARK = "#dcc29c"
LENS = "#3d4f86"
SW = 6  # outline width in mascot units

def st(w=SW):
    return f'stroke="{NAVY}" stroke-width="{w}" stroke-linejoin="round" stroke-linecap="round"'


LINE, THIN = st(), st(SW * 0.75)


def rounded(pts, r=10):
    """Closed path through pts with every corner softened; a point may carry its own radius (x, y, r)."""
    n, corners = len(pts), []
    for i, p in enumerate(pts):
        rad = p[2] if len(p) > 2 else r
        ends = []
        for q in (pts[i - 1], pts[(i + 1) % n]):
            dx, dy = q[0] - p[0], q[1] - p[1]
            k = min(rad / hypot(dx, dy), 0.5)
            ends.append(f"{p[0] + dx * k:.1f},{p[1] + dy * k:.1f}")
        corners.append((ends[0], f"{p[0]},{p[1]}", ends[1]))
    d = f"M{corners[0][2]}"
    for a, c, b in corners[1:] + corners[:1]:
        d += f" L{a} Q{c} {b}"
    return d + " Z"

# ---------------------------------------------------------------- base shape
# Mascot frame: body is roughly 0..215 x 0..200, face centred at (136, 100).
BODY_PTS = [(0, 34, 12), (65, 8, 12), (112, 38, 9), (205, 4, 12), (218, 124, 18), (110, 176, 24), (6, 156, 18)]
BODY = rounded(BODY_PTS)
LOGO = rounded([pt[:2] for pt in BODY_PTS], 5)  # crisper variant for small sizes
HIGHLIGHT = "M140,32 Q170,20 196,11 Q205,8 206,18 L210,86 C196,62 172,42 140,32 Z"
GLINT = (f'<path d="M180,22 L194,17" stroke="{WHITE}" stroke-width="5" stroke-linecap="round" opacity=".85"/>'
         f'<circle cx="203" cy="32" r="3" fill="{WHITE}" opacity=".85"/>')

FEET = (f'<ellipse cx="66" cy="206" rx="20" ry="15" fill="{NAVY}"/>'
        f'<ellipse cx="228" cy="156" rx="17" ry="17" fill="{NAVY}"/>')

# scarf: a wrap hugging the bottom in a soft V (behind), a thick sagging front
# band that rounds the right edge, and two short loose ends on the left
SCARF_BACK = (
    f'<path d="M-14,160 C60,170 150,158 228,132 Q234,140 232,150 C206,178 168,204 132,212 '
    f'Q124,214 116,212 C76,206 20,194 -14,186 Z" fill="{RED}" {LINE}/>'
)
SCARF_TAIL = (
    f'<path d="{rounded([(-12, 186), (-34, 198), (-24, 226), (2, 210)], 7)}" fill="{RED_DARK}" {LINE}/>'
    f'<path d="{rounded([(-16, 164), (-46, 176), (-40, 206), (-12, 196)], 7)}" fill="{RED}" {LINE}/>'
)
SCARF_BAND = (
    f'<path d="M228,116 C200,140 150,152 92,152 C50,152 14,154 -12,163 Q-19,166 -20,173 L-23,190 '
    f'Q-24,198 -16,196 C10,190 40,186 76,186 C140,186 200,170 236,148 Q246,130 228,116 Z" fill="{RED}" {LINE}/>'
    f'<path d="M-4,186 C30,178 60,176 92,175 C150,174 200,160 228,141" fill="none" stroke="{RED_DARK}" stroke-width="5" stroke-linecap="round" opacity=".8"/>'
    f'<path d="M30,162 C70,166 120,164 160,156" fill="none" stroke="{RED_LIGHT}" stroke-width="4" stroke-linecap="round" opacity=".7"/>'
)

FACE_C = (139, 96)
FACE = f'<rect x="73" y="48" width="132" height="96" rx="48" fill="{CREAM}"/>'

EYE_L, EYE_R = (104, 93), (174, 93)


# --------------------------------------------------------------- face parts
def eyes(kind):
    out = []
    for (x, y) in (EYE_L, EYE_R):
        if kind in ("open", "wide"):
            rx, ry = (12.5, 19) if kind == "open" else (13.5, 20.5)
            out.append(f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="{NAVY}"/>'
                       f'<circle cx="{x - 4}" cy="{y - 8}" r="5.5" fill="{WHITE}"/>'
                       f'<circle cx="{x + 4.5}" cy="{y + 8}" r="2.5" fill="{WHITE}"/>')
        elif kind == "happy":   # ^ ^
            out.append(f'<path d="M{x-13},{y+5} Q{x},{y-13} {x+13},{y+5}" fill="none" {st(6)}/>')
        elif kind == "sleep":   # closed, sagging
            out.append(f'<path d="M{x-13},{y+2} Q{x},{y+12} {x+13},{y+2}" fill="none" {st(6)}/>')
        elif kind == "tired":   # half lidded
            out.append(f'<path d="M{x-12},{y} A12,15 0 0 0 {x+12},{y} Z" fill="{NAVY}"/>'
                       f'<path d="M{x-15},{y} L{x+15},{y}" {st(6)}/>'
                       f'<circle cx="{x - 4}" cy="{y + 4}" r="3" fill="{WHITE}"/>')
    return "".join(out)


def blush():
    (lx, ly), (rx, ry) = EYE_L, EYE_R
    return (f'<ellipse cx="{lx - 12}" cy="{ly + 24}" rx="10" ry="5.5" fill="{PINK}" opacity=".35"/>'
            f'<ellipse cx="{rx + 10}" cy="{ry + 24}" rx="10" ry="5.5" fill="{PINK}" opacity=".35"/>')


def brows(kind):
    if not kind:
        return ""
    w = st(5)
    (lx, ly), (rx, ry) = EYE_L, EYE_R
    if kind == "up":
        return (f'<path d="M{lx-8},{ly-27} Q{lx},{ly-33} {lx+8},{ly-28}" fill="none" {w}/>'
                f'<path d="M{rx-8},{ry-28} Q{rx},{ry-33} {rx+8},{ry-27}" fill="none" {w}/>')
    if kind == "worried":
        return (f'<path d="M{lx-11},{ly-22} Q{lx},{ly-23} {lx+10},{ly-30}" fill="none" {w}/>'
                f'<path d="M{rx-10},{ry-30} Q{rx},{ry-23} {rx+11},{ry-22}" fill="none" {w}/>')
    return ""


def mouth(kind):
    cx, cy = 140, 119
    def open_mouth(w, h, t):
        return (f'<path d="M{cx-w},{cy-2} Q{cx},{cy+1} {cx+w},{cy-2} Q{cx+w*.85},{cy+h} {cx},{cy+h} Q{cx-w*.85},{cy+h} {cx-w},{cy-2} Z" fill="{NAVY}"/>'
                f'<path d="M{cx-t},{cy+h-4} Q{cx},{cy+h-11} {cx+t},{cy+h-4} Q{cx},{cy+h} {cx-t},{cy+h-4} Z" fill="{PINK}"/>')
    if kind == "open":
        return open_mouth(14, 17, 8)
    if kind == "big":
        return open_mouth(17, 22, 10)
    if kind == "small":
        return open_mouth(10, 12, 5.5)
    if kind == "smile":
        return f'<path d="M{cx-13},{cy} Q{cx},{cy+12} {cx+13},{cy}" fill="none" {st(5)}/>'
    if kind == "smirk":
        return f'<path d="M{cx-12},{cy+4} Q{cx+2},{cy+11} {cx+14},{cy-1}" fill="none" {st(5)}/>'
    if kind == "o":
        return (f'<ellipse cx="{cx}" cy="{cy+5}" rx="8" ry="9" fill="{NAVY}"/>'
                f'<ellipse cx="{cx}" cy="{cy+9}" rx="4.5" ry="3.5" fill="{PINK}"/>')
    if kind == "flat":
        return f'<path d="M{cx-9},{cy+3} Q{cx},{cy+1} {cx+9},{cy+3}" fill="none" {st(5)}/>'
    if kind == "wavy":
        return f'<path d="M{cx-13},{cy+6} Q{cx-6},{cy} {cx},{cy+4} Q{cx+6},{cy+9} {cx+13},{cy+3}" fill="none" {st(5)}/>'
    return ""


def lens(x, y):
    return f"M{x-18},{y-11} L{x+18},{y-11} Q{x+23},{y-11} {x+22},{y-5} L{x+20},{y+5} Q{x+16},{y+19} {x},{y+18} Q{x-16},{y+19} {x-20},{y+5} L{x-22},{y-5} Q{x-23},{y-11} {x-18},{y-11} Z"


SUNGLASSES = (f'<path d="{lens(*EYE_L)} {lens(*EYE_R)}" fill="{NAVY}"/>'
              f'<path d="M{EYE_L[0]+18},{EYE_L[1]-7} L{EYE_R[0]-18},{EYE_R[1]-7}" {st(8)}/>'
              f'<path d="M{EYE_L[0]-12},{EYE_L[1]-2} L{EYE_L[0]-4},{EYE_L[1]-2} M{EYE_R[0]-12},{EYE_R[1]-2} L{EYE_R[0]-4},{EYE_R[1]-2}" '
              f'stroke="{WHITE}" stroke-width="3" stroke-linecap="round" opacity=".7"/>')


# ------------------------------------------------------------- hands & props
MITTEN = None  # drawn as an egg with a thumb bump, see hand()
THUMB_UP = "M-13,4 C-14,-4 -8,-8 -3,-8 L-4,-20 C-4,-26 4,-27 5,-20 L6,-8 L12,-8 C17,-8 18,-2 15,1 C17,4 16,9 13,10 C14,14 10,17 7,16 L-6,16 C-11,16 -13,10 -13,4 Z"
POINT = "M-10,10 C-14,2 -12,-8 -4,-9 L-2,-20 C-1,-25 6,-25 6,-19 L5,-7 C10,-6 13,-1 11,5 C9,12 -5,16 -10,10 Z"
MITT = ("M2,-15 C11,-15 15,-7 14,2 C13,11 8,15 0,15 C-8,15 -13,10 -13,4 "
        "C-19,3 -22,-4 -18,-8 C-15,-11 -12,-9 -11,-7 C-10,-12 -5,-15 2,-15 Z")


def hand(x, y, rot=0, shape=MITTEN, flip=False, s=1.0, cuff=True):
    """White mitten (thumb on the left unless flipped) on a navy sleeve end."""
    s *= 1.45
    sx = -s if flip else s
    ln = st(SW / s)
    body = (f'<path d="{MITT}" fill="{WHITE}" {ln}/>'
            f'<path d="M-11,-6 Q-9,-1 -12,3" fill="none" {st(SW * 0.55 / s)}/>') if shape is None else f'<path d="{shape}" fill="{WHITE}" {ln}/>'
    sleeve = f'<ellipse cx="0" cy="16" rx="12" ry="9" fill="{NAVY}"/>' if cuff else ""
    return f'<g transform="translate({x},{y}) rotate({rot}) scale({sx},{s})">{sleeve}{body}</g>'


def arm(d, w=30):
    return f'<path d="{d}" fill="none" stroke="{NAVY}" stroke-width="{w}" stroke-linecap="round"/>'


MUG = (f'<path d="M-15,-13 C-25,-13 -26,8 -14,8" fill="none" {st(6)}/>'
       f'<path d="{rounded([(-16, -20, 4), (16, -20, 4), (15, 22, 8), (-15, 22, 8)])}" fill="{NAVY}"/>'
       f'<ellipse cx="0" cy="-19" rx="14" ry="3" fill="#2c3360"/>'
       f'<path d="M-8,-11 L-8,11" stroke="{WHITE}" stroke-width="3.5" stroke-linecap="round" opacity=".3"/>')

LID, LID_RIM, DECK = "#34416c", "#5163a0", "#252d50"
# lid seen from behind in slight perspective, keyboard deck sticking out on the left
LAPTOP = (f'<path d="{rounded([(-80, 20), (40, 16), (52, 32), (-70, 40)], 8)}" fill="{DECK}" {LINE}/>'
          f'<path d="M-66,30 L38,25" stroke="{LID_RIM}" stroke-width="3" stroke-linecap="round" opacity=".7"/>'
          f'<path d="{rounded([(-36, -36), (50, -42), (46, 22), (-40, 26)], 11)}" fill="{LID}" {LINE}/>'
          f'<path d="{rounded([(-29, -29), (43, -34), (40, 15), (-32, 18)], 7)}" fill="none" stroke="{LID_RIM}" stroke-width="2.5" opacity=".55"/>'
          f'<path d="M14,-36 L40,-38 L22,-12 Z" fill="{WHITE}" opacity=".08"/>'
          f'<path transform="translate(5,-6) rotate(-3) scale(0.15) translate(-109,-90)" d="{LOGO}" fill="{RED}"/>')

MAP = (f'<path d="{rounded([(-40, -24), (-14, -30), (12, -24), (40, -30), (40, 26), (12, 32), (-14, 26), (-40, 32)], 4)}" fill="{BEIGE}" {THIN}/>'
       f'<path d="M-14,-27 L-14,24 M12,-21 L12,29" fill="none" stroke="{BEIGE_DARK}" stroke-width="3" stroke-linecap="round"/>'
       f'<path d="M-36,2 L36,0" fill="none" stroke="{BEIGE_DARK}" stroke-width="2.5" stroke-linecap="round"/>'
       f'<path d="M-30,-10 Q-20,-16 -6,-8 Q4,-2 22,-12" fill="none" stroke="{RED}" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="1 5"/>'
       f'<circle cx="24" cy="-13" r="3" fill="{RED}"/>')

BINOCULARS = (f'<path d="M-8,-6 L8,-6" stroke="{NAVY}" stroke-width="10" stroke-linecap="round"/>'
              f'<circle cx="-22" cy="0" r="20" fill="{NAVY}"/><circle cx="22" cy="0" r="20" fill="{NAVY}"/>'
              f'<circle cx="-22" cy="0" r="13" fill="{LENS}"/><circle cx="22" cy="0" r="13" fill="{LENS}"/>'
              f'<circle cx="-26" cy="-4" r="4" fill="{WHITE}" opacity=".6"/><circle cx="18" cy="-4" r="4" fill="{WHITE}" opacity=".6"/>')

FLAG = (f'<path d="M0,-88 L0,92" stroke="{NAVY}" stroke-width="7" stroke-linecap="round"/>'
        f'<circle cx="0" cy="-90" r="5" fill="{NAVY}"/>'
        f'<path d="M3,-84 C16,-90 26,-78 40,-84 Q45,-85 42,-80 L36,-70 Q34,-68 36,-66 L42,-58 Q44,-54 40,-54 C28,-50 16,-60 3,-54 Z" fill="{RED}" {THIN}/>')


# ------------------------------------------------------------------- extras
def lines(x, y, rot=0, s=1.0):
    return (f'<g transform="translate({x},{y}) rotate({rot}) scale({s})" {st(6)} fill="none">'
            f'<path d="M-22,4 L-10,10"/><path d="M-8,-16 L-2,-2"/><path d="M12,-22 L12,-6"/></g>')


def sparkle(x, y, s=1.0):
    return f'<path transform="translate({x},{y}) scale({s})" d="M0,-14 C1,-4 4,-1 13,0 C4,1 1,4 0,14 C-1,4 -4,1 -13,0 C-4,-1 -1,-4 0,-14 Z" fill="{NAVY}" {st(2)}/>'


def question(x, y):
    return (f'<path transform="translate({x},{y})" d="M-12,-8 C-12,-24 14,-24 14,-8 C14,2 2,4 2,14" fill="none" {st(7)}/>'
            f'<circle cx="{x + 2}" cy="{y + 28}" r="5" fill="{NAVY}"/>')


def zzz(x, y):
    z = lambda dx, dy, s: (f'<path transform="translate({x + dx},{y + dy}) scale({s})" '
                           f'd="M-8,-8 L8,-8 L-8,8 L8,8" fill="none" {st(5)}/>')
    return z(0, 10, 1.0) + z(24, -4, 0.8)


def swirl(x, y):
    return (f'<path transform="translate({x},{y})" d="M-2,14 C-18,10 -16,-12 2,-12 C16,-12 18,6 6,8 C-4,9 -6,-2 2,-3" fill="none" {st(4.5)}/>'
            f'<path transform="translate({x},{y})" d="M-8,18 Q0,22 8,16" fill="none" {st(4)}/>')


# -------------------------------------------------------------------- poses
# Each pose: transform of the mascot in a 300x300 cell + its parts.
# back = drawn behind the body, front = drawn over the scarf, top = cell coords.
POSES = {
    "01-wave": dict(rot=-4, eyes="open", brows="up", mouth="open",
                    back=arm("M40,150 C20,120 10,100 -2,76", 32),
                    front=hand(-4, 60, -20, s=1.15),
                    top=lines(40, 66, -10)),
    "02-happy": dict(rot=-6, eyes="happy", mouth="small",
                     front=hand(48, 150, -30) + hand(232, 118, 30, flip=True)),
    "03-question": dict(rot=-10, eyes="open", mouth="smile",
                        top=question(282, 66)),
    "04-thinking": dict(rot=-4, eyes="open", brows="up", mouth="smile",
                        front=hand(120, 158, 10, shape=POINT, s=1.05)),
    "05-surprised": dict(rot=-8, eyes="wide", brows="up", mouth="o",
                         front=hand(84, 150, -10, s=1.1) + hand(214, 140, 10, flip=True, s=1.1),
                         top=lines(282, 62, 60)),
    "06-coffee": dict(rot=-4, eyes="happy", mouth="smile",
                      front=f'<g transform="translate(152,160) scale(1.6)">{MUG}</g>'
                            + hand(112, 172, 10) + hand(200, 166, -10, flip=True)),
    "07-laptop": dict(rot=-4, eyes="open", mouth="smile",
                      front=f'<g transform="translate(194,176) rotate(-5) scale(1.36)">{LAPTOP}</g>' + hand(92, 186, 20, s=1.05),
                      top=lines(300, 92, 40, 0.8)),
    "08-map": dict(rot=-6, eyes="open", mouth="smile",
                   front=f'<g transform="translate(160,168) rotate(-10) scale(1.75)">{MAP}</g>'
                         + hand(90, 186, 10) + hand(232, 152, -10, flip=True)),
    "09-binoculars": dict(rot=-2, eyes="happy", brows="up", mouth="smile",
                          front=f'<g transform="translate(200,104) rotate(-6) scale(1.65)">{BINOCULARS}</g>' + hand(148, 150, -10)),
    "10-thumbsup": dict(rot=-4, eyes="open", mouth="smile",
                        front=hand(236, 118, 0, shape=THUMB_UP, s=1.1),
                        top=sparkle(290, 62)),
    "11-sleep": dict(rot=-8, sy=0.8, eyes="sleep", mouth="flat",
                     front=hand(236, 150, 0) + hand(80, 214, 0),
                     top=zzz(272, 70)),
    "12-tired": dict(rot=-6, eyes="tired", brows="worried", mouth="wavy",
                     front=hand(104, 196, 0) + hand(206, 186, 0, flip=True),
                     top=swirl(282, 62)),
    "13-cool": dict(rot=-6, eyes="open", mouth="smirk", glasses=True,
                    front=hand(234, 136, 10, s=1.1),
                    top=sparkle(282, 92)),
    "14-excited": dict(rot=-4, eyes="happy", mouth="big",
                       back=arm("M40,160 C20,140 10,120 2,100", 32) + arm("M200,150 C220,130 230,110 236,94", 32),
                       front=hand(2, 92, -20, s=1.1) + hand(238, 86, 20, flip=True, s=1.1),
                       top=lines(66, 60, -20)),
    "15-flag": dict(rot=-4, dx=-26, eyes="open", mouth="open",
                    front=f'<g transform="translate(252,96) scale(1.2)">{FLAG}</g>' + hand(250, 150, 0, flip=True, s=1.1)),
}

CELL = 340
SCALE = 0.95


def mascot(p):
    face = FACE + (blush() if p.get("blush", True) else "") + eyes(p.get("eyes")) + brows(p.get("brows")) + mouth(p.get("mouth"))
    if p.get("glasses"):
        face += SUNGLASSES
    body = (f'<path d="{BODY}" fill="{RED}" {LINE}/>'
            f'<path d="{HIGHLIGHT}" fill="{RED_LIGHT}" opacity=".55"/>' + GLINT)
    face = f'<g transform="rotate({p.get("tilt", -8)},{FACE_C[0]},{FACE_C[1]})">{face}</g>'
    inner = (FEET + p.get("back", "") + SCARF_BACK + SCARF_TAIL + body + face
             + SCARF_BAND + p.get("front", ""))
    return (f'<g transform="translate({CELL / 2 + p.get("dx", 0)},{CELL / 2 + 8}) rotate({p.get("rot", 0)}) '
            f'scale({SCALE},{SCALE * p.get("sy", 1)}) translate(-108,-104)">{inner}</g>{p.get("top", "")}')


def svg(content, w=CELL, h=CELL):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f'{content}</svg>\n')


def build():
    OUT.mkdir(exist_ok=True)
    cells = []
    for i, (name, p) in enumerate(POSES.items()):
        g = mascot(p)
        (OUT / f"{name}.svg").write_text(svg(g))
        cells.append(f'<g transform="translate({(i % 5) * CELL},{(i // 5) * CELL})">{g}</g>')
    (OUT.parent / "sheet.svg").write_text(svg("".join(cells), CELL * 5, CELL * 3))


if __name__ == "__main__":
    build()
