"""Draws Ledger's app icon (the sign-in logo: rising bars on a dark tile) to assets/icon.png."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

SIZE = 1024
pygame.init()
img = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
tile = pygame.Rect(100, 100, SIZE - 200, SIZE - 200)   # macOS icon grid leaves a margin
pygame.draw.rect(img, (26, 26, 26), tile, border_radius=185)
bar_w, gap, base = 120, 60, tile.bottom - 190
for i, (h, col) in enumerate(((220, (255, 255, 255)), (340, (255, 255, 255)), (470, (46, 204, 113)))):
    x = tile.centerx - (3 * bar_w + 2 * gap) // 2 + i * (bar_w + gap)
    pygame.draw.rect(img, col, pygame.Rect(x, base - h, bar_w, h), border_radius=30)
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.png")
pygame.image.save(img, out)
print("wrote", out)
