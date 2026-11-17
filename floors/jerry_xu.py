"""Floor 12: the Installation Lab and the XR Lab.

Two rooms, west to east: the Installation Lab, then the XR Lab. Floor 12 is above 10, so only the East
elevator stops here: you ride it up, step off into the XR Lab, cross into the Installation Lab, and ride
back down. The digit is in the plinth on the top ledge of the Installation Lab: take the lift up.
"""
import math

import pygame

from engine import config as C
from engine.bots import PatrolBot, Zapper
from engine.kit import (CeilingLight, Drone, FloorLaser, Locker, Plinth, Poster, ServerRack, Sign, Window,
                        Easel)
from engine.room import Furniture, Lift, Platform, Room

NAME = "Installation Lab + XR Lab"
AUTHOR = "Jerry Xu"


# --- parts of my own ---

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


class TrackingGrid:
    """Decor: the floor-tracking grid of the XR play space."""

    def __init__(self, left, right):
        self.left, self.right = left, right

    def draw(self, surf):
        for x in range(self.left, self.right + 1, 40):
            pygame.draw.line(surf, (80, 60, 120), (x, C.FLOOR_Y - 4), (x, C.FLOOR_Y), 2)


# --- WEST room: a wall on this side (no West elevator up here) ---

class InstallationLab(Room):
    """Projection pieces on plinths. The digit is in the plinth on the top ledge: ride the lift."""

    title = "Installation Lab"

    def build(self):
        self.decor += [Sign(330, 46, "INSTALLATION LAB"), CeilingLight(220), CeilingLight(700),
                       Poster(110, 90, "SITE", (70, 130, 180)), Window(780, 70, seed=12)]
        self.platforms.append(Platform(300, 410, 180))
        self.platforms.append(Platform(560, 230, 200))
        self.lifts.append(Lift(480, y_top=230, y_bottom=410, width=64))
        self.furniture += [Projector(130, C.FLOOR_Y), Easel(330, 410), Plinth(380, 410),
                           Plinth(640, 230, name="projection plinth", holds_piece=True, colors=((200, 90, 160), (240, 240, 240))),
                           Projector(760, C.FLOOR_Y, name="laser projector")]
        self.hazards.append(Zapper(560, y_top=260, y_bottom=C.FLOOR_Y, on_time=1.2, off_time=1.8))
        self.hazards.append(Drone(240, y_top=280, y_bottom=C.FLOOR_Y, speed=80))


# --- EAST room: the East elevator is through its right edge ---

class XRLab(Room):
    title = "XR Lab"

    def build(self):
        self.decor += [Sign(400, 46, "XR LAB"), CeilingLight(300), CeilingLight(660),
                       Poster(150, 90, "VR", (130, 80, 200)), Poster(240, 90, "AR", (80, 160, 150)),
                       TrackingGrid(260, 700)]
        self.platforms.append(Platform(600, 400, 180))
        self.furniture += [VRStation(130, C.FLOOR_Y), VRStation(420, C.FLOOR_Y, name="headset bench"),
                           ServerRack(640, 400), Locker(720, 400), ServerRack(800, C.FLOOR_Y)]
        self.hazards.append(PatrolBot(300, C.FLOOR_Y, left=220, right=760, speed=85))
        self.hazards.append(FloorLaser(260, 380, on_time=1.0, off_time=1.6))


ROOMS = [InstallationLab, XRLab]
