"""Floor 12: the Installation Lab and the XR Lab, as five platformer levels.

Run-and-jump platforming (coins, item crates you hit from below, bots you stomp, springs) and portal
puzzles (a portal device, white panels that take portals, momentum through portals, cubes, buttons,
doors, light bridges, a fizzler). Everything lives in this file; the engine is untouched.

Controls, on top of the engine's (arrows / WASD to move, SPACE to jump, UP to search):
    Mouse        aim the portal device
    Left click   blue portal      (or E)
    Right click  orange portal    (or Q)
    F or DOWN    grab / drop a cube, press a switch

Levels, west to east:   1 Freight Hall  ->  2 Installation Lab  ->  3 Fabrication Bay
                        ->  4 XR Tracking Floor  ->  5 XR Holo Stage (the code digit)
Coming in from the east (floor 12 is reached by the East elevator), doors and bridges you arrive
behind are already open, so each level can be crossed from either side. The digit's own puzzle
(cube on the button turns off the laser grid) has to be solved from whichever side you come in.
"""
import math

import pygame

from engine import config as C
from engine.kit import FilingCabinet, Locker, Plant, Plinth, Printer3D, ServerRack, Sign, Window, Easel, CeilingLight
from engine.player import Player
from engine.room import Furniture, Lift, Platform, Room

NAME = "Installation Lab + XR Lab"
AUTHOR = "Jerry Xu"

PW, PH = Player.W, Player.H

# What you carry from level to level (kept across rooms; the engine rebuilds a room every time you enter it).
RUN = {"coins": 0, "taken": set(), "device": False, "boots": False, "helmet": False, "star": 0.0,
       "helmet_at": 20}

BLUE = (70, 160, 255)
ORANGE = (255, 150, 40)
PANEL = (226, 230, 236)
CONCRETE = (58, 60, 70)
GOO = (120, 200, 60)
HARD_LIGHT = (130, 210, 255)

_FONTS = {}


def _font(size):
    if size not in _FONTS:
        pygame.font.init()
        _FONTS[size] = pygame.font.Font(None, size)
    return _FONTS[size]


# --- input the engine doesn't hand to rooms: the mouse and a few extra keys ---------------------------

_FAKE = None    # tests set this to {"pressed": {...}, "aim": (x, y)} to drive the floor without a keyboard


class _Input:
    KEYS = {"blue": ("K_e",), "orange": ("K_q",), "use": ("K_f", "K_DOWN", "K_s")}

    def __init__(self):
        self.was = set()

    def poll(self):
        """Returns (actions pressed this frame, mouse position or None)."""
        if _FAKE is not None:
            return set(_FAKE.get("pressed", ())), _FAKE.get("aim")
        held, aim = set(), None
        try:
            k = pygame.key.get_pressed()
            for name, codes in self.KEYS.items():
                if any(k[getattr(pygame, c)] for c in codes):
                    held.add(name)
            b = pygame.mouse.get_pressed()
            if b[0]:
                held.add("blue")
            if b[2]:
                held.add("orange")
            if pygame.display.get_surface() is not None and pygame.mouse.get_focused():
                aim = pygame.mouse.get_pos()
        except pygame.error:
            pass
        pressed = held - self.was
        self.was = held
        return pressed, aim


INPUT = _Input()


def _overlap_x(a, b):
    return min(a.right, b.right) - max(a.left, b.left)


def _ray_hit(ox, oy, dx, dy, r):
    """Where a ray from (ox, oy) along (dx, dy) first enters rect r: (t, face) or None.
    face is the side it hits, named by the way that side faces: 'left', 'right', 'up', 'down'."""
    tmin, tmax, face = -1e9, 1e9, None
    for o, d, lo, hi, axis in ((ox, dx, r.left, r.right, "x"), (oy, dy, r.top, r.bottom, "y")):
        if abs(d) < 1e-9:
            if o < lo or o > hi:
                return None
            continue
        t1, t2 = (lo - o) / d, (hi - o) / d
        if t1 > t2:
            t1, t2 = t2, t1
        if t1 > tmin:
            tmin = t1
            face = ("left" if d > 0 else "right") if axis == "x" else ("up" if d > 0 else "down")
        tmax = min(tmax, t2)
        if tmin > tmax:
            return None
    if tmin < 0 or face is None:
        return None
    return tmin, face


# --- the level pieces ----------------------------------------------------------------------------------

class Wall:
    """A solid block: you can't walk or jump through it, and you can stand on its top.
    panels: faces that take portals, as (face, start, end) with face 'left' / 'right' / 'up' / 'down'."""

    def __init__(self, x, y, w, h, panels=()):
        self.rect = pygame.Rect(x, y, w, h)
        self.panels = [Panel(self, *p) for p in panels]

    @property
    def solid(self):
        return True

    def draw(self, surf):
        r = self.rect
        pygame.draw.rect(surf, CONCRETE, r)
        for y in range(r.top + 24, r.bottom, 24):
            pygame.draw.line(surf, (50, 52, 60), (r.left, y), (r.right - 1, y), 1)
        pygame.draw.rect(surf, C.INK, r, 2)


class Door(Wall):
    """A wall that slides up out of the way while its signal is on."""

    def __init__(self, x, y, w, h, link):
        super().__init__(x, y, w, h)
        self.link = link
        self.open = 0.0      # 0 shut .. 1 fully open
        self.want = False

    @property
    def solid(self):
        return self.open < 0.8

    def step(self, dt, on):
        self.want = on
        self.open = max(0.0, min(1.0, self.open + (dt * 2.5 if on else -dt * 2.5)))

    def draw(self, surf):
        r = self.rect
        pygame.draw.rect(surf, (40, 42, 50), r, 2)
        h = int(r.height * (1 - self.open))
        if h > 0:
            body = pygame.Rect(r.left, r.top, r.width, h)
            pygame.draw.rect(surf, (96, 100, 116), body)
            pygame.draw.rect(surf, C.INK, body, 2)
            lamp = (90, 220, 120) if self.want else C.DANGER
            pygame.draw.circle(surf, lamp, (r.centerx, body.bottom - 16), 5)


class Panel:
    """A white strip on one face of a wall (or on the floor) that takes portals."""

    def __init__(self, wall, face, start, end):
        self.wall, self.face = wall, face
        r = wall.rect
        if face == "left":
            self.rect = pygame.Rect(r.left - 4, start, 4, end - start)
        elif face == "right":
            self.rect = pygame.Rect(r.right, start, 4, end - start)
        elif face == "up":
            self.rect = pygame.Rect(start, r.top - 4, end - start, 4)
        else:
            self.rect = pygame.Rect(start, r.bottom, end - start, 4)
        self.vertical = face in ("left", "right")

    def draw(self, surf):
        pygame.draw.rect(surf, PANEL, self.rect)


class FloorPanel(Panel):
    """A portal panel set into the ground."""

    def __init__(self, x0, x1):
        self.wall, self.face, self.vertical = None, "up", False
        self.rect = pygame.Rect(x0, C.FLOOR_Y - 4, x1 - x0, 4)


class Portal:
    HALF_WALL, HALF_FLOOR = 32, 30

    def __init__(self, color, panel, along):
        self.color, self.panel, self.normal = color, panel, panel.face
        half = self.HALF_WALL if panel.vertical else self.HALF_FLOOR
        r = panel.rect
        lo, hi = (r.top, r.bottom) if panel.vertical else (r.left, r.right)
        self.c = max(lo + half, min(hi - half, along))
        self.lo, self.hi = self.c - half, self.c + half
        self.face_at = {"left": r.left, "right": r.right, "up": r.top, "down": r.bottom}[self.normal]
        self.t = 0.0

    def entering(self, p, room):
        """Is the player going in? Returns their speed if so, else None."""
        r = p.rect
        moving = p.vx + room.fling
        n, f = self.normal, self.face_at
        if n == "up":
            if self.lo <= r.centerx <= self.hi and f - 3 <= r.bottom <= f + 24 and (p.on is not None or p.vy >= 0):
                return max(room.last_vy, p.vy, 0.0)
        elif n == "down":
            if self.lo <= r.centerx <= self.hi and f - 24 <= r.top <= f + 3 and p.vy < 0:
                return -p.vy
        elif n == "right":
            if self.lo <= r.centery <= self.hi and f - 24 <= r.left <= f + 3 and moving < 0:
                return -moving
        elif n == "left":
            if self.lo <= r.centery <= self.hi and f - 3 <= r.right <= f + 24 and moving > 0:
                return moving
        return None

    def draw(self, surf):
        self.t += 1 / 60
        glow = 2 + int(2 * math.sin(self.t * 6))
        if self.panel.vertical:
            box = pygame.Rect(0, 0, 18, self.hi - self.lo)
            box.center = (self.face_at, int(self.c))
        else:
            box = pygame.Rect(0, 0, self.hi - self.lo, 14)
            box.center = (int(self.c), self.face_at)
        pygame.draw.ellipse(surf, (20, 20, 26), box)
        pygame.draw.ellipse(surf, self.color, box, 3 + glow // 2)


class Coin:
    R = 8

    def __init__(self, key, x, y):
        self.key, self.x, self.y = key, x, y
        self.rect = pygame.Rect(x - self.R, y - self.R, 2 * self.R, 2 * self.R)

    def draw(self, surf, t):
        w = max(2, int(self.R * 2 * abs(math.cos(t * 3 + self.x * 0.05))))
        box = pygame.Rect(0, 0, w, self.R * 2)
        box.center = (self.x, self.y)
        pygame.draw.ellipse(surf, C.PIECE, box)
        pygame.draw.ellipse(surf, (160, 110, 20), box, 2)


class Crate(Platform):
    """A floating supply crate: stand on it, or jump into it from below to knock out what's inside."""

    S = 40
    ICON = {"coin": C.PIECE, "boots": (90, 200, 255), "helmet": (240, 200, 60), "star": (255, 120, 220)}

    def __init__(self, key, x, top, contents):
        super().__init__(x, top, self.S)
        self.rect = pygame.Rect(int(x), int(top), self.S, self.S)
        self.key, self.contents = key, contents
        self.used = key in RUN["taken"]
        self.bounce = 0.0

    def draw(self, surf):
        r = self.rect.move(0, -int(6 * math.sin(self.bounce * math.pi)) if self.bounce > 0 else 0)
        if self.used:
            pygame.draw.rect(surf, (110, 100, 90), r, border_radius=4)
        else:
            pygame.draw.rect(surf, (210, 150, 60), r, border_radius=4)
            pygame.draw.rect(surf, (250, 220, 140), r.inflate(-14, -14), 2, border_radius=3)
            pygame.draw.circle(surf, self.ICON[self.contents], r.center, 6)
        pygame.draw.rect(surf, C.INK, r, 2, border_radius=4)


class Spring(Platform):
    """A bounce pad. Land on it and it throws you high."""

    V = 950.0

    def __init__(self, x, width=56):
        super().__init__(x, C.FLOOR_Y - 10, width)
        self.squash = 0.0

    def draw(self, surf):
        r = self.rect
        h = 10 - int(6 * self.squash)
        base = pygame.Rect(r.left + 6, C.FLOOR_Y - 4, r.width - 12, 4)
        pygame.draw.rect(surf, (70, 70, 80), base)
        top = pygame.Rect(r.left, C.FLOOR_Y - 4 - h, r.width, 6)
        for i in range(3):
            y = top.bottom + i * 2
            pygame.draw.line(surf, (200, 200, 210), (r.left + 10, y), (r.right - 10, y), 1)
        pygame.draw.rect(surf, (230, 80, 80), top, border_radius=3)


class LightBridge(Platform):
    """A bridge of hard light: it's only there while its signal is on."""

    def draw(self, surf):
        r = self.rect
        pygame.draw.rect(surf, HARD_LIGHT, (r.left, r.top, r.width, 6))
        pygame.draw.line(surf, (230, 250, 255), (r.left, r.top + 1), (r.right, r.top + 1), 2)


class Cube:
    S = 26

    def __init__(self, home):
        self.home = home
        self.respawn()

    def respawn(self):
        self.x, self.y = float(self.home[0]), float(self.home[1] - self.S - 120)
        self.vy, self.carried = 0.0, False

    @property
    def rect(self):
        return pygame.Rect(int(self.x), int(self.y), self.S, self.S)

    def fall(self, dt, room):
        prev = self.y + self.S
        self.vy = min(C.MAX_FALL, self.vy + C.GRAVITY * dt)
        self.y += self.vy * dt
        bottom, best = self.y + self.S, None
        for s in room.surfaces():
            r = s.rect
            if self.x + self.S > r.left and self.x < r.right and prev <= r.top + 1 and bottom >= r.top:
                best = r.top if best is None else min(best, r.top)
        if best is not None:
            self.y, self.vy = float(best - self.S), 0.0
        if self.y > C.H:
            self.respawn()

    def draw(self, surf):
        r = self.rect
        pygame.draw.rect(surf, (170, 176, 190), r, border_radius=4)
        pygame.draw.rect(surf, C.INK, r, 2, border_radius=4)
        pygame.draw.circle(surf, (255, 140, 190), r.center, 6)
        pygame.draw.circle(surf, C.INK, r.center, 6, 1)


class Dispenser:
    """The tube a cube drops out of."""

    def __init__(self, x):
        self.x = x

    def draw(self, surf):
        r = pygame.Rect(self.x - 6, 36, Cube.S + 12, 40)
        pygame.draw.rect(surf, (90, 94, 108), r, border_radius=4)
        pygame.draw.rect(surf, C.INK, r, 2, border_radius=4)
        pygame.draw.rect(surf, (30, 30, 36), (r.left + 6, r.bottom - 6, r.width - 12, 6))


class Button:
    """A floor button. Weighed down by a cube (or you standing on it). latch=True stays on once pressed."""

    def __init__(self, x, y, link, latch=False):
        self.y, self.link, self.latch = y, link, latch
        self.rect = pygame.Rect(x, y - 8, 64, 8)
        self.down = self.latched = False

    def step(self, room, p):
        weight = any(not c.carried and abs(c.rect.bottom - self.y) <= 2 and _overlap_x(c.rect, self.rect) >= 8
                     for c in room.cubes)
        if p.on is not None and abs(p.rect.bottom - self.y) <= 2 and _overlap_x(p.rect, self.rect) >= 6:
            weight = True
        if self.latch and weight:
            self.latched = True
        self.down = weight or self.latched

    def draw(self, surf):
        r = self.rect
        pygame.draw.rect(surf, (60, 60, 70), (r.left - 4, self.y - 4, r.width + 8, 4))
        cap = pygame.Rect(r.left + 6, self.y - (4 if self.down else 10), r.width - 12, 6)
        pygame.draw.rect(surf, (90, 220, 120) if self.down else C.DANGER, cap, border_radius=3)
        pygame.draw.rect(surf, C.INK, cap, 1, border_radius=3)


class Switch:
    """A pedestal switch: press F next to it and its signal stays on for `seconds`, ticking down."""

    def __init__(self, x, link, seconds):
        self.x, self.link, self.seconds = x, link, seconds
        self.rect = pygame.Rect(x, C.FLOOR_Y - 56, 20, 56)
        self.left = 0.0

    def draw(self, surf):
        r = self.rect
        pygame.draw.rect(surf, (80, 84, 96), (r.left + 6, r.top + 12, 8, r.height - 12))
        pygame.draw.rect(surf, (60, 62, 72), (r.left - 6, C.FLOOR_Y - 6, r.width + 12, 6))
        on = self.left > 0
        pygame.draw.circle(surf, (90, 220, 120) if on else (240, 80, 80), (r.centerx, r.top + 8), 9)
        pygame.draw.circle(surf, C.INK, (r.centerx, r.top + 8), 9, 2)
        if on:
            frac = self.left / self.seconds
            ring = pygame.Rect(r.centerx - 16, r.top - 8, 32, 32)
            pygame.draw.arc(surf, (230, 250, 255), ring, math.pi / 2, math.pi / 2 + 2 * math.pi * frac, 3)


class DevicePedestal:
    """Where the portal device sits until you walk into it."""

    def __init__(self, x):
        self.rect = pygame.Rect(x, C.FLOOR_Y - 60, 40, 60)

    def draw(self, surf, t):
        r = self.rect
        pygame.draw.rect(surf, (200, 204, 214), (r.left + 4, r.top + 30, r.width - 8, 30), border_radius=4)
        pygame.draw.rect(surf, C.INK, (r.left + 4, r.top + 30, r.width - 8, 30), 2, border_radius=4)
        y = r.top + 12 + int(4 * math.sin(t * 3))
        pygame.draw.rect(surf, (240, 240, 245), (r.left + 6, y, 28, 12), border_radius=5)
        pygame.draw.circle(surf, BLUE, (r.left + 12, y + 6), 4)
        pygame.draw.circle(surf, ORANGE, (r.left + 28, y + 6), 4)


class Fizzler:
    """A shimmering field. Walk through it and your portals close; a cube you're carrying dissolves."""

    def __init__(self, x):
        self.rect = pygame.Rect(x, 40, 10, C.FLOOR_Y - 40)

    def draw(self, surf, t):
        r = self.rect
        pygame.draw.rect(surf, (60, 64, 80), (r.left - 3, r.top, 3, r.height))
        pygame.draw.rect(surf, (60, 64, 80), (r.right, r.top, 3, r.height))
        for i in range(0, r.height, 18):
            y = r.top + (i + int(t * 60)) % r.height
            pygame.draw.line(surf, (140, 200, 255), (r.left, y), (r.right, y + 6), 1)


# --- hazards (each has .rect, .update(dt, room, player), .draw(surf); an empty rect can't hurt) -----

NO_RECT = pygame.Rect(0, 0, 0, 0)


def _shield(p):
    """Something is about to hit the player. A helmet takes the hit instead. True if they're safe."""
    if p.safe > 0:
        return True
    if RUN["helmet"]:
        RUN["helmet"] = False
        p.safe = 1.5
        return True
    return False


class StompBot:
    """A little security bot that rolls back and forth. Touch its side and you're caught; land on it and
    it's done for."""

    W, H = 34, 30

    def __init__(self, x, y, left, right, speed=70.0):
        self.x, self.y_surface, self.left, self.right, self.speed = float(x), y, left, right, speed
        self.dir = 1
        self.box = pygame.Rect(int(x), y - self.H, self.W, self.H)
        self.rect = self.box.copy()
        self.was_above = False
        self.dead = 0.0      # > 0 while it's squashed
        self.t = 0.0

    def update(self, dt, room, player):
        self.t += dt
        if self.dead:
            self.dead += dt
            self.rect = NO_RECT
            return
        self.x += self.dir * self.speed * dt
        if self.x < self.left:
            self.x, self.dir = float(self.left), 1
        elif self.x + self.W > self.right:
            self.x, self.dir = float(self.right - self.W), -1
        self.box.x = int(self.x)
        r = player.rect
        touching = r.colliderect(self.box)
        if touching and (RUN["star"] > 0 or (self.was_above and player.vy > 0)):
            self.dead = 0.01
            self.rect = NO_RECT
            if RUN["star"] <= 0:
                player.vy = -430.0          # bounce off it
                player.on = None
                room.launched = True
            room.add_coins(1, "Bot stomped")
            return
        above = r.bottom <= self.box.top + 6 and _overlap_x(r, self.box) > -20
        self.was_above = above
        self.rect = NO_RECT if above else self.box
        if touching and not above:
            _shield(player)

    def draw(self, surf):
        if self.dead:
            if self.dead < 0.6:
                flat = pygame.Rect(self.box.left, self.box.bottom - 8, self.W, 8)
                pygame.draw.rect(surf, (60, 64, 72), flat, border_radius=3)
            return
        r = self.box
        pygame.draw.rect(surf, (70, 74, 86), r, border_radius=10)
        pygame.draw.rect(surf, C.INK, r, 2, border_radius=10)
        pygame.draw.circle(surf, (120, 220, 255), (r.centerx + self.dir * 7, r.top + 11), 5)
        pygame.draw.line(surf, C.INK, (r.centerx, r.top), (r.centerx - self.dir * 6, r.top - 9), 2)
        pygame.draw.circle(surf, C.DANGER, (r.centerx - self.dir * 6, r.top - 10), 3)
        wob = int(2 * math.sin(self.t * 14))
        pygame.draw.circle(surf, C.INK, (r.left + 7, r.bottom), 4 + (wob > 0))
        pygame.draw.circle(surf, C.INK, (r.right - 7, r.bottom), 4 + (wob <= 0))


class Turret:
    """A sentry on the floor. It sees along its eye line; when it sees you it charges, then fires.
    It can't see over a light bridge. Land on it to knock it over."""

    W, H = 30, 44
    RANGE = 640

    def __init__(self, x, y, facing=-1):
        self.dir = facing           # (a .dir also tells the check this hazard isn't parked in a doorway)
        self.box = pygame.Rect(x, y - self.H, self.W, self.H)
        self.eye = self.box.top + 14
        self.state, self.t = "idle", 0.0
        self.rect = NO_RECT
        self.beam = None
        self.was_above = False
        self.down = 0.0             # > 0 once knocked over

    def _sight_end(self, room):
        """Where its eye line starts and stops: at its range, or at the first wall or cube in the way."""
        x0 = self.box.left if self.dir < 0 else self.box.right
        end = x0 + self.dir * self.RANGE
        probe = pygame.Rect(min(x0, end), self.eye - 2, self.RANGE, 4)
        for b in [w.rect for w in room.walls if w.solid] + [c.rect for c in room.cubes]:
            if probe.colliderect(b):
                end = max(end, b.right) if self.dir < 0 else min(end, b.left)
        return x0, end, pygame.Rect(min(x0, end), self.eye - 2, abs(end - x0), 4)

    def update(self, dt, room, player):
        r = player.rect
        if self.down:
            self.down += dt
            self.rect = NO_RECT
            return
        touching = r.colliderect(self.box)
        if touching and (RUN["star"] > 0 or (self.was_above and player.vy > 0)):
            self.down = 0.01
            self.rect = NO_RECT
            if RUN["star"] <= 0:
                player.vy, player.on = -400.0, None
                room.launched = True
            room.add_coins(2, "Turret knocked over")
            return
        self.was_above = r.bottom <= self.box.top + 6
        x0, end, line = self._sight_end(room)
        sees = line.colliderect(r)
        self.t += dt
        if self.state == "idle":
            self.rect = NO_RECT
            if sees:
                self.state, self.t = "charge", 0.0
        elif self.state == "charge":
            if self.t > 0.6:
                self.state, self.t = "fire", 0.0
        elif self.state == "fire":
            self.beam = pygame.Rect(min(x0, end), self.eye - 3, abs(end - x0), 6)
            self.rect = self.beam
            if self.beam.colliderect(r):
                _shield(player)
            if self.t > 0.25:
                self.state, self.t, self.rect = "cool", 0.0, NO_RECT
        elif self.state == "cool":
            self.rect = NO_RECT
            if self.t > 0.6:
                self.state = "idle"
        self.sight = (x0, end)

    def draw(self, surf):
        r = self.box
        if self.down:
            pygame.draw.ellipse(surf, (220, 222, 228), (r.left - 8, r.bottom - 16, r.width + 16, 16))
            pygame.draw.ellipse(surf, C.INK, (r.left - 8, r.bottom - 16, r.width + 16, 16), 2)
            return
        pygame.draw.line(surf, C.INK, (r.left + 4, r.bottom), (r.left - 4, r.bottom + 0), 3)
        pygame.draw.ellipse(surf, (230, 232, 238), r)
        pygame.draw.ellipse(surf, C.INK, r, 2)
        eye_x = r.centerx + self.dir * 6
        pygame.draw.circle(surf, C.DANGER, (eye_x, self.eye), 4)
        if self.state in ("charge", "fire") and hasattr(self, "sight"):
            x0, end = self.sight
            width = 1 if self.state == "charge" else 5
            color = (255, 90, 90) if self.state == "charge" else (255, 60, 60)
            pygame.draw.line(surf, color, (x0, self.eye), (end, self.eye), width)


class Goo:
    """A pool of something you really shouldn't step in."""

    def __init__(self, x, w):
        self.rect = pygame.Rect(x, C.FLOOR_Y - 12, w, 12)
        self.t = 0.0

    def update(self, dt, room, player):
        self.t += dt

    def draw(self, surf):
        r = self.rect
        pygame.draw.rect(surf, (40, 80, 30), (r.left, r.top, r.width, C.H - r.top))
        pygame.draw.rect(surf, GOO, r)
        for i in range(r.left + 10, r.right - 6, 26):
            y = r.top + 3 + int(2 * math.sin(self.t * 4 + i))
            pygame.draw.circle(surf, (170, 240, 110), (i, y), 3)


class LaserGrid:
    """A wall of laser that switches off while its signal is on."""

    def __init__(self, x, y_top, y_bottom, link):
        self.box = pygame.Rect(x, y_top, 8, y_bottom - y_top)
        self.link = link
        self.rect = self.box
        self.t = 0.0

    def update(self, dt, room, player):
        self.t += dt
        self.rect = NO_RECT if room.sig.get(self.link) else self.box

    def draw(self, surf):
        b = self.box
        pygame.draw.rect(surf, (60, 62, 72), (b.left - 4, b.top - 8, 16, 8))
        pygame.draw.rect(surf, (60, 62, 72), (b.left - 4, b.bottom, 16, 8))
        if self.rect is NO_RECT:
            return
        for k in range(3):
            x = b.left + 1 + k * 3
            a = 160 + int(90 * math.sin(self.t * 20 + k))
            pygame.draw.line(surf, (255, a // 3, a // 3), (x, b.top), (x, b.bottom), 1)


# --- furniture with its own look ---------------------------------------------------------------------

class Projector(Furniture):
    """A projector on a cart, throwing a cone of light up the wall."""

    def __init__(self, x, y, name="projector cart", holds_piece=False):
        super().__init__(x, y, 60, 56, name, holds_piece)
        self.cone = pygame.Surface((200, 220), pygame.SRCALPHA)     # made once, not every frame
        pygame.draw.polygon(self.cone, (160, 220, 255, 40), [(100, 220), (0, 0), (200, 0)])

    def draw(self, surf):
        r = self.rect
        if not self.searched:
            surf.blit(self.cone, (r.centerx - 100, r.top - 220))
        pygame.draw.rect(surf, (70, 74, 90), (r.left + 6, r.top + 22, r.width - 12, r.height - 22))
        pygame.draw.rect(surf, (40, 42, 52) if not self.searched else (90, 90, 96), (r.left, r.top, r.width, 22),
                         border_radius=4)
        pygame.draw.circle(surf, (190, 230, 255), (r.centerx, r.top + 11), 7)
        pygame.draw.rect(surf, C.INK, r, 2, border_radius=4)


class VRStation(Furniture):
    """A desk with a headset on a stand; the headset's lights pulse."""

    def __init__(self, x, y, name="VR station", holds_piece=False):
        super().__init__(x, y, 100, 64, name, holds_piece)

    def draw(self, surf):
        r = self.rect
        top = (120, 100, 140) if not self.searched else (100, 96, 104)
        pygame.draw.rect(surf, top, (r.left, r.top + 30, r.width, 10))
        pygame.draw.rect(surf, (60, 56, 70), (r.left + 8, r.top + 40, 8, r.height - 40))
        pygame.draw.rect(surf, (60, 56, 70), (r.right - 16, r.top + 40, 8, r.height - 40))
        pygame.draw.line(surf, C.INK, (r.centerx, r.top + 30), (r.centerx, r.top + 14), 3)
        glow = 150 + int(100 * (0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 300.0)))
        pygame.draw.rect(surf, (30, 30, 36), (r.centerx - 22, r.top, 44, 16), border_radius=6)
        pygame.draw.circle(surf, (glow, 80, 220), (r.centerx - 10, r.top + 8), 4)
        pygame.draw.circle(surf, (glow, 80, 220), (r.centerx + 10, r.top + 8), 4)


class _WorldLayer:
    """Decor hook: draws the room's level pieces on top of its background, under platforms and the player."""

    def __init__(self, room):
        self.room = room

    def draw(self, surf):
        self.room.draw_world(surf)


# --- the level room --------------------------------------------------------------------------------

class Level(Room):
    """A room with platformer and portal pieces. Subclasses fill in layout()."""

    number = 0
    palette = ((70, 74, 88), (78, 82, 96))
    needs_device = False
    spare_device = (110, 840)     # where a spare device appears if you arrive without one: (from west, from east)

    def build(self):
        self.walls, self.doors, self.coins, self.crates = [], [], [], []
        self.cubes, self.buttons, self.switches, self.bridges = [], [], [], []
        self.springs, self.fizzlers, self.panels, self.dispensers = [], [], [], []
        self.portals = {"blue": None, "orange": None}
        self.pedestal = None
        self.hints = []
        self.sig = {}
        self.fling = 0.0
        self.last_vy = self.last_top = self.last_cx = 0.0
        self.launched = False
        self.last_on = False
        self.portal_cool = 0.0
        self.first = True
        self.from_east = False
        self.msg, self.msg_t = "", 0.0
        self.shot = None             # (start, end, color, seconds) of the last portal shot, for drawing
        self.aim = None
        self.player = None
        self.t = 0.0
        self.layout()
        for w in self.walls:
            self.panels += w.panels
            if 40 <= w.rect.top < C.FLOOR_Y and not isinstance(w, Door):
                self.platforms.append(_WallTop(w))
        self.decor.insert(0, _WorldLayer(self))

    def layout(self):
        raise NotImplementedError

    # helpers for layout()
    def coin_row(self, x0, y, n, gap=30):
        for i in range(n):
            key = f"{type(self).__name__}:coin:{x0 + i * gap},{y}"
            if key not in RUN["taken"]:
                self.coins.append(Coin(key, x0 + i * gap, y))

    def coin_arc(self, x0, x1, y_base, height, n):
        for i in range(n):
            f = i / (n - 1)
            x = int(x0 + (x1 - x0) * f)
            y = int(y_base - height * 4 * f * (1 - f))
            key = f"{type(self).__name__}:coin:{x},{y}"
            if key not in RUN["taken"]:
                self.coins.append(Coin(key, x, y))

    def crate(self, x, top, contents):
        c = Crate(f"{type(self).__name__}:crate:{x},{top}", x, top, contents)
        self.crates.append(c)
        self.platforms.append(c)

    def hint(self, x, y, text):
        self.hints.append((_font(20).render(text, True, (220, 224, 232)), (x, y)))

    def say(self, text, seconds=1.6):
        self.msg, self.msg_t = text, seconds

    def add_coins(self, n, why=None):
        RUN["coins"] += n
        if RUN["coins"] >= RUN["helmet_at"]:
            RUN["helmet_at"] += 20
            if not RUN["helmet"]:
                RUN["helmet"] = True
                self.say("20 coins: a helmet! It takes one hit for you", 2.2)
                return
        if why:
            self.say(f"{why}  +{n}", 1.0)

    # --- every frame --------------------------------------------------------------------------------
    def update(self, dt, p):
        if p is None:
            return
        self.player, self.t = p, self.t + dt
        self.msg_t = max(0.0, self.msg_t - dt)
        if self.first:
            self.first = False
            self.from_east = p.x > C.W / 2
            if self.needs_device and not RUN["device"]:
                self.pedestal = DevicePedestal(self.spare_device[1 if self.from_east else 0])
        pressed, aim = INPUT.poll()
        self.aim = aim

        # power-ups
        if RUN["star"] > 0:
            RUN["star"] = max(0.0, RUN["star"] - dt)
            p.safe = max(p.safe, 0.05)
        jumped = (not self.launched and self.last_on and p.on is None and p.vy < -400)
        if jumped and RUN["boots"]:
            p.vy = -C.JUMP_SPEED * 1.3 + C.GRAVITY * dt
        self.launched = False
        for s in self.springs:
            s.squash = max(0.0, s.squash - dt * 4)
            if p.on is s:
                p.vy = -Spring.V * (1.12 if RUN["boots"] else 1.0)
                p.on, p.y = None, p.y - 1
                s.squash = 1.0
                self.launched = True

        # momentum from a portal keeps carrying you until you land
        if p.on is not None:
            self.fling = 0.0
        elif self.fling:
            p.x += self.fling * dt

        self.signals(dt)
        self.portal_step(dt, p, pressed, aim)
        self.collide(p)
        self.cube_step(dt, p, pressed)
        self.pickups(p)
        for c in self.crates:
            c.bounce = max(0.0, c.bounce - dt * 4)
        for f in self.fizzlers:
            if f.rect.colliderect(p.rect):
                if self.portals["blue"] or self.portals["orange"]:
                    self.say("The field closed your portals", 1.2)
                self.portals = {"blue": None, "orange": None}
                for c in self.cubes:
                    if c.carried:
                        c.respawn()
                        self.say("The cube dissolved; a new one drops in", 1.6)

        self.last_vy, self.last_top, self.last_cx = p.vy, p.rect.top, p.rect.centerx
        self.last_on = p.on is not None

    def signals(self, dt):
        p = self.player
        for b in self.buttons:
            b.step(self, p)
        sig = {}
        for b in self.buttons:
            sig[b.link] = sig.get(b.link, False) or b.down
        for s in self.switches:
            s.left = max(0.0, s.left - dt)
            sig[s.link] = sig.get(s.link, False) or s.left > 0
        self.sig = sig
        for d in self.doors:
            d.step(dt, sig.get(d.link, False) or self.from_east)
        for br in self.bridges:
            on = sig.get(br.link, False) or self.from_east
            if on and br not in self.platforms:
                self.platforms.append(br)
            elif not on and br in self.platforms:
                self.platforms.remove(br)

    def solids(self):
        return [w.rect for w in self.walls if w.solid] + [c.rect for c in self.crates]

    def collide(self, p):
        """Walls and crates are solid from every side (the engine only knows one-way ledges)."""
        for s in self.solids():
            r = p.rect
            if not r.colliderect(s):
                continue
            if p.vy < 0 and self.last_top >= s.bottom - 2:         # head into it from below
                p.y, p.vy = float(s.bottom), 0.0
                for c in self.crates:
                    if c.rect == s:
                        self.bump(c)
                continue
            if r.bottom <= s.top + 6:                              # standing on it
                continue
            p.x = float(s.left - PW) if self.last_cx < s.centerx else float(s.right)
            self.fling = 0.0

    def bump(self, c):
        c.bounce = 1.0
        if c.used:
            return
        c.used = True
        RUN["taken"].add(c.key)
        if c.contents == "coin":
            self.add_coins(1, "Coin")
        elif c.contents == "boots":
            RUN["boots"] = True
            self.say("Jump boots! You jump higher now", 2.2)
        elif c.contents == "helmet":
            RUN["helmet"] = True
            self.say("Helmet! It takes one hit for you", 2.2)
        elif c.contents == "star":
            RUN["star"] = 8.0
            self.say("Invincible for 8 seconds! Run into things", 2.2)

    def pickups(self, p):
        r = p.rect
        for coin in list(self.coins):
            if r.colliderect(coin.rect):
                self.coins.remove(coin)
                RUN["taken"].add(coin.key)
                self.add_coins(1)
        if self.pedestal and r.colliderect(self.pedestal.rect):
            self.pedestal = None
            RUN["device"] = True
            self.say("Portal device! Aim with the mouse: left click blue, right click orange", 3.0)

    # --- portals ---------------------------------------------------------------------------------------
    def portal_step(self, dt, p, pressed, aim):
        if self.shot:
            self.shot = (*self.shot[:3], self.shot[3] - dt) if self.shot[3] > dt else None
        if RUN["device"]:
            for color in ("blue", "orange"):
                if color in pressed:
                    self.fire(p, color, aim)
        self.portal_cool = max(0.0, self.portal_cool - dt)
        a, b = self.portals["blue"], self.portals["orange"]
        if not (a and b) or self.portal_cool > 0:
            return
        for src, dst in ((a, b), (b, a)):
            speed = src.entering(p, self)
            if speed is not None:
                self.emerge(p, dst, speed)
                self.portal_cool = 0.3
                return

    def fire(self, p, color, aim):
        ox, oy = p.rect.centerx, p.rect.centery - 6
        if aim is None:
            aim = (ox + p.facing * 600, oy)
        dx, dy = aim[0] - ox, aim[1] - oy
        d = math.hypot(dx, dy)
        if d < 1:
            return
        dx, dy = dx / d, dy / d
        best = None                      # (t, panel or None, face)
        blockers = self.solids() + [pygame.Rect(0, C.FLOOR_Y, C.W, C.H - C.FLOOR_Y)]
        for panel in self.panels:
            hit = _ray_hit(ox, oy, dx, dy, panel.rect)
            if hit and hit[1] == panel.face and (best is None or hit[0] < best[0]):
                best = (hit[0], panel)
        for r in blockers:
            hit = _ray_hit(ox, oy, dx, dy, r)
            if hit and (best is None or hit[0] < best[0] - 0.5):
                best = (hit[0], None)
        t = best[0] if best else 1400
        end = (ox + dx * t, oy + dy * t)
        rgb = BLUE if color == "blue" else ORANGE
        self.shot = ((ox, oy), end, rgb, 0.12)
        if not best or best[1] is None:
            self.say("Portals only open on white panels", 1.0)
            return
        panel = best[1]
        along = end[1] if panel.vertical else end[0]
        new = Portal(rgb, panel, along)
        other = self.portals["orange" if color == "blue" else "blue"]
        if other and other.panel is panel and abs(other.c - new.c) < (new.hi - new.lo):
            self.say("Too close to the other portal", 1.0)
            return
        self.portals[color] = new

    def emerge(self, p, dst, speed):
        n = dst.normal
        if n == "up":
            p.x, p.y = dst.c - PW / 2, dst.face_at - PH - 1
            p.vy, self.fling = -max(speed, 420.0), 0.0
        elif n == "down":
            p.x, p.y = dst.c - PW / 2, dst.face_at + 1
            p.vy, self.fling = max(speed, 60.0), 0.0
        elif n == "right":
            p.x, p.y = dst.face_at + 1, dst.c - PH / 2
            p.vy, self.fling, p.facing = -120.0, max(speed, 330.0), 1
        else:
            p.x, p.y = dst.face_at - PW - 1, dst.c - PH / 2
            p.vy, self.fling, p.facing = -120.0, -max(speed, 330.0), -1
        p.on = None
        self.launched = True
        self.last_top = p.rect.top
        self.last_cx = p.rect.centerx

    # --- cubes -------------------------------------------------------------------------------------------
    def cube_step(self, dt, p, pressed):
        held = next((c for c in self.cubes if c.carried), None)
        if "use" in pressed:
            on_lift = p.on is not None and hasattr(p.on, "drive")
            if held:
                held.carried = False
                x = p.rect.centerx + p.facing * 20 - Cube.S / 2
                x = max(0, min(C.W - Cube.S, x))
                probe = pygame.Rect(int(x), int(p.rect.bottom - Cube.S), Cube.S, Cube.S)
                if probe.collidelist(self.solids()) >= 0:
                    x = p.rect.centerx - Cube.S / 2
                held.x, held.y, held.vy = float(x), float(p.rect.bottom - Cube.S), 0.0
                held = None
            elif not on_lift:
                near = p.rect.inflate(30, 20)
                cube = next((c for c in self.cubes if near.colliderect(c.rect)), None)
                switch = next((s for s in self.switches if near.colliderect(s.rect)), None)
                if cube:
                    cube.carried = True
                elif switch:
                    switch.left = switch.seconds
                    self.say(f"Bridge on: {switch.seconds} seconds!", 1.2)
        for c in self.cubes:
            if c.carried:
                c.x = p.rect.centerx + p.facing * 14 - Cube.S / 2
                c.y = p.rect.top + 8
                c.vy = 0.0
            else:
                c.fall(dt, self)
                for h in self.hazards:
                    if isinstance(h, Goo) and h.rect.colliderect(c.rect):
                        c.respawn()

    # --- drawing -----------------------------------------------------------------------------------------
    def draw_background(self, surf):
        wall, line = self.palette
        surf.fill(wall)
        for x in range(0, C.W, 80):
            pygame.draw.line(surf, line, (x, 0), (x, C.FLOOR_Y), 1)
        for y in range(40, C.FLOOR_Y, 80):
            pygame.draw.line(surf, line, (0, y), (C.W, y), 1)

    def draw_world(self, surf):
        t = self.t
        for img, pos in self.hints:
            surf.blit(img, pos)
        for d in self.dispensers:
            d.draw(surf)
        for w in self.walls:
            w.draw(surf)
        for pnl in self.panels:
            pnl.draw(surf)
        for f in self.fizzlers:
            f.draw(surf, t)
        for b in self.buttons:
            b.draw(surf)
        for s in self.switches:
            s.draw(surf)
        if self.pedestal:
            self.pedestal.draw(surf, t)
        for coin in self.coins:
            coin.draw(surf, t)
        for c in self.cubes:
            if not c.carried:
                c.draw(surf)
        for pt in self.portals.values():
            if pt:
                pt.draw(surf)

    def draw_foreground(self, surf):
        p = self.player
        if p is not None:
            r = p.rect
            for c in self.cubes:
                if c.carried:
                    c.draw(surf)
            if RUN["star"] > 0:
                hue = int(self.t * 12) % 3
                color = ((255, 120, 220), (255, 230, 90), (120, 230, 255))[hue]
                pygame.draw.rect(surf, color, r.inflate(8, 8), 2, border_radius=8)
            if RUN["helmet"]:
                pygame.draw.ellipse(surf, (240, 200, 60), (r.centerx - 10, r.top - 4, 20, 12))
                pygame.draw.ellipse(surf, C.INK, (r.centerx - 10, r.top - 4, 20, 12), 1)
            if RUN["boots"]:
                pygame.draw.rect(surf, (90, 200, 255), (r.left, r.bottom - 5, r.width, 5), border_radius=2)
            if RUN["device"] and self.aim is not None:
                pygame.draw.circle(surf, (240, 240, 245), self.aim, 7, 1)
                pygame.draw.circle(surf, BLUE, (self.aim[0] - 3, self.aim[1]), 2)
                pygame.draw.circle(surf, ORANGE, (self.aim[0] + 3, self.aim[1]), 2)
        if self.shot:
            a, b, rgb, _ = self.shot
            pygame.draw.line(surf, rgb, a, b, 2)
        self.draw_hud(surf)

    def draw_hud(self, surf):
        x, y = C.W - 12, 42
        f = _font(24)
        items = []
        if RUN["star"] > 0:
            items.append((f"STAR {RUN['star']:.0f}", (255, 140, 220)))
        if RUN["helmet"]:
            items.append(("HELMET", (240, 200, 60)))
        if RUN["boots"]:
            items.append(("BOOTS", (90, 200, 255)))
        if RUN["device"]:
            items.append(("PORTALS", (230, 230, 240)))
        items.append((f"COINS {RUN['coins']}", C.PIECE))
        for text, color in items:
            img = f.render(text, True, color)
            box = img.get_rect(topright=(x, y))
            pygame.draw.rect(surf, (0, 0, 0), box.inflate(10, 6), border_radius=4)
            surf.blit(img, box)
            x = box.left - 16
        if self.msg_t > 0:
            img = _font(26).render(self.msg, True, (255, 255, 255))
            box = img.get_rect(center=(C.W // 2, 78))
            pygame.draw.rect(surf, (0, 0, 0), box.inflate(16, 8), border_radius=5)
            surf.blit(img, box)


class _WallTop(Platform):
    """The standable top of a wall block (the wall draws itself)."""

    def __init__(self, wall):
        super().__init__(wall.rect.left, wall.rect.top, wall.rect.width)

    def draw(self, surf):
        pass


# --- the five levels, west to east -----------------------------------------------------------------

class FreightHall(Level):
    """Level 1: run, jump, coins, crates, a bot to stomp, a goo pit to clear, a spring."""

    title = "Level 1 - Freight Hall"
    palette = ((64, 70, 84), (72, 78, 94))

    def layout(self):
        self.decor += [Sign(300, 46, "LEVEL 1  FREIGHT HALL"), Window(560, 70, seed=12), CeilingLight(420)]
        self.hint(90, 250, "Jump into crates from below")
        self.hint(380, 300, "Land on bots to stomp them")
        self.hint(640, 420, "Clear the goo, bounce on the spring")
        self.coin_arc(100, 170, 470, 50, 4)
        self.crate(180, 380, "coin")
        self.crate(220, 380, "boots")
        self.crate(260, 380, "coin")
        self.coin_row(190, 350, 3, gap=40)
        self.hazards.append(StompBot(400, C.FLOOR_Y, left=330, right=570))
        self.hazards.append(Goo(590, 100))
        self.coin_arc(570, 710, 470, 90, 5)
        s = Spring(760)
        self.springs.append(s)
        self.platforms.append(s)
        self.platforms.append(Platform(720, 210, 160))
        self.coin_row(735, 186, 4, gap=30)
        self.furniture += [Locker(100, C.FLOOR_Y, name="freight locker"), FilingCabinet(320, C.FLOOR_Y),
                           Plant(840, 210)]


class InstallationLab(Level):
    """Level 2: pick up the portal device. A floor panel and a wall panel get you up to the switch ledge."""

    title = "Level 2 - Installation Lab"
    palette = ((70, 66, 84), (80, 76, 96))
    needs_device = True
    spare_device = (190, 760)

    def layout(self):
        self.decor += [Sign(300, 46, "LEVEL 2  INSTALLATION LAB"), CeilingLight(230), CeilingLight(560)]
        if not RUN["device"]:
            self.pedestal = DevicePedestal(190)
        self.hint(90, 290, "Grab the portal device")
        self.hint(330, 380, "Put one portal on the floor panel,")
        self.hint(330, 400, "the other on the wall panel. Walk in.")
        self.walls.append(Wall(840, 40, 40, 160, panels=[("left", 90, 196)]))
        self.panels.append(FloorPanel(360, 540))
        self.platforms.append(Platform(620, 200, 220))
        self.buttons.append(Button(680, 200, "exit", latch=True))
        door = Door(846, 200, 28, 300, "exit")
        self.walls.append(door)
        self.doors.append(door)
        self.coin_row(770, 176, 2)
        self.coin_row(390, 440, 5, gap=36)
        self.furniture += [Plinth(100, C.FLOOR_Y, colors=((200, 90, 160), (240, 240, 240))),
                           Projector(260, C.FLOOR_Y), Easel(560, C.FLOOR_Y)]


class FabricationBay(Level):
    """Level 3: carry a cube up the lift, drop into a floor portal, fly out of the wall over the goo,
    and set the cube on the button by the door."""

    title = "Level 3 - Fabrication Bay"
    palette = ((62, 72, 76), (70, 82, 86))
    needs_device = True
    spare_device = (100, 780)

    def layout(self):
        self.decor += [Sign(340, 46, "LEVEL 3  FABRICATION BAY"), CeilingLight(520)]
        self.dispensers.append(Dispenser(100))
        self.cubes.append(Cube((100, C.FLOOR_Y)))
        self.hint(230, 110, "F: grab the cube. Ride the lift (hold UP).")
        self.hint(230, 130, "Fall in fast, fly out fast.")
        self.hint(690, 300, "Cube on the button")
        self.lifts.append(Lift(150, y_top=150, y_bottom=C.FLOOR_Y, width=64))
        self.walls.append(Wall(100, 170, 30, 130, panels=[("right", 176, 296)]))
        self.panels.append(FloorPanel(214, 400))
        self.hazards.append(Goo(420, 260))
        br = LightBridge(420, 470, 260)
        br.link = "east_bridge"
        self.bridges.append(br)
        self.coin_arc(160, 700, 300, 60, 8)
        self.buttons.append(Button(720, C.FLOOR_Y, "exit"))
        door = Door(846, 40, 28, C.FLOOR_Y - 40, "exit")
        self.walls.append(door)
        self.doors.append(door)
        self.platforms.append(Platform(690, 400, 140))
        self.furniture += [FilingCabinet(670, C.FLOOR_Y), Printer3D(720, 400), Locker(800, C.FLOOR_Y)]


class XRTracking(Level):
    """Level 4: a timed bridge over the goo, a turret that can't see over the bridge, and a star crate."""

    title = "Level 4 - XR Tracking Floor"
    palette = ((58, 56, 80), (68, 64, 94))

    def layout(self):
        self.decor += [Sign(330, 46, "LEVEL 4  XR TRACKING FLOOR"), CeilingLight(300), CeilingLight(700)]
        self.hint(90, 300, "Crates! Then press F at the switch")
        self.hint(330, 360, "Turrets can't see you on the bridge")
        self.hint(640, 290, "Drop onto the turret")
        self.crate(120, 380, "star")
        self.crate(160, 380, "helmet")
        self.switches.append(Switch(240, "bridge", 5))
        self.hazards.append(Goo(300, 320))
        br = LightBridge(300, 440, 320)
        br.link = "bridge"
        self.bridges.append(br)
        self.coin_row(330, 410, 9, gap=32)
        self.hazards.append(Turret(810, C.FLOOR_Y, facing=-1))
        self.platforms.append(Platform(640, 360, 130))
        self.coin_row(655, 336, 4, gap=32)
        self.furniture += [VRStation(100, C.FLOOR_Y), ServerRack(700, 360), ServerRack(680, C.FLOOR_Y)]


class XRHoloStage(Level):
    """Level 5: the cube is up on a ledge only a portal reaches. Put it on the button to drop the laser grid
    in front of the headset vault, which holds the floor's code digit."""

    title = "Level 5 - XR Holo Stage"
    palette = ((52, 58, 80), (62, 70, 96))
    needs_device = True
    spare_device = (440, 820)

    def layout(self):
        self.decor += [Sign(330, 46, "LEVEL 5  XR HOLO STAGE"), Window(420, 90, seed=5), CeilingLight(640)]
        self.walls.append(Wall(60, 110, 36, 110, panels=[("right", 116, 216)]))
        self.platforms.append(Platform(96, 220, 170))
        self.dispensers.append(Dispenser(190))
        self.cubes.append(Cube((190, 220)))
        self.panels.append(FloorPanel(110, 260))
        self.hint(300, 170, "The cube is up there.")
        self.hint(300, 190, "Cube on the button turns off the lasers.")
        self.hint(600, 120, "The field closes portals")
        self.buttons.append(Button(470, C.FLOOR_Y, "grid"))
        self.fizzlers.append(Fizzler(590))
        self.platforms.append(Platform(640, 410, 120))
        self.platforms.append(Platform(760, 320, 120))
        self.hazards.append(LaserGrid(754, 230, 410, "grid"))
        self.hazards.append(StompBot(620, C.FLOOR_Y, left=610, right=860, speed=75))
        self.coin_row(660, 386, 3)
        self.furniture += [VRStation(300, C.FLOOR_Y), ServerRack(680, 410),
                           Locker(810, 320, name="headset vault", holds_piece=True)]


ROOMS = [FreightHall, InstallationLab, FabricationBay, XRTracking, XRHoloStage]
