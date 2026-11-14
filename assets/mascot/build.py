"""Generate the mascot SVG set from shared parts.

Every pose reuses the same body, scarf, face and outline; a pose only picks
eyes, mouth, hands, props and extras.  Run:  python3 assets/mascot/build.py
"""
from math import acos, cos, hypot, radians, sin, tan
from pathlib import Path

OUT = Path(__file__).parent / "svg"

NAVY = "#1c2140"
SLEEVE = "#2c3360"
RED = "#d63738"
RED_LIGHT = "#e8665d"
SCARF = "#c22f39"
SCARF_DARK = "#a2262f"
SCARF_LIGHT = "#d9454c"
CREAM = "#fdf5ea"
WHITE = "#ffffff"
PINK = "#ef7f86"
BEIGE = "#f3e0c2"
BEIGE_DARK = "#dcc29c"
LENS = "#4a5d96"
DROP = "#bfe3f7"
SW = 6  # outline width in mascot units


def st(w=SW):
    return f'stroke="{NAVY}" stroke-width="{w:.2f}" stroke-linejoin="round" stroke-linecap="round"'


LINE = st()


def rounded(pts, r=10):
    """Closed path through pts with circular corners of true radius r; a point may carry its own (x, y, r)."""
    n, corners = len(pts), []
    for i, p in enumerate(pts):
        a, b = pts[i - 1], pts[(i + 1) % n]
        u, v = (a[0] - p[0], a[1] - p[1]), (b[0] - p[0], b[1] - p[1])
        lu, lv = hypot(*u), hypot(*v)
        theta = acos(max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (lu * lv))))
        rad = p[2] if len(p) > 2 else r
        t = min(rad / tan(theta / 2), lu / 2, lv / 2)
        rad = t * tan(theta / 2)
        p1 = (p[0] + u[0] / lu * t, p[1] + u[1] / lu * t)
        p2 = (p[0] + v[0] / lv * t, p[1] + v[1] / lv * t)
        sweep = 1 if (p[0] - a[0]) * (b[1] - p[1]) - (p[1] - a[1]) * (b[0] - p[0]) > 0 else 0
        corners.append((p1, p2, rad, sweep))
    d = "M{:.1f},{:.1f}".format(*corners[0][1])
    for p1, p2, rad, sweep in corners[1:] + corners[:1]:
        d += f" L{p1[0]:.1f},{p1[1]:.1f} A{rad:.1f},{rad:.1f} 0 0 {sweep} {p2[0]:.1f},{p2[1]:.1f}"
    return d + " Z"


# ---------------------------------------------------------------- animation
# Discreet CSS loops embedded in each SVG (they run inside <img> too). Animated
# parts are wrapped in their own <g class> so CSS never fights a transform attribute.
# --d offsets a whole cell so poses on one page don't move in lockstep.
STYLE = """<style>
.bob,.blink,.sway,.wave,.pump,.tap,.tilt,.scan,.twinkle,.float,.zzz,.dot,.pulse,.drip,.flutter{
 transform-box:fill-box;animation-delay:var(--d,0s);animation-iteration-count:infinite;animation-timing-function:ease-in-out}
.bob{animation-name:pp-bob;animation-duration:3.6s}
.bob.slow{animation-name:pp-breathe;animation-duration:5s}
.bob.bouncy{animation-name:pp-hop;animation-duration:1.8s}
.blink{transform-origin:50% 50%;animation-name:pp-blink;animation-duration:5.2s;animation-timing-function:linear}
.sway{transform-origin:55% 0%;animation-name:pp-sway;animation-duration:3.6s}
.wave{transform-origin:50% 90%;animation-name:pp-wave;animation-duration:1.8s}
.pump{animation-name:pp-pump;animation-duration:2.4s}
.tap{animation-name:pp-tap;animation-duration:.9s}
.tilt{transform-origin:50% 50%;animation-name:pp-tilt;animation-duration:4s}
.scan{animation-name:pp-scan;animation-duration:4.4s}
.twinkle{transform-origin:50% 50%;animation-name:pp-twinkle;animation-duration:2.6s}
.float{animation-name:pp-float;animation-duration:3s}
.zzz{animation-name:pp-zzz;animation-duration:3.4s}
.dot{animation-name:pp-dot;animation-duration:1.6s}
.pulse{transform-origin:50% 50%;animation-name:pp-pulse;animation-duration:1.6s}
.drip{animation-name:pp-drip;animation-duration:3.2s;animation-timing-function:ease-in}
.flutter{transform-origin:0% 50%;animation-name:pp-flutter;animation-duration:2s}
.late{animation-delay:calc(var(--d,0s) - .45s)}
@keyframes pp-bob{50%{transform:translateY(-3px)}}
@keyframes pp-breathe{50%{transform:translateY(-1.5px) scaleY(1.01)}}
@keyframes pp-hop{0%,100%{transform:translateY(0)}40%{transform:translateY(-6px)}60%{transform:translateY(-5px)}}
@keyframes pp-blink{0%,92%,100%{transform:scaleY(1)}95%{transform:scaleY(.1)}}
@keyframes pp-sway{50%{transform:rotate(5deg)}}
@keyframes pp-wave{0%,100%{transform:rotate(-8deg)}50%{transform:rotate(14deg)}}
@keyframes pp-pump{50%{transform:translateY(-4px)}}
@keyframes pp-tap{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-3px)}}
@keyframes pp-tilt{50%{transform:rotate(-2.5deg)}}
@keyframes pp-scan{0%,100%{transform:translateX(0)}30%{transform:translateX(-4px)}70%{transform:translateX(4px)}}
@keyframes pp-twinkle{50%{transform:scale(.65) rotate(25deg);opacity:.55}}
@keyframes pp-float{0%,100%{transform:translateY(0) rotate(0)}50%{transform:translateY(-5px) rotate(6deg)}}
@keyframes pp-zzz{0%{transform:translate(0,6px);opacity:0}25%,70%{opacity:1}100%{transform:translate(6px,-8px);opacity:0}}
@keyframes pp-dot{0%,100%{opacity:.25}40%{opacity:1}}
@keyframes pp-pulse{50%{transform:scale(.85);opacity:.45}}
@keyframes pp-drip{0%{transform:translateY(-2px);opacity:0}20%{opacity:1}80%{transform:translateY(6px);opacity:1}100%{transform:translateY(9px);opacity:0}}
@keyframes pp-flutter{50%{transform:scaleX(.92) skewY(5deg)}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
</style>"""


def anim(cls, content, delay=None):
    style = f' style="animation-delay:calc(var(--d,0s) + {delay}s)"' if delay is not None else ""
    return f'<g class="{cls}"{style}>{content}</g>'


# ---------------------------------------------------------------- base shape
# Mascot frame: body is roughly 0..218 x 0..176, face centred at FACE_C.
BODY_PTS = [(0, 34, 14), (65, 8, 14), (112, 38, 10), (205, 4, 14), (218, 124, 22), (110, 176, 26), (6, 156, 20)]
BODY = rounded(BODY_PTS)
LOGO = rounded([pt[:2] for pt in BODY_PTS], 14)  # crisper variant for small sizes
SHINE = (f'<path d="M150,34 L184,21 Q195,17 196,28 L199,60" fill="none" stroke="{RED_LIGHT}" '
         f'stroke-width="5" stroke-linecap="round" stroke-linejoin="round" opacity=".45"/>'
         f'<path d="M172,26 L180,23" stroke="{WHITE}" stroke-width="4" stroke-linecap="round" opacity=".55"/>')

FEET = (f'<ellipse cx="84" cy="190" rx="16" ry="11" fill="{SLEEVE}" {LINE}/>'
        f'<ellipse cx="154" cy="186" rx="16" ry="11" fill="{SLEEVE}" {LINE}/>')

# scarf: one soft band that tucks the chin in and hides the bottom of the body,
# knotted on the left with two tapered ends hanging down
SCARF_TAIL = (
    f'<path d="{rounded([(8, 186), (22, 184), (26, 214), (8, 217)], 4)}" fill="{SCARF_DARK}" {LINE}/>'
    f'<path d="{rounded([(-8, 182), (6, 186), (-6, 214), (-24, 207)], 4)}" fill="{SCARF}" {LINE}/>'
    f'<path d="M-3,191 L-11,206" fill="none" stroke="{SCARF_DARK}" stroke-width="3" stroke-linecap="round"/>'
)
SCARF_BAND = (
    f'<path d="M212,118 C200,132 170,144 120,147 C80,149 34,150 12,158 C4,162 4,186 12,188 '
    f'C30,187 60,185 96,185 C150,185 202,170 229,147 C237,140 238,118 228,110 C222,106 215,112 212,118 Z" fill="{SCARF}" {LINE}/>'
    f'<path d="M26,178 C52,175 80,174 104,174 C150,174 190,163 212,148" fill="none" stroke="{SCARF_DARK}" '
    f'stroke-width="4.5" stroke-linecap="round" opacity=".85"/>'
    f'<path d="M50,159 C84,158 120,157 156,151" fill="none" stroke="{SCARF_LIGHT}" stroke-width="4" stroke-linecap="round"/>'
    f'<path d="{rounded([(-6, 164), (24, 162), (22, 190), (-2, 192)], 9)}" fill="{SCARF}" {LINE}/>'
    f'<path d="M4,172 Q9,177 8,184" fill="none" stroke="{SCARF_DARK}" stroke-width="3" stroke-linecap="round"/>'
)

FACE_C = (134, 100)
FACE = (f'<path d="M134,48 C175,48 196,64 196,100 C196,136 175,152 134,152 C92,160 72,142 72,100 '
        f'C72,64 93,48 134,48 Z" fill="{CREAM}"/>')

EYE_DX, EYE_DY = 28, 2
EYE_L, EYE_R = (FACE_C[0] - EYE_DX, FACE_C[1] + EYE_DY), (FACE_C[0] + EYE_DX, FACE_C[1] + EYE_DY)
MOUTH = (FACE_C[0], FACE_C[1] + 24)


# --------------------------------------------------------------- face parts
def eyes(kind):
    out = []
    for (x, y) in (EYE_L, EYE_R):
        if kind in ("open", "wide", "soft"):
            rx, ry = {"open": (11.5, 16.5), "wide": (13.5, 18.5), "soft": (11, 14.5)}[kind]
            out.append(f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="{NAVY}"/>'
                       f'<circle cx="{x - 3.5}" cy="{y - 6}" r="4.5" fill="{WHITE}"/>'
                       f'<circle cx="{x + 4}" cy="{y + 6}" r="2" fill="{WHITE}"/>')
        elif kind == "happy":   # ^ ^
            out.append(f'<path d="M{x-12},{y+4} Q{x},{y-11} {x+12},{y+4}" fill="none" {st(6)}/>')
        elif kind == "sleep":   # closed, relaxed
            out.append(f'<path d="M{x-11},{y} Q{x},{y+9} {x+11},{y}" fill="none" {st(5.5)}/>')
    return anim("blink", "".join(out)) if kind in ("open", "wide", "soft") else "".join(out)


def blush():
    (lx, ly), (rx, ry) = EYE_L, EYE_R
    return (f'<ellipse cx="{lx - 10}" cy="{ly + 20}" rx="9" ry="5" fill="{PINK}" opacity=".4"/>'
            f'<ellipse cx="{rx + 10}" cy="{ry + 20}" rx="9" ry="5" fill="{PINK}" opacity=".4"/>')


def brows(kind):
    if not kind:
        return ""
    w = st(5)
    (lx, ly), (rx, ry) = EYE_L, EYE_R
    left = f'<path d="M{lx-7},{ly-28} Q{lx},{ly-33} {lx+7},{ly-29}" fill="none" {w}/>'
    right = f'<path d="M{rx-7},{ry-29} Q{rx},{ry-33} {rx+7},{ry-28}" fill="none" {w}/>'
    if kind == "up":
        return left + right
    if kind == "raised":    # one brow up, the other relaxed
        return (f'<path d="M{lx-7},{ly-25} Q{lx},{ly-27} {lx+7},{ly-25}" fill="none" {w}/>'
                f'<path d="M{rx-7},{ry-31} Q{rx},{ry-37} {rx+7},{ry-32}" fill="none" {w}/>')
    if kind == "worried":
        return (f'<path d="M{lx-7},{ly-24} Q{lx},{ly-25} {lx+7},{ly-29}" fill="none" {w}/>'
                f'<path d="M{rx-7},{ry-29} Q{rx},{ry-25} {rx+7},{ry-24}" fill="none" {w}/>')
    return ""


def mouth(kind, dx=0):
    cx, cy = MOUTH[0] + dx, MOUTH[1]

    def open_mouth(w, h, t):
        return (f'<path d="M{cx-w},{cy-2} Q{cx},{cy+1} {cx+w},{cy-2} Q{cx+w*.9},{cy+h} {cx},{cy+h} '
                f'Q{cx-w*.9},{cy+h} {cx-w},{cy-2} Z" fill="{NAVY}" {st(2)}/>'
                f'<path d="M{cx-t},{cy+h-4} Q{cx},{cy+h-10} {cx+t},{cy+h-4} Q{cx},{cy+h} {cx-t},{cy+h-4} Z" fill="{PINK}"/>')
    if kind == "open":
        return open_mouth(12, 15, 7)
    if kind == "big":
        return open_mouth(15, 18, 9)
    if kind == "small":
        return open_mouth(9, 11, 5)
    if kind == "smile":
        return f'<path d="M{cx-11},{cy} Q{cx},{cy+11} {cx+11},{cy}" fill="none" {st(5)}/>'
    if kind == "content":
        return f'<path d="M{cx-7},{cy+2} Q{cx},{cy+8} {cx+7},{cy+2}" fill="none" {st(5)}/>'
    if kind == "o":
        return (f'<ellipse cx="{cx}" cy="{cy+4}" rx="7" ry="8.5" fill="{NAVY}"/>'
                f'<ellipse cx="{cx}" cy="{cy+8}" rx="4" ry="3" fill="{PINK}"/>')
    if kind == "wavy":
        return f'<path d="M{cx-9},{cy+5} Q{cx-4.5},{cy+2} {cx},{cy+5} Q{cx+4.5},{cy+8} {cx+9},{cy+5}" fill="none" {st(5)}/>'
    return ""


def sunglasses():
    out = []
    for (x, y) in (EYE_L, EYE_R):
        y += 2
        out.append(f'<rect x="{x-15}" y="{y-12}" width="30" height="24" rx="12" fill="{NAVY}"/>'
                   f'<path d="M{x-9},{y-5} Q{x-6},{y-8} {x-1},{y-8}" fill="none" stroke="{WHITE}" '
                   f'stroke-width="3.5" stroke-linecap="round" opacity=".75"/>')
    (lx, ly), (rx, _) = EYE_L, EYE_R
    out.append(f'<path d="M{lx+14},{ly-1} Q{FACE_C[0]},{ly-7} {rx-14},{ly-1}" fill="none" {st(5)}/>')
    return "".join(out)


# ------------------------------------------------------------- hands & props
MITT = ("M2,-15 C11,-15 15,-7 14,2 C13,11 8,15 0,15 C-6,15 -10,12 -12,9 "
        "C-17,8 -21,2 -21,-4 C-21,-9 -17,-10 -15,-8 Q-13,-6 -11.5,-7 C-9,-12 -4,-15 2,-15 Z")
THUMB_UP = ("M-13,4 C-14,-4 -10,-8 -6,-8 C-7,-12 -8,-16 -7,-19 C-6,-27 8,-27 7,-19 C7,-15 7,-11 7,-8 "
            "Q12,-9 14,-6 C18,-3 17,1 15,2 C18,5 17,10 13,11 C15,15 11,18 7,17 L-6,17 C-11,17 -13,11 -13,4 Z")
HAND_S = 1.3  # every hand is drawn at this one size


def hand(x, y, rot=0, shape="mitt", flip=False, cuff=False):
    """White mitten (thumb on the left unless flipped); cuff=True adds a sleeve end below it."""
    s = HAND_S
    sx = -s if flip else s
    ln = st(SW / s)
    if shape == "mitt":
        body = f'<path d="{MITT}" fill="{WHITE}" {ln}/>'
    else:
        body = (f'<path d="{THUMB_UP}" fill="{WHITE}" {ln}/>'
                f'<path d="M6,2 L15,2 M6,10.5 L14,10.5" fill="none" {st(3.5 / s)}/>')
    sleeve = f'<ellipse cx="0" cy="14" rx="9" ry="6" fill="{SLEEVE}" {ln}/>' if cuff else ""
    return f'<g transform="translate({x},{y}) rotate({rot}) scale({sx},{s})">{sleeve}{body}</g>'


SHOULDER_L, SHOULDER_R = (18, 128), (214, 118)


def arm(d, w=28):
    """Sleeve: navy outline with a lighter navy core, drawn behind the body."""
    return (f'<path d="{d}" fill="none" stroke="{NAVY}" stroke-width="{w}" stroke-linecap="round"/>'
            f'<path d="{d}" fill="none" stroke="{SLEEVE}" stroke-width="{w - 2 * SW}" stroke-linecap="round"/>')


def place(content, x, y, rot=0, s=1.0):
    return f'<g transform="translate({x},{y}) rotate({rot}) scale({s})">{content(s)}</g>'


def mug(s):
    ln = st(SW / s)
    return (f'<path d="M15,-13 C28,-13 28,5 15,5" fill="none" {ln}/>'
            f'<path d="{rounded([(-16, -20), (16, -20), (15, 20), (-15, 20)], 6)}" fill="{LID}" {ln}/>'
            f'<ellipse cx="0" cy="-17" rx="12" ry="2.5" fill="{NAVY}" opacity=".5"/>'
            f'<path d="M-9,-9 L-9,10" stroke="{WHITE}" stroke-width="{3.5 / s:.2f}" stroke-linecap="round" opacity=".3"/>'
            f'<path transform="translate(3,-2) scale(0.075) translate(-109,-90)" d="{LOGO}" fill="{RED}"/>')


LID, LID_RIM, DECK = "#34416c", "#5163a0", "#252d50"


def laptop(s):
    """Lid seen from behind (16:10), thin keyboard deck peeking under the hinge."""
    ln = st(SW / s)
    return (f'<path d="{rounded([(-56, -2), (56, -4), (60, 8), (-60, 10)], 5)}" fill="{DECK}" {ln}/>'
            f'<path d="{rounded([(-52, -62), (52, -66), (50, 0), (-50, 2)], 10)}" fill="{LID}" {ln}/>'
            f'<path d="{rounded([(-44, -54), (44, -58), (42, -8), (-42, -6)], 6)}" fill="none" stroke="{LID_RIM}" '
            f'stroke-width="{2.5 / s:.2f}" opacity=".55"/>'
            f'<path d="{rounded([(18, -56), (40, -57), (24, -36)], 4)}" fill="{WHITE}" opacity=".08"/>'
            f'<path transform="translate(0,-32) rotate(-2) scale(0.17) translate(-109,-90)" d="{LOGO}" fill="{RED}"/>')


def map_(s):
    ln = st(SW / s)
    return (f'<path d="{rounded([(-40, -24), (-14, -30), (12, -24), (40, -30), (40, 26), (12, 32), (-14, 26), (-40, 32)], 4)}" '
            f'fill="{BEIGE}" {ln}/>'
            f'<path d="M-14,-29 L12,-23 L12,31 L-14,25 Z" fill="{BEIGE_DARK}" opacity=".45"/>'
            f'<path d="M-30,-10 Q-20,-16 -6,-8 Q4,-2 22,-12" fill="none" stroke="{RED}" stroke-width="{2.5 / s:.2f}" '
            f'stroke-linecap="round" stroke-dasharray="{1 / s:.2f} {5 / s:.2f}"/>'
            f'<circle cx="24" cy="-13" r="3" fill="{RED}"/>')


def binoculars(s):
    ln = st(SW / s)
    out = f'<path d="{rounded([(-12, -8), (12, -8), (12, 6), (-12, 6)], 5)}" fill="{NAVY}" {ln}/>'
    for x in (-EYE_DX, EYE_DX):
        out += (f'<circle cx="{x}" cy="0" r="21" fill="{NAVY}" {ln}/>'
                f'<circle cx="{x}" cy="0" r="13.5" fill="{LENS}"/>'
                f'<circle cx="{x - 5}" cy="-5" r="4" fill="{WHITE}" opacity=".7"/>')
    return out


def flag(s):
    ln = st(SW / s)
    return (f'<path d="M0,-70 L0,90" stroke="{NAVY}" stroke-width="{10 / s:.2f}" stroke-linecap="round"/>'
            f'<path d="M0,-66 L0,86" stroke="#3b4775" stroke-width="{3 / s:.2f}" stroke-linecap="round"/>'
            f'<circle cx="0" cy="-72" r="6.5" fill="{NAVY}"/>'
            f'<g class="flutter"><path d="M4,-66 C20,-74 36,-58 58,-66 C64,-68 66,-63 63,-59 L55,-46 C53,-43 53,-41 55,-38 L62,-27 '
            f'C65,-22 62,-19 58,-19 C38,-15 22,-29 4,-23 Z" fill="{RED}" {ln}/>'
            f'<path d="M14,-58 C26,-62 36,-52 48,-56" fill="none" stroke="{RED_LIGHT}" stroke-width="{3.5 / s:.2f}" '
            f'stroke-linecap="round" opacity=".7"/></g>')


# ------------------------------------------------------------------- extras
def lines(x, y, rot=0, s=1.0):
    """Three short strokes radiating from (x, y); rot is the middle stroke's direction (0 = up)."""
    out = ""
    for a in (rot - 38, rot, rot + 38):
        dx, dy = sin(radians(a)), -cos(radians(a))
        out += f'<path d="M{x + dx * 13 * s:.1f},{y + dy * 13 * s:.1f} L{x + dx * 24 * s:.1f},{y + dy * 24 * s:.1f}"/>'
    return anim("pulse", f'<g fill="none" {st(5.5)}>{out}</g>')


def sparkle(x, y, s=1.0):
    return anim("twinkle", f'<path transform="translate({x},{y}) scale({s})" d="M0,-14 C1,-4 4,-1 13,0 C4,1 1,4 0,14 '
                           f'C-1,4 -4,1 -13,0 C-4,-1 -1,-4 0,-14 Z" fill="{NAVY}" {st(2)}/>')


def question(x, y):
    return anim("float", f'<path transform="translate({x},{y})" d="M-11,-8 C-11,-22 13,-22 13,-8 C13,1 2,3 2,12" fill="none" {st(5.5)}/>'
                         f'<circle cx="{x + 2}" cy="{y + 24}" r="4.5" fill="{NAVY}"/>')


def dots(x, y):
    return "".join(anim("dot", f'<circle cx="{x + i * 12}" cy="{y - i * 3}" r="{3.5 + i * 0.5}" fill="{NAVY}"/>', i * 0.25)
                   for i in range(3))


def zzz(x, y):
    z = lambda dx, dy, s: (f'<path transform="translate({x + dx},{y + dy}) scale({s})" '
                           f'd="M-7,-7 L7,-7 L-7,7 L7,7" fill="none" {st(5 / s)}/>')
    return anim("zzz", z(0, 10, 1.0)) + anim("zzz", z(22, -6, 0.75), 1.1)


def drop(x, y, s=1.0):
    return anim("drip", f'<path transform="translate({x},{y}) scale({s})" d="M0,-12 C5,-4 9,1 9,6 C9,11 5,14 0,14 '
                        f'C-5,14 -9,11 -9,6 C-9,1 -5,-4 0,-12 Z" fill="{DROP}" {st(4.5 / s)}/>')


# -------------------------------------------------------------------- poses
# Each pose: transform of the mascot in a CELL x CELL cell + its parts.
# back = drawn behind the body, front = drawn over the scarf, top = cell coords.
POSES = {
    "01-wave": dict(rot=-6, dx=8, eyes="open", mouth="open",
                    back=arm("M16,124 C-4,118 -20,104 -24,88"),
                    front=anim("wave", hand(-24, 76, -18)),
                    top=lines(50, 64, -40)),
    "02-happy": dict(rot=-4, eyes="happy", mouth="small",
                     front=anim("pump", hand(46, 134, -25)) + anim("pump late", hand(212, 124, 25, flip=True))),
    "03-question": dict(rot=-3, eyes="open", mouth="content",
                        top=question(286, 74)),
    "04-thinking": dict(rot=-2, eyes="open", brows="raised", mouth="content", mouth_dx=-2,
                        front=hand(158, 144, -30),
                        top=dots(268, 82)),
    "05-surprised": dict(rot=-4, eyes="wide", brows="up", mouth="o",
                         front=hand(82, 138, -12) + hand(186, 132, 12, flip=True),
                         top=lines(282, 82, 40)),
    "06-coffee": dict(rot=-2, eyes="happy", mouth="smile",
                      front=anim("bob", place(mug, 148, 162, 0, 1.3) + hand(118, 180, 15, flip=True) + hand(180, 178, -15))),
    "07-laptop": dict(rot=-2, eyes="open", mouth="smile",
                      front=place(laptop, 144, 206, -4, 1.05) + anim("tap", hand(94, 200, 20, flip=True)) + anim("tap late", hand(194, 194, -20)),
                      top=lines(282, 96, 45, 0.85)),
    "08-map": dict(rot=-3, eyes="open", mouth="o",
                   front=anim("tilt", place(map_, 146, 184, -6, 1.3) + hand(98, 186, 15, flip=True) + hand(194, 180, -15))),
    "09-binoculars": dict(rot=-2, eyes=None, brows="up", mouth="smile",
                          front=anim("scan", place(binoculars, EYE_L[0] + EYE_DX, EYE_L[1], 0, 1.0)
                                + hand(EYE_L[0] - 16, EYE_L[1] + 18, 25, flip=True) + hand(EYE_R[0] + 16, EYE_R[1] + 18, -25))),
    "10-thumbsup": dict(rot=-2, eyes="open", mouth="smile",
                        front=anim("pump", hand(218, 126, 0, shape="thumb")),
                        top=sparkle(292, 74)),
    "11-sleep": dict(rot=-14, dy=4, bob="slow", eyes="sleep", mouth="content",
                     front=hand(216, 146, 10),
                     top=zzz(268, 86)),
    "12-tired": dict(rot=-3, eyes="soft", brows="worried", mouth="wavy",
                     face_extra=drop(FACE_C[0] + 50, FACE_C[1] - 28, 0.8),
                     front=hand(104, 188, 0, flip=True) + hand(176, 184, 0)),
    "13-cool": dict(rot=-3, eyes=None, mouth="smile", glasses=True,
                    front=anim("wave", hand(220, 132, 12)),
                    top=sparkle(290, 96)),
    "14-excited": dict(rot=-5, dx=-2, bob="bouncy", eyes="happy", mouth="big",
                       back=arm("M18,128 C0,122 -14,108 -18,94") + arm("M214,118 C232,110 240,98 242,86"),
                       front=anim("pump", hand(-18, 82, -20)) + anim("pump late", hand(242, 74, 20, flip=True)),
                       top=lines(52, 64, -35)),
    "15-flag": dict(rot=-2, dx=-32, eyes="open", mouth="open",
                    front=place(flag, 232, 86, 0, 1.1) + hand(231, 150, 0)),
}

CELL = 340
SCALE = 0.95


def mascot(p, phase=0.0):
    face = FACE + (blush() if p.get("blush", True) else "") + eyes(p.get("eyes"))
    face += brows(p.get("brows")) + mouth(p.get("mouth"), p.get("mouth_dx", 0))
    if p.get("glasses"):
        face += sunglasses()
    face += p.get("face_extra", "")
    body = f'<path d="{BODY}" fill="{RED}"/>' + SHINE + f'<path d="{BODY}" fill="none" {LINE}/>'
    face = f'<g transform="rotate({p.get("tilt", -4)},{FACE_C[0]},{FACE_C[1]})">{face}</g>'
    inner = (FEET + p.get("back", "") + anim("sway", SCARF_TAIL) + body + face
             + SCARF_BAND + p.get("front", ""))
    g = (f'<g transform="translate({CELL / 2 + p.get("dx", 0)},{CELL / 2 + 8 + p.get("dy", 0)}) '
         f'rotate({p.get("rot", 0)}) scale({SCALE}) translate(-108,-104)">{inner}</g>')
    bob = f'bob {p["bob"]}' if "bob" in p else "bob"
    return f'<g style="--d:{-phase:.2f}s">{anim(bob, g)}{p.get("top", "")}</g>'


def svg(content, w=CELL, h=CELL, box=None):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{box or f"0 0 {w} {h}"}" width="{w}" height="{h}">'
            f'{STYLE}{content}</svg>\n')


def avatar():
    """Small-size Pépite: no tails, hands or extras, upright, bolder outline, cropped to the body."""
    face = FACE + blush() + eyes("open") + mouth("smile")
    face = f'<g transform="rotate(-4,{FACE_C[0]},{FACE_C[1]})">{face}</g>'
    return svg(anim("bob", f'<path d="{BODY}" fill="{RED}" {st(9)}/>' + SHINE + face + SCARF_BAND), 240, 212, "-14 -14 260 220")


def build():
    OUT.mkdir(exist_ok=True)
    cells = []
    for i, (name, p) in enumerate(POSES.items()):
        (OUT / f"{name}.svg").write_text(svg(mascot(p)))
        g = mascot(p, phase=i * 0.37)
        cells.append(f'<g transform="translate({(i % 5) * CELL},{(i // 5) * CELL})">{g}</g>')
    (OUT.parent / "sheet.svg").write_text(svg("".join(cells), CELL * 5, CELL * 3))
    (OUT.parent / "avatar.svg").write_text(avatar())


if __name__ == "__main__":
    build()
