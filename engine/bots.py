"""Hazards you can use as they are, or subclass for your own.

Any hazard is an object with .rect, .update(dt, room, player) and .draw(surf). Touching its rect
costs the player a life (DEATH_PENALTY seconds off the clock) and sends them back to the door.
"""
import math

import pygame

from . import config as C


class PatrolBot:
    """A security bot that rolls back and forth along a surface.

    x is where it starts; y is the surface it rolls on (C.FLOOR_Y for the ground, or a platform's y).
    It patrols between left and right. With sees=True it speeds up when the player is on its level
    and in front of it.
    """

    W, H = 34, 40

    def __init__(self, x, y, left, right, speed=90.0, sees=True):
        self.x = float(x)
        self.y_surface = int(y)
        self.left, self.right = int(left), int(right)
        self.speed = float(speed)
        self.sees = sees
        self.dir = 1
        self.alert = False
        self.t = 0.0
        self.rect = pygame.Rect(int(self.x), self.y_surface - self.H, self.W, self.H)

    def update(self, dt, room, player):
        self.t += dt
        level = abs(player.rect.bottom - self.y_surface) < 6
        ahead = (player.rect.centerx - self.rect.centerx) * self.dir > 0
        self.alert = self.sees and level and ahead and abs(player.rect.centerx - self.rect.centerx) < 320
        v = self.speed * (2.2 if self.alert else 1.0)
        self.x += self.dir * v * dt
        if self.x < self.left:
            self.x, self.dir = float(self.left), 1
        elif self.x + self.W > self.right:
            self.x, self.dir = float(self.right - self.W), -1
        self.rect.x = int(self.x)

    def draw(self, surf):
        r = self.rect
        pygame.draw.rect(surf, (60, 64, 72), r, border_radius=8)
        pygame.draw.rect(surf, C.INK, r, 2, border_radius=8)
        eye_x = r.centerx + self.dir * 8
        eye = C.DANGER if self.alert else (120, 220, 255)
        pygame.draw.circle(surf, eye, (eye_x, r.top + 13), 6)
        if self.alert:
            s = pygame.Surface((90, 30), pygame.SRCALPHA)
            tip = 0 if self.dir > 0 else 90
            pygame.draw.polygon(s, (230, 70, 60, 70), [(tip, 13), (90 - tip, 2), (90 - tip, 28)])
            surf.blit(s, (eye_x if self.dir > 0 else eye_x - 90, r.top))
        wob = int(2 * math.sin(self.t * 14))
        pygame.draw.circle(surf, C.INK, (r.left + 8, r.bottom), 5 + (wob > 0))
        pygame.draw.circle(surf, C.INK, (r.right - 8, r.bottom), 5 + (wob <= 0))


class Zapper:
    """A floor-to-ceiling beam that switches on and off. x is its centre; it spans y_top..y_bottom.

    on_time and off_time are seconds; offset shifts it in the cycle so two zappers can alternate.
    For the last WARN seconds before it switches on, a faint flicker shows it's about to fire; it can't
    catch you until it's really on.
    """

    WARN = 0.5

    def __init__(self, x, y_top=0, y_bottom=C.FLOOR_Y, on_time=1.5, off_time=1.5, offset=0.0):
        self.on_time, self.off_time, self.t = on_time, off_time, offset
        self.on = self.warning = False
        self.box = pygame.Rect(int(x) - 4, int(y_top), 8, int(y_bottom - y_top))
        self.rect = pygame.Rect(0, 0, 0, 0)

    def update(self, dt, room, player):
        self.t = (self.t + dt) % (self.on_time + self.off_time)
        self.on = self.t < self.on_time
        self.warning = not self.on and (self.on_time + self.off_time) - self.t <= min(self.WARN, self.off_time)
        self.rect = self.box if self.on else pygame.Rect(0, 0, 0, 0)

    def draw(self, surf):
        pygame.draw.rect(surf, (90, 90, 100), (self.box.x - 4, self.box.top - 8, 16, 8))
        pygame.draw.rect(surf, (90, 90, 100), (self.box.x - 4, self.box.bottom, 16, 8))
        if self.on:
            pygame.draw.rect(surf, C.DANGER, self.box)
            pygame.draw.rect(surf, (255, 200, 190), self.box.inflate(-4, 0))
        elif self.warning and int(self.t * 20) % 2:
            pygame.draw.line(surf, (170, 80, 80), self.box.midtop, self.box.midbottom, 1)


class SecurityCamera:
    """A ceiling camera that sweeps a spotlight back and forth along a surface. Step into the lit spot and
    you're caught; jump over it, or wait while it pauses at the end of its sweep.

    x is where the camera hangs (from the ceiling at y=46). The spot sweeps between left and right along the
    surface at y (C.FLOOR_Y for the ground, or a platform's y), at speed px/s, and waits `pause` seconds at
    each end. spot is how wide the lit spot is. offset (px) starts the spot further along its sweep.
    """

    MOUNT_Y = 46

    def __init__(self, x, y=C.FLOOR_Y, left=None, right=None, speed=110.0, pause=0.6, spot=70, offset=0.0):
        self.x, self.y_surface = int(x), int(y)
        self.left = int(left if left is not None else x - 200)
        self.right = int(right if right is not None else x + 200)
        self.speed, self.pause, self.spot = float(speed), float(pause), int(spot)
        self.cx = float(min(self.right, self.left + offset))
        self.dir = 1                # which way the spot is moving (a moving hazard: not a doorway blocker)
        self.wait = 0.0
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.glow = pygame.Surface((self.spot, 18), pygame.SRCALPHA)     # made once, not every frame
        pygame.draw.ellipse(self.glow, (255, 240, 170, 110), self.glow.get_rect())
        self._place()

    def _place(self):
        # The part that catches you: the lit patch, from the surface up to ankle height.
        self.rect = pygame.Rect(int(self.cx - self.spot / 2) + 6, self.y_surface - 14, self.spot - 12, 14)

    def update(self, dt, room, player):
        if self.wait > 0:
            self.wait -= dt
        else:
            self.cx += self.dir * self.speed * dt
            if self.cx >= self.right:
                self.cx, self.dir, self.wait = float(self.right), -1, self.pause
            elif self.cx <= self.left:
                self.cx, self.dir, self.wait = float(self.left), 1, self.pause
        self._place()

    def draw(self, surf):
        cam = (self.x, self.MOUNT_Y + 10)
        half = self.spot // 2
        beam = (255, 236, 160)
        pygame.draw.line(surf, beam, cam, (int(self.cx) - half, self.y_surface), 1)
        pygame.draw.line(surf, beam, cam, (int(self.cx) + half, self.y_surface), 1)
        surf.blit(self.glow, (int(self.cx) - half, self.y_surface - 9))
        pygame.draw.rect(surf, (90, 90, 100), (self.x - 3, self.MOUNT_Y - 6, 6, 8))
        body = pygame.Rect(0, 0, 26, 14)
        body.center = cam
        pygame.draw.rect(surf, (200, 202, 210), body, border_radius=4)
        pygame.draw.rect(surf, C.INK, body, 2, border_radius=4)
        lens_x = body.centerx + (6 if self.cx > self.x else -6)
        pygame.draw.circle(surf, C.DANGER, (lens_x, body.centery + 2), 3)
