"""Renders README screenshots into docs/ without opening a window or touching real save data.

    ./venv/bin/python tools/screenshots.py
"""
import os
import sys
import tempfile
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.argv = [sys.argv[0]]

import ledger_game as g  # noqa: E402
import pygame  # noqa: E402

g.ACCOUNTS_FILE = os.path.join(tempfile.mkdtemp(), "accounts.json")  # never write to real saves
OUT = os.path.join(ROOT, "docs")
os.makedirs(OUT, exist_ok=True)
st, scr = g.state, g.screen
shots = []


def frame(draw):
    draw()
    img = g._window_surface.copy()
    shots.append(img)
    return img


def app(tab, off=0):
    def draw():
        st.tab = tab
        g.scroll_offset[tab] = off
        g.draw_app_background(scr)
        g.draw_header(scr)
        g.safe_draw_tab(scr, tab)
        g.draw_tab_bar(scr)
    return draw


def save(name, img):
    pygame.image.save(img, os.path.join(OUT, name))


# A trader with some history, so charts and the portfolio have something to show.
g.create_account("StockNinja", "demo1234")
st.avatar.update({"skin": 2, "hair_style": 1, "hair_color": 1, "outfit": 3, "accessory": 1, "outfit_style": 1})
st.screen_mode = "playing"
st.tutorial_completed = st.tour_completed = True
for _ in range(40):
    g.tick_market()
for t in ("AAPL", "NVDA", "KO", "DIS"):
    a = g.find_asset(t)
    if a:
        g.do_buy(a, 1 if a["price"] > 150 else 2)
for _ in range(30):
    g.tick_market()
st.academy_completed = ["needs", "save"] if "save" in g.LESSONS else ["needs"]
st.toast = None
g.particles.clear()
g.floating_texts.clear()

save("signin.png", frame(lambda: g.draw_signin_screen(scr)))
save("home.png", frame(app("home")))
save("market.png", frame(app("market")))
save("portfolio.png", frame(app("portfolio")))
save("academy.png", frame(app("academy")))

g.open_lesson_game(g.academy_current_lesson())
g.lesson_game.update(stage_at=time.time() - 5, card_at=time.time() - 5)
save("lesson.png", frame(lambda: (g.draw_app_background(scr), g.draw_lesson_game(scr))))
g.close_lesson_game()

g.open_scam_game()
g.start_scam_run()
g.time.sleep(0.8)
save("scam.png", frame(lambda: (g.draw_app_background(scr), g.draw_scam_game(scr))))
g.close_scam_game()

g.open_battle(g.RIVALS[0])
save("battle.png", frame(lambda: (g.draw_app_background(scr), g.draw_battle(scr))))
g.battle["open"] = False

st.parent_unlocked = True
save("parents.png", frame(app("parents")))

# Banner: the six most representative screens side by side.
pick = ["home", "market", "academy", "lesson", "scam", "battle"]
imgs = [pygame.image.load(os.path.join(OUT, n + ".png")) for n in pick]
w, h = imgs[0].get_size()
gap = 24
banner = pygame.Surface((len(imgs) * w + (len(imgs) + 1) * gap, h + 2 * gap))
banner.fill((13, 12, 28))
for i, im in enumerate(imgs):
    banner.blit(im, (gap + i * (w + gap), gap))
save("banner.png", pygame.transform.smoothscale(banner, (banner.get_width() // 2, banner.get_height() // 2)))
print("wrote", sorted(os.listdir(OUT)))
