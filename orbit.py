#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ORBIT / TERMINAL UNIVERSE
An interactive Solar System right in your terminal.

    orbit                       # English (default)
    orbit --lang ru             # Russian

Controls
    ← →   (A D)       select a body / fly to the neighbouring one
    ENTER  ↓          approach the selected body
    ESC  ⌫            return to the system view
    ↑ ↓               scroll the story (in planet view)
    + -               zoom
    < >   [ ]         simulation speed
    SPACE             pause
    I                 hide / show the info panel
    H  TAB            clean view: hide every panel, leave only the planets
    L                 switch language (English / Russian)
    0 … 8             quick jump: 0 — Sun, 1 — Mercury … 8 — Neptune
    Q                 quit
    Mouse: click a planet to fly to it, wheel to zoom.

Python 3 standard library only. Starting positions of the planets match
their real positions for today's date (mean longitudes); after that,
time runs faster.
"""

import colorsys
import curses
import locale
import math
import os
import random
import sys
import textwrap
import time
from collections import OrderedDict

TAU = math.tau
HALF_PI = math.pi / 2
SIN_E = 0.38                          # camera elevation above the ecliptic plane
COS_E = math.sqrt(1.0 - SIN_E * SIN_E)
TW, TH = 256, 128                     # surface texture resolution
N_TEX = TW * TH
FPS_TARGET = 30
SPEEDS = (0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 40.0)
J2000_UNIX = 946728000.0              # 2000-01-01 12:00 UTC

# Braille: dot bit for [row 0..3][column 0..1] inside a 2×4 cell
BB = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))
BRAILLE = [chr(0x2800 + i) for i in range(256)]


# Ordered-dithering thresholds per dot (8×8 table, values 0…1)
_BAYER8 = ((0, 32, 8, 40, 2, 34, 10, 42), (48, 16, 56, 24, 50, 18, 58, 26),
           (12, 44, 4, 36, 14, 46, 6, 38), (60, 28, 52, 20, 62, 30, 54, 22),
           (3, 35, 11, 43, 1, 33, 9, 41), (51, 19, 59, 27, 49, 17, 57, 25),
           (15, 47, 7, 39, 13, 45, 5, 37), (63, 31, 55, 23, 61, 29, 53, 21))
# "line" dithering — horizontal dashes, like the bands of gas giants
_LINES4 = ((0, 2, 1, 3), (8, 10, 9, 11), (4, 6, 5, 7), (12, 14, 13, 15))
THRESH = {
    'bayer': [[(_BAYER8[y][x] + 0.5) / 64 for x in range(8)] for y in range(8)],
    'lines': [[(_LINES4[y & 3][x & 3] + 0.5) / 16 for x in range(8)] for y in range(8)],
}

KEY_LIGHT = (-0.5, -0.32, 0.8)          # close-up light: upper left, slightly in front
LAND = frozenset((28, 64, 107, 108, 137, 179, 186))   # Earth land colors (for city lights at night)


def clamp(x, a, b):
    return a if x < a else b if x > b else x


def lerp(a, b, t):
    return a + (b - a) * t


def smootherstep(t):
    return t * t * t * (t * (t * 6 - 15) + 10)


# ═══════════════════════════════ data ════════════════════════════════════

# Physical and visual parameters. Distances and sizes are NOT to scale
# (otherwise the inner planets would be invisible); the panel facts are real.
#   R      orbit radius (world units)       r      planet radius (world units)
#   period orbital period, years            L0/rate mean longitude at J2000, deg / deg per day
#   spin   visual rotation, rad/s           roll/pitch  orientation of the rotation axis
#   moons  ((en, ru), orbit radius in planet radii, size, period s, palette, texture)
BODIES = [
    dict(key='sun', R=0.0, r=8.5, period=None, L0=0.0, rate=0.0,
         spin=0.05, roll=0.12, pitch=0.10, color=220, atm=None, dither='bayer',
         ext=1.45, ring=None, moons=()),
    dict(key='mercury', R=15.0, r=1.9, period=0.2408, L0=252.2503, rate=4.0923344,
         spin=0.04, roll=0.0, pitch=0.05, color=248, atm=None, dither='bayer',
         ext=1.0, ring=None, moons=()),
    dict(key='venus', R=23.0, r=3.0, period=0.6152, L0=181.9798, rate=1.6021302,
         spin=-0.05, roll=0.05, pitch=0.08, color=223, atm=223, dither='bayer',
         ext=1.0, ring=None, moons=()),
    dict(key='earth', R=32.0, r=3.2, period=1.0, L0=100.4664, rate=0.9856091,
         spin=0.25, roll=0.41, pitch=0.18, color=39, atm=39, dither='bayer',
         ext=1.0, ring=None,
         moons=((('Moon', 'Луна'), 2.7, 0.24, 26.0, (240, 247, 254), 'luna'),)),
    dict(key='mars', R=41.0, r=2.3, period=1.8808, L0=355.4330, rate=0.5240207,
         spin=0.24, roll=0.44, pitch=0.15, color=173, atm=None, dither='bayer',
         ext=1.0, ring=None,
         moons=((('Phobos', 'Фобос'), 1.75, 0.07, 7.0, (239, 243, 247), 'rock'),
                (('Deimos', 'Деймос'), 2.5, 0.055, 13.0, (239, 243, 247), 'rock'))),
    dict(key='jupiter', R=66.0, r=7.6, period=11.862, L0=34.3515, rate=0.0830853,
         spin=0.5, roll=0.05, pitch=0.06, color=216, atm=None, dither='lines',
         ext=1.0, ring=None,
         moons=((('Io', 'Ио'), 1.6, 0.075, 6.0, (136, 186, 229), 'io'),
                (('Europa', 'Европа'), 2.0, 0.07, 10.0, (137, 223, 230), 'ice'),
                (('Ganymede', 'Ганимед'), 2.5, 0.095, 17.0, (241, 246, 251), 'rock'),
                (('Callisto', 'Каллисто'), 3.1, 0.09, 30.0, (236, 240, 245), 'rock'))),
    dict(key='saturn', R=88.0, r=6.4, period=29.457, L0=50.0775, rate=0.0334443,
         spin=0.45, roll=-0.16, pitch=0.36, color=223, atm=None, dither='lines',
         ext=1.0, ring=None, wide_ring=True,
         moons=((('Enceladus', 'Энцелад'), 2.6, 0.04, 9.0, (152, 255, 231), 'ice'),
                (('Rhea', 'Рея'), 2.85, 0.05, 15.0, (243, 248, 253), 'rock'),
                (('Titan', 'Титан'), 3.25, 0.1, 32.0, (136, 172, 179), 'titan'))),
    dict(key='uranus', R=109.0, r=4.6, period=84.011, L0=314.0550, rate=0.0117331,
         spin=-0.3, roll=1.25, pitch=0.75, color=152, atm=116, dither='bayer',
         ext=1.0,
         ring=((1.64, 1.64, 'dot', 66), (1.78, 1.78, 'dot', 66), (2.0, 2.0, 'dense', 109)),
         moons=((('Ariel', 'Ариэль'), 2.3, 0.055, 11.0, (243, 248, 252), 'rock'),
                (('Titania', 'Титания'), 2.65, 0.07, 17.0, (242, 247, 251), 'rock'),
                (('Oberon', 'Оберон'), 3.0, 0.07, 25.0, (239, 244, 249), 'rock'))),
    dict(key='neptune', R=128.0, r=4.4, period=164.8, L0=304.3487, rate=0.0059810,
         spin=0.33, roll=0.5, pitch=0.15, color=33, atm=33, dither='lines',
         ext=1.0,
         ring=((2.15, 2.15, 'sparse', 61), (2.54, 2.54, 'sparse', 61)),
         moons=((('Triton', 'Тритон'), 2.4, 0.09, -20.0, (174, 224, 231), 'ice'),)),
]

RING_GAP = {'dense': 1.25, 'dash': 1.0, 'dot': 2.5, 'sparse': 4.5}

LANGS = ('en', 'ru')

# Texts about each body: name, class, distance label, facts and a short story.
# 'to' (Russian only) is the "towards …" form used in the flight HUD.
TEXT = {
    'sun': {
        'en': dict(
            name='Sun', cls='STAR · G2V YELLOW DWARF', au='star',
            facts=[('Diameter', '1,392,700 km'), ('Mass', '333,000 Earths'),
                   ('Surface', '≈ 5,500 °C'), ('Core', '≈ 15 million °C'),
                   ('Rotation', '25–35 days'), ('Age', '≈ 4.6 billion years')],
            story='The Sun is an ordinary yellow dwarf star, yet for us it is the source of '
                  'all life. It holds 99.86% of the mass of the Solar System. Every second, '
                  'its core fuses about 600 million tonnes of hydrogen into helium. Light '
                  'from its surface reaches Earth in 8 minutes 20 seconds, while energy born '
                  'in the core takes tens of thousands of years to work its way out. In about '
                  '5 billion years the Sun will swell into a red giant.'),
        'ru': dict(
            name='Солнце', to='к Солнцу', cls='ЗВЕЗДА · ЖЁЛТЫЙ КАРЛИК G2V', au='звезда',
            facts=[('Диаметр', '1 392 700 км'), ('Масса', '333 000 масс Земли'),
                   ('Поверхность', '≈ 5 500 °C'), ('Ядро', '≈ 15 млн °C'),
                   ('Оборот вокруг оси', '25–35 суток'), ('Возраст', '≈ 4,6 млрд лет')],
            story='Солнце — самая обычная звезда, жёлтый карлик, но для нас это источник '
                  'всей жизни. В нём сосредоточено 99,86% массы Солнечной системы. Каждую '
                  'секунду в ядре около 600 миллионов тонн водорода превращаются в гелий. '
                  'Свет от поверхности долетает до Земли за 8 минут 20 секунд, а энергия, '
                  'рождённая в ядре, пробивается наружу десятки тысяч лет. Примерно через '
                  '5 миллиардов лет Солнце раздуется в красного гиганта.'),
    },
    'mercury': {
        'en': dict(
            name='Mercury', cls='TERRESTRIAL PLANET', au='0.39 AU',
            facts=[('Diameter', '4,879 km'), ('Mass', '0.055 Earths'),
                   ('From the Sun', '0.39 AU · 58 million km'), ('Year', '88 Earth days'),
                   ('Solar day', '176 Earth days'), ('Temperature', '−173…+427 °C'),
                   ('Moons', 'none')],
            story='The smallest planet and the closest one to the Sun. With almost no '
                  'atmosphere, its surface bakes at +427 °C by day and freezes to −173 °C '
                  'at night. Mercury spins so slowly that a single solar day lasts 176 Earth '
                  'days — exactly two of its years. The surface is pocked with craters like '
                  'the Moon, and water ice hides at the bottom of permanently shadowed polar '
                  'craters.'),
        'ru': dict(
            name='Меркурий', to='к Меркурию', cls='ПЛАНЕТА ЗЕМНОЙ ГРУППЫ', au='0,39 а.е.',
            facts=[('Диаметр', '4 879 км'), ('Масса', '0,055 массы Земли'),
                   ('От Солнца', '0,39 а.е. · 58 млн км'), ('Год', '88 земных суток'),
                   ('Солнечные сутки', '176 земных суток'), ('Температура', '−173…+427 °C'),
                   ('Спутники', 'нет')],
            story='Самая маленькая планета и ближайшая к Солнцу. Атмосферы почти нет, '
                  'поэтому днём поверхность раскаляется до +427 °C, а ночью остывает '
                  'до −173 °C. Меркурий вращается так медленно, что солнечные сутки на нём '
                  'длятся 176 земных — ровно два его года. Поверхность изрыта кратерами, '
                  'как у Луны, а на дне вечно затенённых полярных кратеров прячется '
                  'водяной лёд.'),
    },
    'venus': {
        'en': dict(
            name='Venus', cls='TERRESTRIAL PLANET', au='0.72 AU',
            facts=[('Diameter', '12,104 km'), ('Mass', '0.82 Earths'),
                   ('From the Sun', '0.72 AU · 108 million km'), ('Year', '225 Earth days'),
                   ('Day', '243 days, retrograde'), ('Temperature', '≈ +464 °C'),
                   ('Moons', 'none')],
            story="Earth's twin in size — and a true hell in conditions. A dense carbon "
                  'dioxide atmosphere drives a runaway greenhouse effect: the surface sits at '
                  "+464 °C — hotter than Mercury — under a pressure 92 times Earth's. The sky "
                  'is veiled by clouds of sulfuric acid. Venus spins backwards, so the Sun '
                  'rises in the west there, and its day is longer than its year.'),
        'ru': dict(
            name='Венера', to='к Венере', cls='ПЛАНЕТА ЗЕМНОЙ ГРУППЫ', au='0,72 а.е.',
            facts=[('Диаметр', '12 104 км'), ('Масса', '0,82 массы Земли'),
                   ('От Солнца', '0,72 а.е. · 108 млн км'), ('Год', '225 земных суток'),
                   ('Сутки', '243 суток, обратное'), ('Температура', '≈ +464 °C'),
                   ('Спутники', 'нет')],
            story='Близнец Земли по размеру — и настоящий ад по условиям. Плотная атмосфера '
                  'из углекислого газа устроила чудовищный парниковый эффект: у поверхности '
                  '+464 °C — жарче, чем на Меркурии, — а давление в 92 раза выше земного. '
                  'Небо затянуто облаками серной кислоты. Венера вращается в обратную '
                  'сторону, поэтому Солнце там восходит на западе, а её сутки длиннее её года.'),
    },
    'earth': {
        'en': dict(
            name='Earth', cls='TERRESTRIAL PLANET', au='1.00 AU · you are here',
            facts=[('Diameter', '12,742 km'), ('Mass', '5.97×10²⁴ kg'),
                   ('From the Sun', '1 AU · 149.6 million km'), ('Year', '365.25 days'),
                   ('Day', '23 h 56 min'), ('Temperature', '−89…+57 °C'),
                   ('Moons', '1 — the Moon')],
            story='Our home, and so far the only place in the Universe known to host life. '
                  'About 71% of the surface is covered by oceans. The magnetic field '
                  'deflects the solar wind, and the nitrogen-oxygen atmosphere shields us '
                  "from meteors and harsh radiation. The Moon stabilizes the tilt of Earth's "
                  'axis, which has kept the climate relatively steady for millions of years. '
                  'Earth is also the densest planet in the Solar System.'),
        'ru': dict(
            name='Земля', to='к Земле', cls='ПЛАНЕТА ЗЕМНОЙ ГРУППЫ', au='1,00 а.е. · вы здесь',
            facts=[('Диаметр', '12 742 км'), ('Масса', '5,97·10²⁴ кг'),
                   ('От Солнца', '1 а.е. · 149,6 млн км'), ('Год', '365,25 суток'),
                   ('Сутки', '23 ч 56 мин'), ('Температура', '−89…+57 °C'),
                   ('Спутники', '1 — Луна')],
            story='Наш дом и пока единственное известное место во Вселенной, где есть жизнь. '
                  'Около 71% поверхности покрыто океанами. Магнитное поле отклоняет солнечный '
                  'ветер, а атмосфера из азота и кислорода защищает от метеоров и жёсткого '
                  'излучения. Луна стабилизирует наклон земной оси — поэтому климат миллионы '
                  'лет остаётся относительно устойчивым. А ещё Земля — самая плотная планета '
                  'Солнечной системы.'),
    },
    'mars': {
        'en': dict(
            name='Mars', cls='TERRESTRIAL PLANET', au='1.52 AU',
            facts=[('Diameter', '6,779 km'), ('Mass', '0.107 Earths'),
                   ('From the Sun', '1.52 AU · 228 million km'), ('Year', '687 Earth days'),
                   ('Day', '24 h 37 min'), ('Temperature', '−153…+20 °C'),
                   ('Moons', '2 — Phobos, Deimos')],
            story='The Red Planet owes its color to iron oxide — rusty dust, in other words. '
                  'It is home to the tallest volcano in the Solar System, Olympus Mons '
                  '(about 22 km high), and the Valles Marineris canyon system, more than '
                  '4,000 km long. The atmosphere is very thin — less than 1% of the pressure '
                  'on Earth — and the poles are capped with water ice and dry ice. Rivers '
                  'once flowed on Mars; today rovers drive across it.'),
        'ru': dict(
            name='Марс', to='к Марсу', cls='ПЛАНЕТА ЗЕМНОЙ ГРУППЫ', au='1,52 а.е.',
            facts=[('Диаметр', '6 779 км'), ('Масса', '0,107 массы Земли'),
                   ('От Солнца', '1,52 а.е. · 228 млн км'), ('Год', '687 земных суток'),
                   ('Сутки', '24 ч 37 мин'), ('Температура', '−153…+20 °C'),
                   ('Спутники', '2 — Фобос, Деймос')],
            story='Красная планета: цвет ей придаёт оксид железа — проще говоря, ржавая пыль. '
                  'Здесь высочайший вулкан Солнечной системы, гора Олимп (около 22 км), '
                  'и каньон Долины Маринера длиной более 4 000 км. Атмосфера очень разрежена — '
                  'давление меньше 1% земного, — а на полюсах лежат шапки из водяного и сухого '
                  'льда. Когда-то по Марсу текли реки, а сегодня по нему ездят марсоходы.'),
    },
    'jupiter': {
        'en': dict(
            name='Jupiter', cls='GAS GIANT', au='5.20 AU',
            facts=[('Diameter', '142,984 km (11× Earth)'), ('Mass', '318 Earths'),
                   ('From the Sun', '5.2 AU · 778 million km'), ('Year', '11.9 Earth years'),
                   ('Day', '9 h 56 min'), ('Temperature', '≈ −145 °C (clouds)'),
                   ('Moons', '95+')],
            story='The king of planets: Jupiter is 2.5 times more massive than all the other '
                  'planets combined. It is a gas giant with no solid surface. The stripes are '
                  'ammonia clouds stretched out by its furious spin — a day here lasts less '
                  'than 10 hours. The Great Red Spot is a storm larger than Earth that has been '
                  'observed for almost 200 years. And beneath the icy crust of its moon Europa '
                  'lies an ocean of liquid water.'),
        'ru': dict(
            name='Юпитер', to='к Юпитеру', cls='ГАЗОВЫЙ ГИГАНТ', au='5,20 а.е.',
            facts=[('Диаметр', '142 984 км (×11 Земли)'), ('Масса', '318 масс Земли'),
                   ('От Солнца', '5,2 а.е. · 778 млн км'), ('Год', '11,9 земных лет'),
                   ('Сутки', '9 ч 56 мин'), ('Температура', '≈ −145 °C (облака)'),
                   ('Спутники', '95+')],
            story='Король планет: Юпитер в 2,5 раза массивнее всех остальных планет вместе '
                  'взятых. Это газовый гигант без твёрдой поверхности. Полосы на диске — облака '
                  'аммиака, растянутые бешеным вращением: сутки здесь длятся меньше 10 часов. '
                  'Большое красное пятно — шторм крупнее Земли, который наблюдают уже почти '
                  '200 лет. А под ледяной коркой спутника Европы скрыт океан жидкой воды.'),
    },
    'saturn': {
        'en': dict(
            name='Saturn', cls='GAS GIANT', au='9.54 AU',
            facts=[('Diameter', '120,536 km (9.5× Earth)'), ('Mass', '95 Earths'),
                   ('From the Sun', '9.5 AU · 1.43 billion km'), ('Year', '29.5 Earth years'),
                   ('Day', '10 h 33 min'), ('Temperature', '≈ −178 °C (clouds)'),
                   ('Moons', '270+')],
            story="The jewel of the Solar System. Saturn's rings span about 280,000 "
                  'kilometers, yet they are usually only about ten meters thick: billions of '
                  "chunks of ice and dust. The planet's average density is lower than that of "
                  'water — in a big enough ocean, Saturn would float. It has more known moons '
                  'than any other planet, and the largest, Titan, is wrapped in a thick '
                  'atmosphere and has seas of liquid methane.'),
        'ru': dict(
            name='Сатурн', to='к Сатурну', cls='ГАЗОВЫЙ ГИГАНТ', au='9,54 а.е.',
            facts=[('Диаметр', '120 536 км (×9,5 Земли)'), ('Масса', '95 масс Земли'),
                   ('От Солнца', '9,5 а.е. · 1,43 млрд км'), ('Год', '29,5 земных лет'),
                   ('Сутки', '10 ч 33 мин'), ('Температура', '≈ −178 °C (облака)'),
                   ('Спутники', '270+')],
            story='Жемчужина Солнечной системы. Кольца Сатурна раскинулись примерно на '
                  '280 тысяч километров, но толщина их обычно всего около десятка метров: это '
                  'миллиарды ледяных глыб и пылинок. Средняя плотность планеты меньше, чем у '
                  'воды, — в гигантском океане Сатурн бы плавал. У него больше всего известных '
                  'спутников, а самый крупный, Титан, окутан плотной атмосферой, и на нём есть '
                  'моря жидкого метана.'),
    },
    'uranus': {
        'en': dict(
            name='Uranus', cls='ICE GIANT', au='19.2 AU',
            facts=[('Diameter', '51,118 km (4× Earth)'), ('Mass', '14.5 Earths'),
                   ('From the Sun', '19.2 AU · 2.87 billion km'), ('Year', '84 Earth years'),
                   ('Day', '17 h 14 min'), ('Axial tilt', '97.8°'),
                   ('Temperature', 'down to −224 °C'), ('Moons', '28+')],
            story='An ice giant that rolls along its orbit lying on its side: its axis is '
                  'tilted by almost 98°. As a result, each pole gets 42 years of sunlight '
                  'followed by 42 years of darkness. Methane in the atmosphere gives it its '
                  'blue-green color. Uranus was the first planet discovered with a telescope — '
                  'William Herschel found it in 1781. It has the coldest atmosphere of any '
                  'planet, down to −224 °C.'),
        'ru': dict(
            name='Уран', to='к Урану', cls='ЛЕДЯНОЙ ГИГАНТ', au='19,2 а.е.',
            facts=[('Диаметр', '51 118 км (×4 Земли)'), ('Масса', '14,5 массы Земли'),
                   ('От Солнца', '19,2 а.е. · 2,87 млрд км'), ('Год', '84 земных года'),
                   ('Сутки', '17 ч 14 мин'), ('Наклон оси', '97,8°'),
                   ('Температура', 'до −224 °C'), ('Спутники', '28+')],
            story='Ледяной гигант, который катится по орбите, лёжа на боку: его ось наклонена '
                  'почти на 98°. Поэтому каждый полюс 42 года освещён Солнцем, а следующие '
                  '42 года погружён в ночь. Голубовато-зелёный цвет даёт метан в атмосфере. '
                  'Уран — первая планета, открытая с помощью телескопа: в 1781 году его '
                  'обнаружил Уильям Гершель. Здесь самая холодная атмосфера среди планет — '
                  'до −224 °C.'),
    },
    'neptune': {
        'en': dict(
            name='Neptune', cls='ICE GIANT', au='30.1 AU',
            facts=[('Diameter', '49,528 km (3.9× Earth)'), ('Mass', '17 Earths'),
                   ('From the Sun', '30.1 AU · 4.5 billion km'), ('Year', '164.8 Earth years'),
                   ('Day', '16 h 6 min'), ('Temperature', '≈ −214 °C'),
                   ('Moons', '16')],
            story='The most distant planet: sunlight takes more than four hours to reach it. '
                  'Neptune was discovered "with the tip of a pen": in 1846 Urbain Le Verrier '
                  "calculated its position from disturbances in Uranus's orbit, and on the "
                  'very night he received the prediction, Johann Galle found the planet '
                  'through a telescope. The fastest winds in the Solar System blow here — up '
                  'to 2,000 km/h. Its largest moon, Triton, orbits backwards and is probably '
                  'a captured Kuiper Belt object.'),
        'ru': dict(
            name='Нептун', to='к Нептуну', cls='ЛЕДЯНОЙ ГИГАНТ', au='30,1 а.е.',
            facts=[('Диаметр', '49 528 км (×3,9 Земли)'), ('Масса', '17 масс Земли'),
                   ('От Солнца', '30,1 а.е. · 4,5 млрд км'), ('Год', '164,8 земных лет'),
                   ('Сутки', '16 ч 6 мин'), ('Температура', '≈ −214 °C'),
                   ('Спутники', '16')],
            story='Самая далёкая планета: солнечный свет идёт до неё больше четырёх часов. '
                  'Нептун открыли «на кончике пера»: в 1846 году Урбен Леверье вычислил его '
                  'положение по возмущениям орбиты Урана, и в ту же ночь, получив расчёты, '
                  'Иоганн Галле нашёл планету в телескоп. Здесь дуют самые быстрые ветры '
                  'в Солнечной системе — до 2 000 км/ч. Крупнейший спутник, Тритон, движется '
                  'в обратную сторону: вероятно, это захваченный объект пояса Койпера.'),
    },
}

# Interface strings.
UI = {
    'en': dict(
        boot='initializing simulation…', terrain='▸ terrain & clouds: {}', moons='MOONS',
        ephem='▸ ephemeris for {}', date='%Y-%m-%d',
        too_small='Please enlarge the terminal window (min 64×20)',
        course='▸ COURSE: {}', back='◂ RETURNING TO SYSTEM VIEW',
        hints_view=[('SPACE', 'pause'), ('← →', 'select'), ('ENTER', 'approach'),
                    ('+/-', 'zoom'), ('< >', 'time'), ('0-8', 'jump'), ('H', 'clean view'),
                    ('L', 'русский'), ('Q', 'quit')],
        hints_body=[('ESC', 'back'), ('← →', 'next planet'), ('↑ ↓', 'scroll'),
                    ('+/-', 'zoom'), ('I', 'panel'), ('H', 'clean view'), ('L', 'русский'),
                    ('SPACE', 'pause'), ('Q', 'quit')],
        clean_hint='[H] show interface'),
    'ru': dict(
        boot='инициализация симуляции…', terrain='▸ рельеф и облака: {}', moons='СПУТНИКИ',
        ephem='▸ эфемериды на {}', date='%d.%m.%Y',
        too_small='Увеличьте окно терминала (минимум 64×20)',
        course='▸ КУРС {}', back='◂ ВОЗВРАТ НА ОБЗОРНУЮ ОРБИТУ',
        hints_view=[('SPACE', 'пауза'), ('← →', 'выбор'), ('ENTER', 'приблизиться'),
                    ('+/-', 'зум'), ('< >', 'время'), ('0-8', 'перелёт'), ('H', 'чистый вид'),
                    ('L', 'english'), ('Q', 'выход')],
        hints_body=[('ESC', 'назад'), ('← →', 'соседняя планета'), ('↑ ↓', 'текст'),
                    ('+/-', 'зум'), ('I', 'панель'), ('H', 'чистый вид'), ('L', 'english'),
                    ('SPACE', 'пауза'), ('Q', 'выход')],
        clean_hint='[H] вернуть интерфейс'),
}


# ═══════════════════════════ noise and textures ═══════════════════════════

def _smooth(t):
    return t * t * (3.0 - 2.0 * t)


def fbm_field(seed, base, octaves, gain=0.5, ys=0.5):
    """Fractal value noise for a whole TW×TH texture at once (periodic in longitude).
    ys — latitude frequency relative to longitude: larger ys → features stretched along longitude."""
    rnd = random.Random(seed)
    acc = [0.0] * N_TEX
    f, amp, norm = base, 1.0, 0.0
    for _ in range(octaves):
        grid = [[rnd.random() for _ in range(f)] for _ in range(int(f * ys) + 2)]
        cols = []
        for i in range(TW):
            x = (i + 0.5) / TW * f
            ix = int(x)
            cols.append((ix % f, (ix + 1) % f, _smooth(x - ix)))
        for j in range(TH):
            y = (j + 0.5) / TH * f * ys
            iy = int(y)
            uy = _smooth(y - iy)
            lr = [(a + (b - a) * uy) * amp for a, b in zip(grid[iy], grid[iy + 1])]
            k = j * TW
            acc[k:k + TW] = [s + lr[a] + (lr[b] - lr[a]) * u
                             for s, (a, b, u) in zip(acc[k:k + TW], cols)]
        norm += amp
        f *= 2
        amp *= gain
    inv = 1.0 / norm
    return [v * inv for v in acc]


def lat_of(j):
    return (0.5 - (j + 0.5) / TH) * math.pi


LATD = [math.degrees(lat_of(j)) for j in range(TH)]


def pct(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, int(q * len(s)))]


def stamp(cu, clat, rad, fn, ang=False):
    """Call fn(k, d[, a]) for texels within radius rad (radians) of (cu, clat):
    d — distance from the centre as a fraction of rad, a — direction."""
    j0 = max(0, int((0.5 - (clat + rad) / math.pi) * TH) - 1)
    j1 = min(TH - 1, int((0.5 - (clat - rad) / math.pi) * TH) + 1)
    for j in range(j0, j1 + 1):
        lat = lat_of(j)
        cl = max(0.1, math.cos(lat))
        du = rad / cl / TAU
        i0 = int((cu - du) * TW) - 2
        dlat = lat - clat
        base = j * TW
        for ii in range(i0, i0 + min(TW, int(2 * du * TW) + 5)):
            dl = (((ii + 0.5) / TW - cu + 0.5) % 1.0 - 0.5) * TAU * cl
            d = math.hypot(dlat, dl) / rad
            if d < 1.0:
                if ang:
                    fn(base + ii % TW, d, math.atan2(dlat, dl))
                else:
                    fn(base + ii % TW, d)


def oval(lat0, u0, hw, hh, fn, emax=1.0):
    """Call fn(k, e) inside an oval; e is the squared elliptical distance. hw, hh in degrees."""
    sq = math.sqrt(emax)
    for j in range(TH):
        dy = (LATD[j] - lat0) / hh
        if abs(dy) >= sq:
            continue
        base = j * TW
        for ii in range(int((u0 - hw * sq / 360) * TW) - 2, int((u0 + hw * sq / 360) * TW) + 3):
            dx = ((ii + 0.5) / TW - u0) * 360 / hw
            e = dx * dx + dy * dy
            if e < emax:
                fn(base + ii % TW, e)


def setter(tv, tc, val, col):
    def f(k, *_):
        tv[k] = val
        tc[k] = col
    return f


def craters(tv, rnd, count, rmin, rmax, rays=0, depth=0.42):
    def bowl(k, d):
        if d > 0.78:
            tv[k] = min(1.0, tv[k] * 1.22 + 0.06)            # rim
        else:
            tv[k] *= (1 - depth) + depth * (d / 0.78) ** 2  # bowl
    for _ in range(count):
        rad = rmin * (rmax / rmin) ** (rnd.random() ** 2.4)
        stamp(rnd.random(), math.asin(rnd.uniform(-0.97, 0.97)), rad, bowl)
    for _ in range(rays):                                    # young rayed craters
        rad = rnd.uniform(0.035, 0.055)
        cu, clat = rnd.random(), math.asin(rnd.uniform(-0.85, 0.85))
        nr, ph = rnd.randint(9, 15), rnd.random() * TAU

        def ray(k, d, a, nr=nr, ph=ph):
            if d > 0.14 and math.cos(a * nr + ph + 2.5 * d) > 0.84:
                tv[k] = min(1.0, tv[k] + 0.32 * (1.0 - d))

        def young(k, d):
            tv[k] = 0.98 if d > 0.7 else 0.7
        stamp(cu, clat, rad * 6, ray, ang=True)
        stamp(cu, clat, rad, young)


def banded(seed, bands, turb_amp, fine_amp, ys_t=1.3):
    """Banded gas-giant atmosphere: band edges are smeared by turbulence."""
    lut = []
    for q in range(721):
        ld = -90 + q * 0.25
        for hi, v, c in bands:
            if ld < hi:
                lut.append((v, c))
                break
        else:
            lut.append(bands[-1][1:])
    turb = fbm_field(seed, 8, 5, 0.55, ys=ys_t)
    fine = fbm_field(seed + 3, 32, 3, 0.5, ys=1.5)
    tv, tc = [0.0] * N_TEX, [0] * N_TEX
    for j in range(TH):
        latd = LATD[j]
        base = j * TW
        for k in range(base, base + TW):
            v, c = lut[int(clamp(latd + (turb[k] - 0.5) * turb_amp + 90, 0, 180) * 4)]
            tv[k] = clamp(v * (1 + (fine[k] - 0.5) * fine_amp), 0.0, 1.0)
            tc[k] = c
    return tv, tc, fine


def tex_sun(seed):
    rnd = random.Random(seed)
    gran = fbm_field(seed, 48, 3, 0.55)
    sup = fbm_field(seed + 1, 8, 3, 0.5)
    tv = [clamp(0.8 + (g - 0.5) * 1.3 + (s - 0.5) * 0.35, 0.0, 1.0) for g, s in zip(gran, sup)]
    spots = set()

    def facula(k, d):
        tv[k] = min(1.0, tv[k] + 0.12 * (1 - d))

    def spot(k, d):
        tv[k] = 0.08 if d < 0.45 else min(tv[k], 0.42)
        spots.add(k)
    for _ in range(6):                                       # sunspot groups
        cu = rnd.random()
        clat = math.radians(rnd.choice((-1, 1)) * rnd.uniform(6, 30))
        group = [(cu + rnd.gauss(0, 0.018), clat + rnd.gauss(0, 0.03), rnd.uniform(0.03, 0.065))
                 for _ in range(rnd.randint(2, 6))]
        for u, la, rad in group:
            stamp(u, la, rad * 3.5, facula)
        for u, la, rad in group:
            stamp(u, la, rad, spot)
    tc = []
    for k, x in enumerate(tv):
        if k in spots:
            tc.append(52 if x < 0.2 else 130)
        else:
            tc.append(230 if x > 0.97 else 228 if x > 0.88 else 221 if x > 0.76 else
                      214 if x > 0.6 else 208 if x > 0.42 else 166)
    return tv, tc


def tex_mercury(seed):
    rnd = random.Random(seed)
    tv = [clamp(0.72 + (x - 0.5) * 0.9, 0.0, 1.0) for x in fbm_field(seed, 6, 6, 0.55)]

    def caloris(k, d):                                       # Caloris basin
        if d > 0.86:
            tv[k] = min(1.0, tv[k] * 1.2 + 0.08)
        elif d < 0.8:
            tv[k] = tv[k] * 0.8 + 0.16
    stamp(0.32, math.radians(30), 0.32, caloris)
    craters(tv, rnd, 600, 0.03, 0.16, rays=7)
    tc = [255 if x > 0.86 else 253 if x > 0.74 else 251 if x > 0.62 else 249 if x > 0.5
          else 246 if x > 0.38 else 243 for x in tv]
    return tv, tc


def tex_venus(seed):
    a = fbm_field(seed, 4, 6, 0.6, ys=1.2)
    b = fbm_field(seed + 1, 10, 4, 0.5, ys=2.0)
    tv, tc = [0.0] * N_TEX, [0] * N_TEX
    for j in range(TH):
        lat = lat_of(j)
        shift = int(0.14 * abs(lat) / HALF_PI * TW)          # cloud "chevrons"
        base = j * TW
        for i in range(TW):
            k = base + i
            v = clamp(0.74 + (a[base + (i + shift) % TW] - 0.5) * 1.15 + (b[k] - 0.5) * 0.4
                      + 0.05 * math.cos(lat * 4), 0.0, 1.0)
            tv[k] = v
            tc[k] = (230 if v > 0.9 else 223 if v > 0.8 else 186 if v > 0.7 else
                     180 if v > 0.6 else 179 if v > 0.5 else 137)
    return tv, tc


def tex_earth(seed):
    rnd = random.Random(seed)
    warp = fbm_field(seed + 7, 3, 3, 0.5)
    land = fbm_field(seed, 4, 7, 0.52)
    ridge = fbm_field(seed + 3, 8, 5, 0.5)
    moist = fbm_field(seed + 9, 5, 4, 0.5)
    cl = fbm_field(seed + 50, 6, 5, 0.55, ys=1.4)
    cl2 = fbm_field(seed + 51, 24, 3, 0.5, ys=1.4)
    n = [0.0] * N_TEX
    for j in range(TH):
        b = j * TW
        for i in range(TW):                                  # warp the coastlines
            n[b + i] = land[b + (i + int((warp[b + i] - 0.5) * 0.3 * TW)) % TW]
    thr = pct(n, 0.71)                                       # ~29% land
    c_hi, c_lo = pct(cl, 0.91), pct(cl, 0.8)
    tv, tc = [0.0] * N_TEX, [0] * N_TEX
    for j in range(TH):
        latd = abs(LATD[j])
        for k in range(j * TW, j * TW + TW):
            x = n[k]
            h = x - thr
            if latd > 77 - 20 * (x - 0.5) or (latd > 68 and h > 0.02):
                v, c = 0.95, 255                             # ice
            elif h > 0:
                rg = 1.0 - abs(2.0 * ridge[k] - 1.0)
                elev = h * 3.0 + rg * rg * 0.5 * min(1.0, h * 15)
                m = moist[k]
                if elev > 0.95:
                    v, c = 0.93, 255                         # snowy peaks
                elif elev > 0.62:
                    v, c = 0.66, 137                         # mountains
                elif (12 < latd < 34 and m < 0.52) or m < 0.36:
                    v, c = (0.82, 186) if m < 0.42 else (0.76, 179)   # deserts
                elif latd > 56:
                    v, c = 0.6, 108                          # taiga and tundra
                elif latd < 14 and m > 0.55:
                    v, c = 0.56, 28                          # jungle
                elif m > 0.5:
                    v, c = 0.6, 64                           # forests
                else:
                    v, c = 0.66, 107                         # grasslands
            else:
                v, c = ((0.64, 38) if h > -0.025 else (0.56, 32) if h > -0.09 else
                        (0.5, 26) if h > -0.17 else (0.46, 25))
            if latd < 80:
                if cl[k] > c_hi:
                    v, c = 0.96, 255
                elif cl[k] > c_lo and cl2[k] > 0.6:
                    v, c = 0.88, 252
            tv[k], tc[k] = v, c
    for _ in range(3):                                       # cyclones
        sgn = rnd.choice((-1, 1))

        def cyc(k, d, a, sgn=sgn):
            if d > 0.1 and math.sin(2 * a * sgn + d * 13) > 0.15 * (1 + d):
                tv[k], tc[k] = 0.95 - d * 0.1, 255
        stamp(rnd.random(), math.radians(sgn * rnd.uniform(14, 32)), rnd.uniform(0.09, 0.14),
              cyc, ang=True)
    return tv, tc


def tex_mars(seed):
    rnd = random.Random(seed)
    n = fbm_field(seed, 4, 7, 0.55)
    det = fbm_field(seed + 2, 24, 3, 0.5)
    t_dark, t_mid, t_hi = pct(n, 0.1), pct(n, 0.25), pct(n, 0.86)
    tv, tc = [0.0] * N_TEX, [0] * N_TEX
    for j in range(TH):
        latd = LATD[j]
        for i in range(TW):
            k = j * TW + i
            x = n[k] + (det[k] - 0.5) * 0.06
            if latd > 78 - (x - 0.5) * 30 or latd < -82 - (x - 0.5) * 16:
                # polar cap with spiral troughs
                if math.sin(3 * (i + 0.5) / TW * TAU + (90 - abs(latd)) * 0.45) > 0.72:
                    tv[k], tc[k] = 0.7, 250
                else:
                    tv[k], tc[k] = 0.96, 255
            elif x < t_dark:
                tv[k], tc[k] = 0.4 + (det[k] - 0.5) * 0.2, 131
            elif x < t_mid:
                tv[k], tc[k] = 0.52, 130
            elif x > t_hi:
                tv[k], tc[k] = 0.86, 180
            else:
                tv[k], tc[k] = 0.7 + (x - t_mid) * 0.5, 173 if det[k] > 0.45 else 166
    oval(8, 0.58, 16, 11, lambda k, e: setter(tv, tc, 0.4, 131 if e < 0.55 else 130)(k))  # Syrtis Major
    stamp(0.69, math.radians(-42), 0.2,                       # Hellas Planitia
          lambda k, d: setter(tv, tc, 0.88 if d < 0.85 else 0.7, 180 if d < 0.85 else 173)(k))
    craters(tv, rnd, 260, 0.035, 0.09)
    for u, la, rad in ((0.13, 18, 0.1), (0.2, 11, 0.045), (0.21, 0, 0.045), (0.22, -9, 0.05)):
        def volcano(k, d):                                   # Olympus Mons and the Tharsis volcanoes
            if d > 0.75:
                tv[k], tc[k] = 0.9, 180
            elif d < 0.22:
                tv[k], tc[k] = 0.45, 130
            else:
                tv[k], tc[k] = 0.62 + 0.25 * d, 173
        stamp(u, math.radians(la), rad, volcano)
    for i in range(int(0.23 * TW), int(0.43 * TW)):          # Valles Marineris
        u = (i + 0.5) / TW
        c_lat = -7 - 3 * math.sin((u - 0.23) * 30)
        for j in range(TH):
            dd = abs(LATD[j] - c_lat)
            if dd < 1.3:
                tv[j * TW + i], tc[j * TW + i] = 0.26, 52
            elif dd < 2.4:
                tv[j * TW + i], tc[j * TW + i] = 0.85, 180
    return tv, tc


def tex_jupiter(seed):
    rnd = random.Random(seed)
    bands = [(-66, 0.46, 102), (-56, 0.56, 138), (-46, 0.68, 144), (-41, 0.8, 187),
             (-37, 0.6, 137), (-34, 0.86, 223), (-27, 0.62, 173), (-19, 0.94, 230),
             (-12, 0.58, 130), (-7, 0.66, 173), (0, 0.92, 223), (7, 0.88, 187), (13, 0.62, 173),
             (18, 0.5, 130), (24, 0.94, 230), (31, 0.6, 137), (35, 0.86, 223), (39, 0.62, 180),
             (46, 0.8, 187), (56, 0.64, 144), (66, 0.56, 138), (91, 0.46, 102)]
    tv, tc, fine = banded(seed, bands, 7.0, 0.35)
    for s in (-1, 1):                                        # equatorial festoons
        for q in range(13):
            oval(s * 7.0, (q + rnd.random() * 0.4) / 13, 4.0, 2.2, setter(tv, tc, 0.42, 66))

    def grs(k, e):                                           # Great Red Spot
        if e > 1.0:
            tv[k], tc[k] = 0.95, 230
        elif e > 0.72:
            tv[k], tc[k] = 0.8, 173
        elif e > 0.3:
            tv[k], tc[k] = 0.74, 167
        else:
            tv[k], tc[k] = 0.8, 174
    oval(-22, 0.62, 13, 6, grs, emax=1.7)
    for q in range(5):                                       # white ovals
        oval(-33.5, 0.1 + q * 0.17 + rnd.gauss(0, 0.01), 2.8, 1.8,
             lambda k, e: setter(tv, tc, 0.97 if e < 0.6 else 0.85, 231 if e < 0.6 else 223)(k))
    for q in range(4):                                       # brown barges
        oval(15.5, rnd.random(), 3.5, 1.2, setter(tv, tc, 0.4, 94))
    for q in range(40):                                      # polar vortices
        la = rnd.choice((-1, 1)) * rnd.uniform(56, 80)
        hh = rnd.uniform(1.0, 2.2)
        oval(la, rnd.random(), hh / math.cos(math.radians(la)), hh,
             setter(tv, tc, 0.62, rnd.choice((144, 102, 138))))
    return tv, tc


def tex_saturn(seed):
    rnd = random.Random(seed)
    bands = [(-74, 0.58, 109), (-60, 0.66, 144), (-46, 0.76, 180), (-34, 0.84, 187),
             (-24, 0.74, 180), (-13, 0.86, 223), (13, 0.95, 230), (24, 0.86, 223), (34, 0.74, 180),
             (46, 0.82, 187), (60, 0.7, 144), (74, 0.64, 138), (91, 0.6, 109)]
    tv, tc, fine = banded(seed, bands, 3.0, 0.18)
    cos30 = math.cos(math.pi / 6)
    for j in range(TH):                                      # north polar hexagon
        if LATD[j] < 74:
            continue
        rr = (90 - LATD[j]) / 14.0
        for i in range(TW):
            a6 = ((i + 0.5) / TW * TAU) % (TAU / 6) - TAU / 12
            hexd = rr * math.cos(a6) / cos30
            k = j * TW + i
            if hexd < 1.0:
                tv[k], tc[k] = (0.42, 23) if rr < 0.2 else (0.62 + (fine[k] - 0.5) * 0.2, 109)
            elif hexd < 1.14:
                tv[k], tc[k] = 0.86, 187
    oval(38, rnd.random(), 3.0, 1.6, setter(tv, tc, 0.97, 231))   # storm
    return tv, tc


def tex_uranus(seed):
    rnd = random.Random(seed)
    bands = [(-62, 0.9, 195), (-40, 0.82, 159), (-15, 0.78, 152), (15, 0.76, 116),
             (40, 0.78, 152), (62, 0.8, 116), (91, 0.84, 152)]
    tv, tc, _ = banded(seed, bands, 5.0, 0.12)
    for _ in range(4):
        oval(rnd.uniform(20, 40), rnd.random(), 3.5, 1.2, setter(tv, tc, 0.97, 231))
    return tv, tc


def tex_neptune(seed):
    bands = [(-70, 0.52, 18), (-58, 0.66, 26), (-48, 0.6, 25), (-38, 0.74, 33), (-26, 0.64, 26),
             (-8, 0.76, 33), (8, 0.7, 27), (26, 0.78, 33), (42, 0.66, 26), (58, 0.62, 25),
             (91, 0.52, 18)]
    tv, tc, fine = banded(seed, bands, 6.0, 0.25)
    for j in range(TH):                                      # cirrus methane clouds
        if 22 < LATD[j] < 34 or -36 < LATD[j] < -30:
            for k in range(j * TW, j * TW + TW):
                if fine[k] > 0.66:
                    tv[k], tc[k] = 0.97, 255 if fine[k] > 0.7 else 153
    oval(-20, 0.4, 12, 6, lambda k, e: setter(tv, tc, 0.3 if e < 0.75 else 0.45,
                                                  17 if e < 0.75 else 18)(k))   # Great Dark Spot
    oval(-26, 0.45, 6, 1.4, setter(tv, tc, 0.98, 255))
    oval(-42, 0.7, 3, 1.5, setter(tv, tc, 0.95, 255))       # the "Scooter"
    oval(-55, 0.15, 5, 2.5, lambda k, e: setter(tv, tc, 0.9 if e < 0.2 else 0.32,
                                                    153 if e < 0.2 else 18)(k))
    return tv, tc


# ── moons: (tv, cls) are colored with the moon's palette, (tv, tc) have fixed colors ──

def tex_luna(seed):
    rnd = random.Random(seed)
    big = fbm_field(seed, 3, 4, 0.5)
    n = fbm_field(seed + 1, 8, 5, 0.55)
    thr = pct(big, 0.3)
    tv = [0.36 + (y - 0.5) * 0.2 if x < thr else clamp(0.7 + (y - 0.5) * 0.6, 0.0, 1.0)
          for x, y in zip(big, n)]                            # maria and highlands
    craters(tv, rnd, 350, 0.035, 0.14, rays=3)
    return tv, [0 if x < 0.45 else 1 if x < 0.7 else 2 for x in tv]


def tex_rock(seed):
    rnd = random.Random(seed)
    tv = [clamp(0.62 + (x - 0.5) * 0.8, 0.0, 1.0) for x in fbm_field(seed, 5, 5, 0.55)]
    craters(tv, rnd, 300, 0.04, 0.18, rays=2)
    return tv, [0 if x < 0.5 else 1 if x < 0.72 else 2 for x in tv]


def tex_ice(seed):
    a = fbm_field(seed, 4, 5, 0.55)
    b = fbm_field(seed + 1, 6, 4, 0.5)
    tv, cls = [], []
    for x, y in zip(a, b):
        if abs((x * 9) % 1.0 - 0.5) < 0.05 or abs((y * 7) % 1.0 - 0.5) < 0.04:
            tv.append(0.55)                                  # cracks in the ice
            cls.append(0)
        else:
            v = clamp(0.82 + (x - 0.5) * 0.4, 0.0, 1.0)
            tv.append(v)
            cls.append(2 if v > 0.84 else 1)
    return tv, cls


def tex_io(seed):
    rnd = random.Random(seed)
    tv = [clamp(0.76 + (x - 0.5) * 0.6, 0.0, 1.0) for x in fbm_field(seed, 5, 5, 0.55)]
    tc = [229 if x > 0.84 else 186 if x > 0.7 else 178 if x > 0.56 else 172 for x in tv]
    for _ in range(28):                                      # volcanoes
        rad = rnd.uniform(0.05, 0.1)
        cu, clat = rnd.random(), math.asin(rnd.uniform(-0.9, 0.9))
        if rnd.random() < 0.35:
            stamp(cu, clat, rad * 2.6,
                  lambda k, d: setter(tv, tc, 0.7, 167)(k) if d > 0.7 else None)
        stamp(cu, clat, rad, setter(tv, tc, 0.3, rnd.choice((52, 94))))
    return tv, tc


def tex_titan(seed):
    n = fbm_field(seed, 4, 3, 0.5, ys=1.2)
    tv, tc = [0.0] * N_TEX, [0] * N_TEX
    for j in range(TH):
        for k in range(j * TW, j * TW + TW):
            v = 0.74 + (n[k] - 0.5) * 0.3 + 0.04 * math.sin(LATD[j] / 9)
            if LATD[j] > 62:
                v -= 0.15                                    # polar haze hood
            tv[k] = v
            tc[k] = 179 if v > 0.78 else 172 if v > 0.66 else 136
    return tv, tc


TEXGEN = {'sun': tex_sun, 'mercury': tex_mercury, 'venus': tex_venus, 'earth': tex_earth,
          'mars': tex_mars, 'jupiter': tex_jupiter, 'saturn': tex_saturn,
          'uranus': tex_uranus, 'neptune': tex_neptune}
MOONGEN = {'luna': tex_luna, 'rock': tex_rock, 'ice': tex_ice, 'io': tex_io, 'titan': tex_titan}
PALETTED = frozenset(('luna', 'rock', 'ice'))


def saturn_profile(seed, NP=700, R0=1.2, R1=2.36):
    """Radial profile of Saturn's rings: (density, color) from R0 to R1 planet radii."""
    rnd = random.Random(seed)
    waves = [(rnd.uniform(30, 420), rnd.random() * TAU, rnd.uniform(0.3, 1.0)) for _ in range(14)]
    wsum = sum(w[2] for w in waves)
    prof = []
    for k in range(NP):
        R = R0 + (R1 - R0) * (k + 0.5) / NP
        n = sum(a * math.sin(f * R + p) for f, p, a in waves) / wsum   # fine ringlets
        if R < 1.239:
            d, c = 0.0, 0
        elif R < 1.527:
            d, c = 0.22 + 0.14 * n, 137                       # C ring
        elif R < 1.64:
            d, c = 0.62 + 0.2 * n, 180                        # inner B ring
        elif R < 1.95:
            d, c = 0.9 + 0.12 * n, (187 if n < 0.1 else 230)  # B ring
        elif R < 2.025:
            d, c = 0.05, 239                                  # Cassini Division
        elif R < 2.27:
            if 2.205 < R < 2.225 or 2.255 < R < 2.265:
                d, c = 0.0, 0                                 # Encke and Keeler gaps
            else:
                d, c = 0.62 + 0.12 * n, 144                   # A ring
        elif 2.305 < R < 2.34:
            d, c = 0.75, 252                                  # F ring
        else:
            d, c = 0.0, 0
        prof.append((clamp(d, 0.0, 1.0), c))
    return prof, R0, NP / (R1 - R0), NP


# ═══════════════════════════ scene objects ════════════════════════════════

class Moon:
    def __init__(self, spec, rnd):
        self.names, self.Rf, self.size, self.period, self.pal, self.kind = spec
        self.color = self.pal[1]
        self.a0 = rnd.random() * TAU
        self.tex = None


class Body:
    def __init__(self, d, idx, rnd):
        self.__dict__.update(d)
        self.idx = idx
        q, r = self.pitch, self.roll
        pole = (math.sin(r) * math.cos(q), -math.cos(r) * math.cos(q), math.sin(q))
        e1 = (math.cos(r), math.sin(r), 0.0)
        e2 = (-math.sin(q) * math.sin(r), math.sin(q) * math.cos(r), math.cos(q))
        self.axes = (pole, e1, e2)
        self.ring_prof = saturn_profile(7) if d.get('wide_ring') else None
        ro = max(f1 for _, f1, _, _ in self.ring) if self.ring else 2.34 if self.ring_prof else 1.0
        self.ext_h = max(self.ext, ro * math.hypot(e1[0], e2[0]))
        self.ext_v = max(self.ext, ro * math.hypot(e1[1], e2[1]))
        self.omega = 0.16 / math.sqrt(self.period) if self.period else 0.0
        self.moons = [Moon(m, rnd) for m in self.moons]
        self.tex = None
        self.a0 = 0.0


class Canvas:
    """Braille canvas: every terminal cell is 2×4 "pixels"."""

    def __init__(self, cw, ch):
        self.cw, self.ch = cw, ch
        self.pw, self.ph = cw * 2, ch * 4
        self.n = cw * ch
        self.col = [0] * self.n
        self.clear()

    def clear(self):
        self.bits = bytearray(self.n)
        self.occ = bytearray(self.n)      # cell covered by a body: hide stars behind it

    def plot_pts(self, pts, dx=0.0, dy=0.0):
        pw, ph, cw = self.pw, self.ph, self.cw
        bits, col = self.bits, self.col
        for x, y, c in pts:
            x += dx
            y += dy
            if 0.0 <= x < pw and 0.0 <= y < ph:
                xi = int(x)
                yi = int(y)
                i = (yi >> 2) * cw + (xi >> 1)
                bits[i] |= BB[yi & 3][xi & 1]
                col[i] = c


# ═══════════════════════════════ palette ══════════════════════════════════

def xterm_rgb(c):
    if c < 16:
        base = [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205),
                (0, 205, 205), (229, 229, 229), (127, 127, 127), (255, 0, 0), (0, 255, 0),
                (255, 255, 0), (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)]
        return base[c]
    if c < 232:
        c -= 16
        lv = [0, 95, 135, 175, 215, 255]
        return lv[c // 36], lv[(c // 6) % 6], lv[c % 6]
    g = 8 + (c - 232) * 10
    return g, g, g


XRGB = [xterm_rgb(c) for c in range(256)]
_LV = (0, 95, 135, 175, 215, 255)


def _cube_q(v):
    return 0 if v < 48 else 1 if v < 115 else min(5, (v - 35) // 40)


def rgb_to_xterm(r, g, b):
    qr, qg, qb = _cube_q(r), _cube_q(g), _cube_q(b)
    dc = (_LV[qr] - r) ** 2 + (_LV[qg] - g) ** 2 + (_LV[qb] - b) ** 2
    avg = (r + g + b) // 3
    gi = 0 if avg < 8 else min(23, (avg - 3) // 10)
    gv = 8 + 10 * gi
    dg = (gv - r) ** 2 + (gv - g) ** 2 + (gv - b) ** 2
    return 232 + gi if dg < dc else 16 + 36 * qr + 6 * qg + qb


RAMP_N = 7
_RAMPS = {}


_HSV = [colorsys.rgb_to_hsv(*(v / 255 for v in XRGB[c])) for c in range(256)]


def nearest_hue(r, g, b, chromatic):
    """Nearest xterm color that keeps the hue: colored never turns gray."""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    best, bd = 250, 1e9
    for c in range(17, 256):
        hc, sc, vc = _HSV[c]
        if (sc < 0.15) if chromatic else (sc > 0.12):
            continue
        dh = abs(h - hc)
        dh = min(dh, 1.0 - dh) * 6.0
        d = 4.0 * (v - vc) ** 2 + 1.2 * (s - sc) ** 2 + (dh * dh * s if chromatic else 0.0)
        if d < bd:
            best, bd = c, d
    return best


def ramp(c):
    """Color c darkened in RAMP_N steps (from shadow to full light)."""
    rp = _RAMPS.get(c)
    if rp is None:
        r, g, b = XRGB[c]
        chromatic = _HSV[c][1] > 0.15
        rp = [nearest_hue(r * f, g * f, b * f, chromatic)
              for f in (0.38 + 0.62 * k / (RAMP_N - 1) for k in range(RAMP_N))]
        rp[-1] = c
        _RAMPS[c] = rp
    return rp


class Palette:
    def __init__(self):
        self.cache = {}
        self.next = 1
        self.ok = curses.has_colors()
        self.bg = -1
        self.n = 0
        if self.ok:
            curses.start_color()
            try:
                curses.use_default_colors()
            except curses.error:
                self.bg = curses.COLOR_BLACK
            self.n = curses.COLORS
            self.maxpairs = curses.COLOR_PAIRS

    def _basic(self, c):
        r, g, b = xterm_rgb(c)
        if max(r, g, b) - min(r, g, b) < 40:
            return curses.COLOR_WHITE
        best, bd = curses.COLOR_WHITE, 1e9
        for idx, (cr, cg, cb) in ((1, (1, 0, 0)), (2, (0, 1, 0)), (3, (1, 1, 0)), (4, (0, 0, 1)),
                                  (5, (1, 0, 1)), (6, (0, 1, 1))):
            m = max(r, g, b)
            d = (r / m - cr) ** 2 + (g / m - cg) ** 2 + (b / m - cb) ** 2
            if d < bd:
                best, bd = idx, d
        return best

    def attr(self, c):
        a = self.cache.get(c)
        if a is not None:
            return a
        a = 0
        if self.ok and c is not None:
            fg = c if self.n >= 256 else self._basic(c)
            if self.next < self.maxpairs:
                curses.init_pair(self.next, fg, self.bg)
                a = curses.color_pair(self.next)
                self.next += 1
            else:
                r, g, b = XRGB[c]
                best = min((k for k in self.cache if k is not None),
                           key=lambda k: sum((u - v) ** 2 for u, v in zip(XRGB[k], (r, g, b))),
                           default=None)
                a = self.cache.get(best, 0) if best is not None else 0
            if self.n < 256 and sum(xterm_rgb(c)) > 600:
                a |= curses.A_BOLD
        self.cache[c] = a
        return a


# ═══════════════════════════════ camera ═══════════════════════════════════

def vanwijk(c0, w0, c1, w1, rho=1.4):
    """Optimal zoom-and-pan path (van Wijk & Nuij, 2003).
    Returns the path length S and a function e∈[0,1] → (centre, view width)."""
    ux, uy = c1[0] - c0[0], c1[1] - c0[1]
    u1 = math.hypot(ux, uy)
    if u1 < 1e-6 * max(w0, w1):
        k = math.log(w1 / w0)
        return abs(k) / rho, (lambda e: ((c0[0] + ux * e, c0[1] + uy * e), w0 * math.exp(k * e)))
    r2 = rho * rho
    b0 = (w1 * w1 - w0 * w0 + r2 * r2 * u1 * u1) / (2 * w0 * r2 * u1)
    b1 = (w1 * w1 - w0 * w0 - r2 * r2 * u1 * u1) / (2 * w1 * r2 * u1)
    r0, r1 = -math.asinh(b0), -math.asinh(b1)
    S = (r1 - r0) / rho
    ch0, sh0 = math.cosh(r0), math.sinh(r0)

    def at(e):
        s = e * S
        u = w0 / r2 * (ch0 * math.tanh(rho * s + r0) - sh0)
        w = w0 * ch0 / math.cosh(rho * s + r0)
        k = u / u1
        return (c0[0] + ux * k, c0[1] + uy * k), w
    return S, at


# ═══════════════════════════════ application ══════════════════════════════

class App:
    def __init__(self, scr, pal, flush, lang='en'):
        self.scr, self.pal, self.flush = scr, pal, flush
        self.lang = lang if lang in LANGS else 'en'
        rnd = random.Random(2026)
        self.bodies = [Body(d, i, rnd) for i, d in enumerate(BODIES)]
        days = (time.time() - J2000_UNIX) / 86400.0
        for b in self.bodies:
            if b.R:
                b.a0 = math.radians((b.L0 + b.rate * days) % 360.0)
        self.asteroids = []
        for _ in range(230):
            a = rnd.uniform(2.2, 3.3)                         # AU
            self.asteroids.append((41 + (a - 1.6) / 1.9 * 18 + rnd.gauss(0, 0.6),
                                   rnd.random() * TAU, 0.16 / math.sqrt(a ** 1.5)))
        streamers = [rnd.random() * TAU for _ in range(7)]
        self.corona = []
        for _ in range(900):
            ang = rnd.random() * TAU if rnd.random() < 0.6 else rnd.choice(streamers) + rnd.gauss(0, 0.07)
            self.corona.append((ang, rnd.random(), rnd.uniform(0.08, 0.22), rnd.random() * TAU))
        self.comet = dict(a=86.0, e=0.86, w=2.3, T=170.0, M0=-0.55)
        self.proms = [(rnd.random() * TAU, rnd.uniform(0.12, 0.22), rnd.uniform(0.08, 0.16),
                       rnd.random() * TAU) for _ in range(4)]
        self.n_objects = (len(self.bodies) + sum(len(b.moons) for b in self.bodies)
                          + len(self.asteroids) + 2)

        self.sel = 3
        self.target = 3
        self.mode = 'overview'           # overview | flying | detail
        self.trans = None
        self.t = 0.0
        self.speed_i = SPEEDS.index(1.0)
        self.paused = False
        self.user_zoom = 1.0
        self.detail_zoom = 1.0
        self.panel_on = True
        self.clean = False               # clean view: no frame, panels or labels
        self.clean_t = -1e9
        self.scroll = 0
        self.arrive = 0.0
        self.fps = float(FPS_TARGET)
        self.ring_cache = {}
        self.geo_cache = OrderedDict()
        self.panel_cache = {}
        self.labels = []
        self.P = []
        self.last_click = 0.0
        self.work = []
        self.lite = False
        self.resize()
        self.cam = list(self.overview_cam())

    # ─────────────────────────── setup ────────────────────────────────

    def T(self, b):
        """Texts about body b in the current language."""
        return TEXT[b.key][self.lang]

    def U(self, key):
        """Interface string in the current language."""
        return UI[self.lang][key]

    def name(self, b):
        return self.T(b)['name'].upper()

    def generate(self, progress=None):
        steps = [(self.name(b), b) for b in self.bodies] + [(self.U('moons'), None)]
        for name, b in steps:
            if progress:
                progress(name)
            if b is not None:
                b.tex = TEXGEN[b.key](1000 + b.idx * 17)
                continue
            base = {}
            for pb in self.bodies:
                for m in pb.moons:
                    if m.kind not in base:
                        base[m.kind] = MOONGEN[m.kind](300 + len(base) * 11)
                    tv, aux = base[m.kind]
                    m.tex = (tv, [m.pal[c] for c in aux]) if m.kind in PALETTED else (tv, aux)
        lift = lambda tv: [v * 0.92 + 0.1 if v < 0.98 else 1.0 for v in tv]
        for b in self.bodies:                                # denser dots on the lit side
            if b.R:
                b.tex = (lift(b.tex[0]), b.tex[1])
            for m in b.moons:
                m.tex = (lift(m.tex[0]), m.tex[1])
        colors = {221}                                       # precompute shading ramps
        for b in self.bodies:
            colors.update(b.tex[1])
            colors.update(c for _, c in (b.ring_prof[0] if b.ring_prof else ()))
            colors.update(c for m in b.moons for c in m.tex[1])
            if b.atm:
                colors.add(b.atm)
        for c in colors:
            ramp(c)

    def boot(self):
        A = self.pal.attr
        H, W = self.scr.getmaxyx()
        self.scr.erase()
        x = max(1, W // 2 - 22)
        y = max(0, H // 2 - 8)
        self.put(y, x, 'ORBIT / TERMINAL UNIVERSE', A(255) | curses.A_BOLD)
        self.put(y + 1, x, self.U('boot'), A(244))
        row = [y + 3]

        def progress(name):
            if row[0] > y + 3:
                self.put(row[0] - 1, x + 34, 'OK', A(80))
            self.put(row[0], x, self.U('terrain').format(f'{name:<9}'), A(250))
            self.put(row[0], x + 30, '…', A(244))
            self.flush()
            row[0] += 1

        self.generate(progress)
        self.put(row[0] - 1, x + 34, 'OK', A(80))
        self.put(row[0] + 1, x, self.U('ephem').format(time.strftime(self.U('date'))), A(250))
        self.put(row[0] + 1, x + 34, 'OK', A(80))
        self.flush()
        time.sleep(0.35)
        self.scr.erase()

    def resize(self):
        self.H, self.W = self.scr.getmaxyx()
        self.too_small = self.W < 64 or self.H < 20
        if self.clean:                   # the scene takes the whole window
            self.ox, self.oy = 0, 0
            self.cw, self.ch = max(1, self.W), max(1, self.H)
        else:                            # inside the frame, below the header
            self.ox, self.oy = 1, 3
            self.cw, self.ch = max(1, self.W - 2), max(1, self.H - 8)
        self.cv = Canvas(self.cw, self.ch)
        pw, ph = self.cv.pw, self.cv.ph
        self.base_ppu = min(pw * 0.47 / 128.0, ph * 0.45 / (128.0 * SIN_E))
        self.panel_w = int(clamp(self.cw * 0.38, 34, 58))
        self.ring_cache.clear()
        self.geo_cache.clear()
        self.panel_cache.clear()
        rnd = random.Random(42)
        self.stars = []
        for _ in range(self.W * self.H // 24):           # in screen cells: stay put on toggle
            p = rnd.random()
            if p < 0.48:
                ch, c = '.', 240
            elif p < 0.70:
                ch, c = '·', 244
            elif p < 0.85:
                ch, c = '*', 250
            else:
                ch, c = '+', 80 if rnd.random() < 0.6 else 30
            self.stars.append((rnd.random() * self.W, rnd.random() * self.H,
                               rnd.choice((0.008, 0.02, 0.045)), ch, c,
                               rnd.random() * TAU, rnd.uniform(0.4, 2.2)))

    # ─────────────────────────── geometry ─────────────────────────────

    def body_world(self, b):
        if not b.R:
            return 0.0, 0.0
        a = b.a0 + b.omega * self.t
        return b.R * math.cos(a), -b.R * math.sin(a)

    def overview_cam(self):
        return (0.0, 0.0, 0.5, 0.5, self.base_ppu * self.user_zoom)

    def detail_cam(self, idx):
        b = self.bodies[idx]
        X, Y = self.body_world(b)
        pw, ph = self.cv.pw, self.cv.ph
        avail = (self.cw - (self.panel_w if self.panel_on and not self.clean else 0)) * 2
        rt = min(ph * 0.40 / b.ext_v, avail * 0.46 / b.ext_h) * self.detail_zoom
        return (X, Y * SIN_E, avail * 0.5 / pw, 0.5, rt / b.r)

    def light(self, b, X, Y, r):
        if not b.R:
            return (0.0, 0.0, 1.0)
        n = math.hypot(X, Y) or 1.0
        lx, ly, lz = -X / n, -Y * SIN_E / n, -Y * COS_E / n
        f = clamp((r - 8.0) / 40.0, 0.0, 1.0)            # close up — a fixed "studio" key light
        if f > 0:
            k = KEY_LIGHT
            lx, ly, lz = lerp(lx, k[0], f), lerp(ly, k[1], f), lerp(lz, k[2], f)
        m = math.sqrt(lx * lx + ly * ly + lz * lz)
        return (lx / m, ly / m, lz / m)

    def comet_world(self):
        c = self.comet
        e = c['e']
        M = c['M0'] + TAU * self.t / c['T']
        E = M
        for _ in range(8):
            E -= (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
        x = c['a'] * (math.cos(E) - e)
        y = c['a'] * math.sqrt(1 - e * e) * math.sin(E)
        cw, sw = math.cos(c['w']), math.sin(c['w'])
        return x * cw - y * sw, x * sw + y * cw

    # ─────────────────────────── controls ─────────────────────────────

    def fly(self, dest, idx, now):
        tg = self.detail_cam(idx) if dest == 'detail' else self.overview_cam()
        pw = self.cv.pw
        S, _ = vanwijk((self.cam[0], self.cam[1]), pw / self.cam[4], (tg[0], tg[1]), pw / tg[4])
        self.trans = dict(dest=dest, idx=idx, c0=(self.cam[0], self.cam[1]), w0=pw / self.cam[4],
                          a0=(self.cam[2], self.cam[3]), t0=now,
                          dur=clamp(0.8 + 0.42 * abs(S), 1.1, 2.8))
        self.mode = 'flying'
        if dest == 'detail':
            self.target = idx
            self.sel = idx
        self.scroll = 0

    def go(self, idx, now):
        self.sel = idx
        if not (self.mode == 'detail' and self.target == idx):
            self.fly('detail', idx, now)

    def heading_to_planet(self):
        return self.mode == 'detail' or (self.trans is not None and self.trans['dest'] == 'detail')

    def step_sel(self, d, now):
        idx = (self.sel + d) % len(self.bodies)
        if self.heading_to_planet():
            self.go(idx, now)
        else:
            self.sel = idx

    def zoom(self, k):
        if self.heading_to_planet():
            self.detail_zoom = clamp(self.detail_zoom * (1.15 if k > 0 else 1 / 1.15), 0.55, 1.9)
        else:
            self.user_zoom = clamp(self.user_zoom * (1.25 if k > 0 else 0.8), 0.5, 6.0)

    def handle_key(self, k, now):
        if isinstance(k, str):            # Cyrillic letters: same keys on a Russian layout
            if k in 'qQйЙ':
                return False
            if k == ' ':
                self.paused = not self.paused
            elif k in '\n\r':
                self.enter(now)
            elif k in '\x1b\x7f\b':
                self.back(now)
            elif k in '+=':
                self.zoom(1)
            elif k in '-_':
                self.zoom(-1)
            elif k in '[<,бБх':
                self.speed_i = max(0, self.speed_i - 1)
            elif k in ']>.юЮъ':
                self.speed_i = min(len(SPEEDS) - 1, self.speed_i + 1)
            elif k in 'iIшШ':
                if self.clean:                               # bring the interface back with the panel
                    self.toggle_clean(now)
                    self.panel_on = True
                else:
                    self.panel_on = not self.panel_on
            elif k in 'hHрР\t':
                self.toggle_clean(now)
            elif k in 'aAфФ':
                self.step_sel(-1, now)
            elif k in 'dDвВ':
                self.step_sel(1, now)
            elif k in 'lLдД':
                self.lang = LANGS[(LANGS.index(self.lang) + 1) % len(LANGS)]
            elif k.isdigit() and int(k) < len(self.bodies):
                self.go(int(k), now)
            return True
        if k == curses.KEY_RESIZE:
            try:
                curses.update_lines_cols()
            except Exception:
                pass
            self.resize()
            self.scr.clear()
        elif k == curses.KEY_LEFT:
            self.step_sel(-1, now)
        elif k == curses.KEY_RIGHT:
            self.step_sel(1, now)
        elif k == curses.KEY_UP:
            if self.mode == 'detail':
                self.scroll = max(0, self.scroll - 1)
        elif k == curses.KEY_DOWN:
            if self.mode == 'detail':
                self.scroll += 1
            else:
                self.enter(now)
        elif k == curses.KEY_ENTER:
            self.enter(now)
        elif k in (curses.KEY_BACKSPACE, curses.KEY_DC):
            self.back(now)
        elif k == curses.KEY_MOUSE:
            self.mouse(now)
        return True

    def toggle_clean(self, now):
        self.clean = not self.clean
        self.clean_t = now
        self.resize()                    # the camera glides to the new framing by itself
        self.scr.erase()

    def show_panel(self):
        return self.mode == 'detail' and self.panel_on and not self.clean

    def enter(self, now):
        if self.mode == 'detail':
            self.arrive = -1e9                               # reveal the whole text
        elif not (self.trans and self.trans['dest'] == 'detail'):
            self.fly('detail', self.sel, now)

    def back(self, now):
        if self.heading_to_planet():
            self.fly('overview', self.sel, now)

    def mouse(self, now):
        try:
            _, mx, my, _, bs = curses.getmouse()
        except curses.error:
            return
        if bs & getattr(curses, 'BUTTON4_PRESSED', 0x80000):
            self.zoom(1)
            return
        if bs & getattr(curses, 'BUTTON5_PRESSED', 0x200000):
            self.zoom(-1)
            return
        if not bs & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED):
            return
        if now - self.last_click < 0.2:
            return
        self.last_click = now
        vx, vy = mx - self.ox, my - self.oy
        if not (0 <= vx < self.cw and 0 <= vy < self.ch):
            return
        if self.show_panel() and vx >= self.cw - self.panel_w:
            return
        px, py = vx * 2 + 1, vy * 4 + 2
        best, bd = None, 1e9
        for i, (_, _, sx, sy, r) in enumerate(self.P):
            d = math.hypot(px - sx, py - sy)
            if d < max(r + 6, 9) and d - r < bd:
                best, bd = i, d - r
        if best is not None:
            self.go(best, now)

    # ─────────────────────────── simulation ───────────────────────────

    def update(self, dt, now):
        if not self.paused:
            self.t += dt * SPEEDS[self.speed_i]
        cam = self.cam
        pw = self.cv.pw
        tr = self.trans
        if tr:
            tg = self.detail_cam(tr['idx']) if tr['dest'] == 'detail' else self.overview_cam()
            f = clamp((now - tr['t0']) / tr['dur'], 0.0, 1.0)
            e = smootherstep(f)
            self.lite = True
            _, at = vanwijk(tr['c0'], tr['w0'], (tg[0], tg[1]), pw / tg[4])
            (fx, fy), w = at(e)
            cam[:] = [fx, fy, lerp(tr['a0'][0], tg[2], e), lerp(tr['a0'][1], tg[3], e), pw / w]
            if f >= 1.0:
                cam[:] = list(tg)
                self.mode = tr['dest']
                self.trans = None
                self.arrive = now
                self.lite = False
            return
        tg = self.detail_cam(self.target) if self.mode == 'detail' else self.overview_cam()
        k = 1.0 - math.exp(-dt * 7.0)
        if self.mode == 'detail':
            cam[0], cam[1] = tg[0], tg[1]
        else:
            cam[0] += (tg[0] - cam[0]) * k
            cam[1] += (tg[1] - cam[1]) * k
        cam[2] += (tg[2] - cam[2]) * k
        cam[3] += (tg[3] - cam[3]) * k
        cam[4] *= math.exp((math.log(tg[4]) - math.log(cam[4])) * k)

    # ─────────────────────────── drawing bodies ───────────────────────

    def cache_get(self, key):
        g = self.geo_cache.get(key)
        if g is not None:
            self.geo_cache.move_to_end(key)
        return g

    def cache_put(self, key, g):
        self.geo_cache[key] = g
        while len(self.geo_cache) > 14:
            self.geo_cache.popitem(last=False)
        return g

    def sphere_geo(self, cx, cy, r, axes, dither, lite=False):
        """Geometry of the visible disc: normal, texture coordinates and dither
        threshold for every Braille dot. Cached while the camera is still.
        lite — during flights: normal and texture are sampled per cell, not per dot."""
        qx = round(cx * 2) * 0.5
        qy = round(cy * 2) * 0.5
        key = ('s', qx, qy, round(r * 8), id(axes), dither, lite)
        g = self.cache_get(key)
        if g is not None:
            return g
        cv = self.cv
        pw, ph, cw = cv.pw, cv.ph, cv.cw
        (ppx, ppy, ppz), (e1x, e1y, e1z), (e2x, e2y, e2z) = axes
        TT = THRESH[dither]
        inv = 1.0 / r
        r2 = r * r
        asin, atan2, sqrt = math.asin, math.atan2, math.sqrt
        latk = TH / math.pi
        lonk = TW / TAU
        PI = math.pi
        pix = []
        cells = {}
        samp = {}
        for py in range(max(0, int(math.floor(qy - r))), min(ph - 1, int(qy + r)) + 1):
            dy = py + 0.5 - qy
            h = r2 - dy * dy
            if h <= 0.0:
                continue
            hw = sqrt(h)
            x0 = max(0, math.ceil(qx - hw - 0.5))
            x1 = min(pw - 1, math.floor(qx + hw - 0.5))
            if x0 > x1:
                continue
            ny = dy * inv
            rowi = (py >> 2) * cw
            br = BB[py & 3]
            tr = TT[py & 7]
            for px in range(x0, x1 + 1):
                i = rowi + (px >> 1)
                bit = br[px & 1]
                cells[i] = cells.get(i, 0) | bit
                if lite:
                    sm = samp.get(i)
                    if sm is None:
                        sm = samp[i] = self._cell_sample(i, qx, qy, inv, axes)
                    pix.append((i, bit) + sm + (tr[px & 7],))
                    continue
                nx = (px + 0.5 - qx) * inv
                d2 = nx * nx + ny * ny
                nz = sqrt(1.0 - d2) if d2 < 1.0 else 0.0
                sl = nx * ppx + ny * ppy + nz * ppz
                sl = 1.0 if sl > 1.0 else -1.0 if sl < -1.0 else sl
                row = int((HALF_PI - asin(sl)) * latk)
                if row >= TH:
                    row = TH - 1
                lon = (atan2(nx * e1x + ny * e1y + nz * e1z, nx * e2x + ny * e2y + nz * e2z) + PI) * lonk
                pix.append((i, bit, nx, ny, nz, row * TW, lon, tr[px & 7]))
        cl = [(i, m) + (samp.get(i) or self._cell_sample(i, qx, qy, inv, axes))
              for i, m in cells.items()]
        return self.cache_put(key, (cl, pix))

    def _cell_sample(self, i, qx, qy, inv, axes):
        """Normal and texture coordinates at the cell centre (clamped inside the disc)."""
        (ppx, ppy, ppz), (e1x, e1y, e1z), (e2x, e2y, e2z) = axes
        cw = self.cv.cw
        sqrt = math.sqrt
        nx = ((i % cw) * 2 + 1 - qx) * inv
        ny = ((i // cw) * 4 + 2 - qy) * inv
        d2 = nx * nx + ny * ny
        if d2 >= 0.995:
            f = 0.9975 / sqrt(d2)
            nx *= f
            ny *= f
            nz = 0.0707
        else:
            nz = sqrt(1.0 - d2)
        sl = nx * ppx + ny * ppy + nz * ppz
        sl = 1.0 if sl > 1.0 else -1.0 if sl < -1.0 else sl
        row = min(TH - 1, int((HALF_PI - math.asin(sl)) * (TH / math.pi)))
        lon = (math.atan2(nx * e1x + ny * e1y + nz * e1z, nx * e2x + ny * e2y + nz * e2z)
               + math.pi) * (TW / TAU)
        return (nx, ny, nz, row * TW, lon)

    def draw_sphere(self, cx, cy, r, tex, axes, dither, L, phase, color,
                    amb=0.07, emissive=False, lights=False, tick=0, rshadow=None):
        cv = self.cv
        if cx + r < 0 or cx - r >= cv.pw or cy + r < 0 or cy - r >= cv.ph:
            return
        bits, col, occ = cv.bits, cv.col, cv.occ
        if r < 1.0 or tex is None:                  # very far away — a single dot
            px, py = int(cx), int(cy)
            if 0 <= px < cv.pw and 0 <= py < cv.ph:
                i = (py >> 2) * cv.cw + (px >> 1)
                bits[i] |= BB[py & 3][px & 1]
                col[i] = color
                occ[i] = 1
            return
        solid = r < 7.0
        cl, pix = self.sphere_geo(cx, cy, r, axes, dither, lite=self.lite and r > 24)
        tv, tc = tex
        Lx, Ly, Lz = L[0] * 1.25, L[1] * 1.25, L[2] * 1.25   # the disc centre is fully lit
        amb1 = 1.0 - amb
        sh = (phase % TAU) * (TW / TAU)
        RN = RAMP_N - 0.001
        RAMPS = _RAMPS
        sqrt = math.sqrt
        if rshadow:
            (Px, Py, Pz), (prof, R0, kp, NP) = rshadow
            lp = Lx * Px + Ly * Py + Lz * Pz
            if abs(lp) < 1e-3:
                rshadow = None
            else:
                inv_lp = -1.0 / lp
                R0s, R1s = R0 * R0, (R0 + NP / kp) ** 2

        # 1) cell colors: surface hue darkened by lighting
        for i, m, nx, ny, nz, row, lon in cl:
            bits[i] &= 255 ^ m
            occ[i] = 1
            c = tc[row + int(lon + sh) % TW]
            if emissive:
                lf = 0.3 + 0.7 * nz                 # limb darkening
            else:
                d = nx * Lx + ny * Ly + nz * Lz
                lf = amb + amb1 * d if d > 0.0 else amb
                if solid:
                    lf = 0.45 + 0.6 * lf
                elif rshadow and d > 0.0:
                    t = (nx * Px + ny * Py + nz * Pz) * inv_lp
                    if t > 0.0:
                        hx, hy, hz = nx + t * Lx, ny + t * Ly, nz + t * Lz
                        R2 = hx * hx + hy * hy + hz * hz
                        if R0s < R2 < R1s:
                            lf = amb + (lf - amb) * (1.0 - 0.85 * prof[int((sqrt(R2) - R0) * kp)][0])
            rp = RAMPS.get(c) or ramp(c)
            lf = 0.4 + 1.1 * lf if emissive or solid or d > 0.0 else 0.25
            col[i] = rp[int((lf if lf < 1.0 else 1.0) * RN)]

        # 2) dots: each with its own brightness and dither threshold
        if solid:
            for i, bit, nx, ny, nz, row, lon, thr in pix:
                if emissive or nx * Lx + ny * Ly + nz * Lz > -0.06 or thr < 0.42:
                    bits[i] |= bit
            return
        if emissive:
            boost = clamp((24.0 - r) / 40.0, 0.0, 0.4)
            for i, bit, nx, ny, nz, row, lon, thr in pix:
                if (tv[row + int(lon + sh) % TW] * (0.42 + 0.58 * nz) + boost
                        + ((i * 7919 + bit * 131 + tick * 104729) % 97) * 0.002 - 0.1) > thr:
                    bits[i] |= bit
            return
        if rshadow:
            for i, bit, nx, ny, nz, row, lon, thr in pix:
                d = nx * Lx + ny * Ly + nz * Lz
                if d > 0.0:
                    lf = amb + amb1 * d
                    t = (nx * Px + ny * Py + nz * Pz) * inv_lp
                    if t > 0.0:                     # ring shadow on the globe
                        hx, hy, hz = nx + t * Lx, ny + t * Ly, nz + t * Lz
                        R2 = hx * hx + hy * hy + hz * hz
                        if R0s < R2 < R1s:
                            lf = amb + (lf - amb) * (1.0 - 0.85 * prof[int((sqrt(R2) - R0) * kp)][0])
                else:
                    lf = amb
                if tv[row + int(lon + sh) % TW] * lf > thr:
                    bits[i] |= bit
            return
        for i, bit, nx, ny, nz, row, lon, thr in pix:
            ti = row + int(lon + sh) % TW
            d = nx * Lx + ny * Ly + nz * Lz
            if d > 0.0:
                if tv[ti] * (amb + amb1 * d) > thr:
                    bits[i] |= bit
            elif tv[ti] * amb > thr:
                bits[i] |= bit
            elif lights and d < -0.12 and tc[ti] in LAND and (ti * 2654435761 >> 11) % 3 == 0:
                bits[i] |= bit                      # city lights at night
                col[i] = 221

    def ring_geo(self, b, cx, cy, r, L):
        """Saturn's rings per dot: radial profile and the planet's shadow on the rings."""
        qx = round(cx * 2) * 0.5
        qy = round(cy * 2) * 0.5
        lite = self.lite
        key = ('r', b.idx, qx, qy, round(r * 8), round(L[0] * 25), round(L[1] * 25), round(L[2] * 25), lite)
        g = self.cache_get(key)
        if g is not None:
            return g
        cv = self.cv
        pw, ph, cw = cv.pw, cv.ph, cv.cw
        prof, R0, kp, NP = b.ring_prof
        R1 = R0 + NP / kp
        (Px, Py, Pz), (e1x, e1y, _), (e2x, e2y, e2z) = b.axes
        det = e1x * e2y - e2x * e1y
        dd = det * det
        A = (e1y * e1y + e2y * e2y) / dd
        B = -(e1x * e1y + e2x * e2y) / dd
        C = (e1x * e1x + e2x * e2x) / dd
        Lx, Ly, Lz = L
        rl = 0.55 + 0.45 * abs(Lx * Px + Ly * Py + Lz * Pz)
        Ro, Ri = R1 * r, R0 * r
        ext_v = Ro * math.hypot(e1y, e2y)
        TT = THRESH['bayer']
        RN = RAMP_N - 0.001
        inv_r = 1.0 / r
        gap2 = (1.0 + 1.5 / r) ** 2
        back, front = [], []
        samp = {}
        sqrt = math.sqrt
        for py in range(max(0, int(qy - ext_v) - 1), min(ph - 1, int(qy + ext_v) + 1) + 1):
            y = py + 0.5 - qy
            disc = B * B * y * y - A * (C * y * y - Ro * Ro)
            if disc <= 0.0:
                continue
            s = sqrt(disc)
            px0 = max(0, math.ceil(qx + (-B * y - s) / A - 0.5))
            px1 = min(pw - 1, math.floor(qx + (-B * y + s) / A - 0.5))
            di = B * B * y * y - A * (C * y * y - Ri * Ri)
            if di > 0.0:
                si = sqrt(di)
                xia, xib = (-B * y - si) / A, (-B * y + si) / A
            else:
                xia = xib = 0.0
            rowi = (py >> 2) * cw
            br = BB[py & 3]
            tr = TT[py & 7]
            yr = y * inv_r
            for px in range(px0, px1 + 1):
                x = px + 0.5 - qx
                if xia < x < xib:
                    continue
                if lite:                            # in flight: one sample per cell
                    i = rowi + (px >> 1)
                    hit = samp.get(i)
                    if hit is None:
                        x = (px | 1) - qx
                        y = (py | 3) - 1 - qy
                        hit = samp[i] = self._ring_sample(x, y, r, det, e1x, e1y, e2x, e2y, e2z,
                                                          prof, R0, kp, NP, L, rl, gap2)
                        y = py + 0.5 - qy
                    if hit and hit[0] > tr[px & 7]:
                        (front if hit[1] else back).append((i, br[px & 1], hit[2]))
                    continue
                q = (-e1y * x + e1x * y) / det
                p = (e2y * x - e2x * y) / det
                k = int((sqrt(p * p + q * q) * inv_r - R0) * kp)
                if k < 0 or k >= NP:
                    continue
                dens, c = prof[k]
                if dens <= 0.0:
                    continue
                xr = x * inv_r
                zr = q * e2z * inv_r
                if zr <= 0.0 and xr * xr + yr * yr < gap2:
                    continue                        # behind the planet's disc
                lit = rl
                pl = xr * Lx + yr * Ly + zr * Lz
                if pl < 0.0 and xr * xr + yr * yr + zr * zr - pl * pl < 1.0:
                    lit *= 0.12                     # planet's shadow on the rings
                if dens * lit > tr[px & 7]:
                    rp = _RAMPS.get(c) or ramp(c)
                    (front if zr > 0.0 else back).append((rowi + (px >> 1), br[px & 1], rp[int(lit * RN)]))
        return self.cache_put(key, (back, front))

    def _ring_sample(self, x, y, r, det, e1x, e1y, e2x, e2y, e2z, prof, R0, kp, NP, L, rl, gap2):
        q = (-e1y * x + e1x * y) / det
        p = (e2y * x - e2x * y) / det
        k = int((math.sqrt(p * p + q * q) / r - R0) * kp)
        if k < 0 or k >= NP or prof[k][0] <= 0.0:
            return None
        dens, c = prof[k]
        xr, yr, zr = x / r, y / r, q * e2z / r
        if zr <= 0.0 and xr * xr + yr * yr < gap2:
            return None
        lit = rl
        pl = xr * L[0] + yr * L[1] + zr * L[2]
        if pl < 0.0 and xr * xr + yr * yr + zr * zr - pl * pl < 1.0:
            lit *= 0.12
        return dens * lit, zr > 0.0, ramp(c)[int(lit * (RAMP_N - 0.001))]

    def plot_cells(self, pts):
        bits, col = self.cv.bits, self.cv.col
        for i, bit, c in pts:
            bits[i] |= bit
            col[i] = c

    def ring_points(self, b, r, with_orbits):
        """Thin rings (Uranus, Neptune) and dotted moon orbits."""
        key = (b.idx, int(r * 4), with_orbits)
        hit = self.ring_cache.get(key)
        if hit:
            return hit
        back, front = [], []
        _, (e1x, e1y, _), (e2x, e2y, e2z) = b.axes

        def ellipse(R, gap, color, dash=False, offs=0.0):
            n = max(8, int(TAU * R / gap))
            for s in range(n):
                if dash and s % 6 >= 4:
                    continue
                a = TAU * s / n + offs
                ca, sa = math.cos(a), math.sin(a)
                (front if sa * e2z > 0 else back).append(
                    (R * (ca * e1x + sa * e2x), R * (ca * e1y + sa * e2y), color))

        for f0, f1, style, color in (b.ring or ()):
            width = (f1 - f0) * r
            nl = max(1, int(width / 2.2 + 0.5))
            for li in range(nl):
                R = (f0 + (f1 - f0) * (li + 0.5) / nl) * r
                ellipse(R, RING_GAP[style], color, style == 'dash', li * 0.37)
        if with_orbits:
            for m in b.moons:
                ellipse(m.Rf * r, 6.0, 237)
        gap2 = (r + 2.0) ** 2
        back = [p for p in back if p[0] * p[0] + p[1] * p[1] > gap2]
        r2 = r * r
        front = [p for p in front if p[2] != 237 or p[0] * p[0] + p[1] * p[1] > r2]
        if len(self.ring_cache) > 48:
            self.ring_cache.clear()
        self.ring_cache[key] = (back, front)
        return back, front

    def draw_corona(self, sx, sy, r, faint=False):
        pts = []
        t = self.t
        spread = 0.1 if faint else 0.6 if r > 30 else 0.3
        for k in range(min(len(self.corona), int(r * (2 if faint else 7 if r > 30 else 3)) + 8)):
            ang, d0, sp, wob = self.corona[k]
            f = (d0 + t * sp) % 1.0
            d = r * (1.03 + spread * f * f)
            a = ang + 0.04 * math.sin(t * 0.7 + wob)
            c = 226 if f < 0.18 else 220 if f < 0.4 else 214 if f < 0.65 else 208 if f < 0.85 else 130
            pts.append((sx + math.cos(a) * d, sy + math.sin(a) * d, c))
        self.cv.plot_pts(pts)

    def draw_prominences(self, sx, sy, r):
        """Prominences — fiery arcs above the solar limb."""
        pts = []
        for a0, w, h, ph in self.proms:
            fl = 0.85 + 0.15 * math.sin(self.t * 0.9 + ph)
            n = int((w + 2 * h) * r * 1.4) + 8
            for lay, c in ((1.0, 196), (0.86, 202), (0.72, 208)):
                for k in range(n):
                    t = k / (n - 1)
                    ang = a0 + w * (t - 0.5)
                    rr = r * (1.0 + h * fl * lay * math.sin(math.pi * t))
                    pts.append((sx + math.cos(ang) * rr, sy + math.sin(ang) * rr, c))
        self.cv.plot_pts(pts)

    def draw_limb(self, cx, cy, r, L, atm):
        """Dashed limb on the night side and the glowing atmosphere rim."""
        Lx, Ly, _ = L
        n = int(TAU * (r + 3))
        pts = []
        rp = ramp(atm) if atm else None
        for k in range(n):
            a = TAU * k / n
            ca, sa = math.cos(a), math.sin(a)
            dl = ca * Lx + sa * Ly
            if dl < 0.2 and (k // 3) % 2 == 0:
                pts.append((cx + ca * (r - 0.4), cy + sa * (r - 0.4), 242))
            if atm:
                lit = dl + 0.35
                if lit > 0.0:
                    if k % 2 == 0 or lit > 0.8:
                        pts.append((cx + ca * (r + 1.1), cy + sa * (r + 1.1), atm))
                    if k % 3 == 0 and lit > 0.45:
                        pts.append((cx + ca * (r + 2.6), cy + sa * (r + 2.6), rp[3]))
        self.cv.plot_pts(pts)

    def label(self, row, col, text, color, bold=False, prio=5):
        a = self.pal.attr(color) | (curses.A_BOLD if bold else 0)
        self.labels.append((prio, int(math.floor(row)), int(math.floor(col)), text, a))

    def flush_labels(self):
        """Draw labels by priority; skip those overlapping already drawn ones."""
        taken = set()
        for prio, row, col, text, a in sorted(self.labels, key=lambda l: -l[0]):
            cells = [(row, c) for c in range(col - 1, col + len(text) + 1)]
            if any(c in taken for c in cells):
                continue
            taken.update(cells)
            self.vput(row, col, text, a)

    def draw_body(self, i):
        b = self.bodies[i]
        X, Y, sx, sy, r = self.P[i]
        cv = self.cv
        big = r >= 14.0
        show_moons = big and bool(b.moons)
        reach = r * max(b.ext_h, b.ext_v)
        if show_moons:
            reach = max(reach, r * max(m.Rf for m in b.moons) + 6)
        if sx + reach < 0 or sx - reach > cv.pw or sy + reach < 0 or sy - reach > cv.ph:
            return
        L = self.light(b, X, Y, r)
        if not b.R:
            # a distant Sun's corona must not sprinkle sparks over the target planet
            faint = r > 30 and not (self.target == 0 and self.heading_to_planet())
            self.draw_corona(sx, sy, r, faint)
        back = front = ()
        if b.ring or show_moons:
            back, front = self.ring_points(b, r, show_moons)
        wide = self.ring_geo(b, sx, sy, r, L) if b.ring_prof and r >= 2.0 else None
        moons = []
        if show_moons:
            _, (e1x, e1y, _), (e2x, e2y, e2z) = b.axes
            for m in b.moons:
                a = m.a0 + TAU * self.t / m.period
                ca, sa = math.cos(a), math.sin(a)
                R = m.Rf * r
                moons.append((sa * e2z, sx + R * (ca * e1x + sa * e2x),
                              sy + R * (ca * e1y + sa * e2y), max(1.0, m.size * r), m, -a))
        cv.plot_pts(back, sx, sy)
        if wide:
            self.plot_cells(wide[0])
        for z, mx, my, mr, m, mph in moons:
            if z <= 0:
                self.draw_sphere(mx, my, mr, m.tex, b.axes, 'bayer', L, mph, m.color, amb=0.08)
        rshadow = (b.axes[0], b.ring_prof) if b.ring_prof and r >= 7.0 else None
        self.draw_sphere(sx, sy, r, b.tex, b.axes, b.dither, L, b.spin * self.t, b.color,
                         amb=0.07, emissive=not b.R, lights=(b.key == 'earth'),
                         tick=int(self.t * 5), rshadow=rshadow)
        if wide:
            self.plot_cells(wide[1])
        cv.plot_pts(front, sx, sy)
        for z, mx, my, mr, m, mph in moons:
            if z > 0:
                self.draw_sphere(mx, my, mr, m.tex, b.axes, 'bayer', L, mph, m.color, amb=0.08)
        if big and b.R:
            self.draw_limb(sx, sy, r, L, b.atm)
        if not b.R and r > 25:
            self.draw_prominences(sx, sy, r)
        if r >= 26 and self.mode != 'overview' and not self.clean:
            for z, mx, my, mr, m, _ in moons:
                if z > 0 or math.hypot(mx - sx, my - sy) > r + mr:
                    self.label(my / 4, (mx + mr + 3) / 2, m.names[LANGS.index(self.lang)], 243, prio=4)

    def orbit_pts(self, R, theta, color, ox, oy, ppu, back, front):
        cv = self.cv
        pw, ph = cv.pw, cv.ph
        rx, ry = R * ppu, R * SIN_E * ppu
        if rx < 3 or ox + rx < 0 or ox - rx > pw or oy + ry < 0 or oy - ry > ph:
            return
        n = int(TAU * math.sqrt((rx * rx + ry * ry) / 2) / 4.0)
        step = TAU / n
        if n > 2400:                     # deep zoom — only the visible arc near the planet
            half = min(math.pi, (pw + ph) * 1.3 / rx)
            ks = range(int((theta - half) / step), int((theta + half) / step) + 1)
        else:
            ks = range(n)
        for k in ks:
            a = k * step
            s = math.sin(a)
            x = ox + rx * math.cos(a)
            y = oy - ry * s
            if 0 <= x < pw and 0 <= y < ph:
                (back if s > 0 else front).append((x, y, color))

    def render_scene(self):
        cv = self.cv
        cv.clear()
        cam = self.cam
        ppu = cam[4]
        ox = cam[2] * cv.pw - cam[0] * ppu
        oy = cam[3] * cv.ph - cam[1] * ppu
        T = self.t
        zoomed = ppu > self.base_ppu * 3.5
        steady = self.mode == 'detail'

        self.P = []
        for b in self.bodies:
            X, Y = self.body_world(b)
            self.P.append((X, Y, ox + X * ppu, oy + Y * SIN_E * ppu, b.r * ppu))

        back, front = [], []
        for b in self.bodies[1:]:
            if zoomed and b.idx != self.sel:
                continue
            col = 80 if b.idx == self.sel else 238
            self.orbit_pts(b.R, b.a0 + b.omega * T, col, ox, oy, ppu, back, front)
        if not zoomed:
            pw, ph = cv.pw, cv.ph
            for R, a0, w in self.asteroids:
                a = a0 + w * T
                s = math.sin(a)
                x = ox + R * math.cos(a) * ppu
                y = oy - R * s * SIN_E * ppu
                if 0 <= x < pw and 0 <= y < ph:
                    (back if s > 0 else front).append((x, y, 243))
            self.add_comet(ox, oy, ppu, back, front)

        cv.plot_pts(back)
        order = sorted(range(1, len(self.bodies)), key=lambda i: self.P[i][1])
        visible = [i for i in order if not steady or i == self.target]
        for i in visible:
            if self.P[i][1] < 0:
                self.draw_body(i)
        self.draw_body(0)
        cv.plot_pts(front)
        for i in visible:
            if self.P[i][1] >= 0:
                self.draw_body(i)

        if self.mode != 'detail':
            self.overview_labels()

    def add_comet(self, ox, oy, ppu, back, front):
        X, Y = self.comet_world()
        dist = math.hypot(X, Y)
        hx, hy = ox + X * ppu, oy + Y * SIN_E * ppu
        lst = back if Y < 0 else front
        dxs, dys = X / dist, Y * SIN_E / dist
        m = math.hypot(dxs, dys) or 1.0
        dxs, dys = dxs / m, dys / m
        tail = clamp(520.0 / dist, 1.5, 34.0) * ppu
        n = int(clamp(tail / 1.6, 3, 180))
        tick = int(self.t * 8)
        for k in range(n):
            f = (k + 1) / n
            h = ((k * 2654435761 + tick * 40503) >> 5) % 1000 / 1000.0
            if h < f * 0.65:
                continue
            spread = (h - 0.5) * f * tail * 0.12
            x = hx + dxs * tail * f - dys * spread
            y = hy + dys * tail * f + dxs * spread
            lst.append((x, y, 159 if f < 0.3 else 117 if f < 0.6 else 31))
            if k % 2 == 0:                                   # the dust tail is curved
                bend = f * f * tail * 0.22
                lst.append((hx + dxs * tail * f * 0.8 + dys * bend,
                            hy + dys * tail * f * 0.8 - dxs * bend, 230 if f < 0.4 else 244))
        for ddx, ddy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            lst.append((hx + ddx, hy + ddy, 255))

    def overview_labels(self):
        zoomed = self.cam[4] > self.base_ppu * 2.5
        sel_info = None
        for i, b in enumerate(self.bodies if not self.clean else ()):
            X, Y, sx, sy, r = self.P[i]
            if r > 22:
                continue
            rh = r * b.ext_h
            if i == self.sel:
                sel_info = (b, sx, sy, r)
            elif not zoomed or r > 4:
                self.label(sy / 4, (sx + rh + 3) / 2, self.name(b), 243)
        if sel_info:
            b, sx, sy, r = sel_info
            rh, rv = r * b.ext_h + 4, r * b.ext_v + 4
            le, ri = int((sx - rh) / 2), int((sx + rh) / 2)
            to, bo = int((sy - rv) / 4), int((sy + rv) / 4)
            for row, col, chh in ((to, le, '┌'), (to, ri, '┐'), (bo, le, '└'), (bo, ri, '┘')):
                self.label(row, col, chh, 80, prio=9)
            self.label(sy / 4, ri + 2, self.name(b), 80, True, prio=10)
            self.label(sy / 4 + 1, ri + 2, self.T(b)['au'], 244, prio=10)
        # a probe on a distant orbit
        a = 0.9 + 0.012 * self.t
        cam = self.cam
        px = cam[2] * self.cv.pw + (100 * math.cos(a) - cam[0]) * cam[4]
        py = cam[3] * self.cv.ph + (-100 * math.sin(a) * SIN_E - cam[1]) * cam[4]
        self.label(py / 4, px / 2 - 2, '=[]=', 250, prio=1)

    # ─────────────────────────── screen output ────────────────────────

    def put(self, y, x, s, attr=0):
        try:
            self.scr.addstr(y, x, s, attr)
        except curses.error:
            pass

    def vput(self, row, col, s, attr=0):
        if row < 0 or row >= self.ch or not s:
            return
        if col < 0:
            s = s[-col:]
            col = 0
        if col + len(s) > self.cw:
            s = s[:max(0, self.cw - col)]
        if s:
            self.put(self.oy + row, self.ox + col, s, attr)

    def star_map(self, now):
        cam = self.cam
        cw, ch, W, H, ox, oy = self.cw, self.ch, self.W, self.H, self.ox, self.oy
        shx = -cam[0] * cam[4] / 2
        shy = -cam[1] * cam[4] / 4
        m = {}
        for x, y, dpt, chh, c, tw, sp in self.stars:
            s = math.sin(tw + now * sp)
            if s < -0.93:
                continue
            row = int((y + shy * dpt) % H) - oy
            col = int((x + shx * dpt) % W) - ox
            if not (0 <= row < ch and 0 <= col < cw):
                continue
            if s > 0.95:
                chh, c = ('+' if chh in '.·' else '*'), 255
            m[row * cw + col] = (chh, c)
        return m

    def compose(self, now):
        cv = self.cv
        cw = cv.cw
        bits, col, occ = cv.bits, cv.col, cv.occ
        stars = self.star_map(now)
        A = self.pal.attr
        for row in range(cv.ch):
            base = row * cw
            runs = []
            cur = None
            buf = []
            start = 0
            for x in range(cw):
                i = base + x
                b = bits[i]
                if b:
                    chh = BRAILLE[b]
                    c = col[i]
                elif occ[i]:
                    chh, c = ' ', None
                else:
                    s = stars.get(i)
                    if s is None:
                        chh, c = ' ', None
                    else:
                        chh, c = s
                if c is None or c == cur:
                    buf.append(chh)
                else:
                    if buf:
                        runs.append((start, ''.join(buf), cur))
                    buf = [chh]
                    start = x
                    cur = c
            if buf:
                runs.append((start, ''.join(buf), cur))
            for x, text, c in runs:
                self.put(self.oy + row, self.ox + x, text, A(c) if c is not None else 0)

    def panel_lines(self, b, inner):
        key = (b.idx, inner, self.lang)
        if key in self.panel_cache:
            return self.panel_cache[key]
        L = []
        tx = self.T(b)
        L.append(('hdr', [(f"SOL-{b.idx:02d}  ·  {tx['au'].split(' · ')[0].upper()}", 244, False)]))
        L.append(('hdr', []))
        name = tx['name'].upper()
        if len(name) * 2 - 1 <= inner:
            name = ' '.join(name)
        L.append(('hdr', [(name, 255, True)]))
        L.append(('hdr', [(tx['cls'], 80, False)]))
        L.append(('rule', [('─' * inner, 238, False)]))
        for lab, val in tx['facts']:
            dots = inner - len(lab) - len(val) - 2
            if dots >= 2:
                L.append(('fact', [(lab + ' ', 245, False), ('·' * dots, 238, False),
                                   (' ' + val, 253, False)]))
            else:
                L.append(('fact', [(lab, 245, False)]))
                L.append(('fact', [(val.rjust(inner), 253, False)]))
        L.append(('rule', [('─' * inner, 238, False)]))
        for line in textwrap.wrap(tx['story'], inner):
            L.append(('text', [(line, 252, False)]))
        self.panel_cache[key] = L
        return L

    def draw_panel(self, now):
        A = self.pal.attr
        b = self.bodies[self.target]
        pw, ch = self.panel_w, self.ch
        x0 = self.cw - pw
        blank = ' ' * pw
        for r in range(ch):
            self.vput(r, x0, blank)
            self.vput(r, x0, '│', A(23))
        inner = pw - 4
        lines = self.panel_lines(b, inner)
        avail = ch - 2
        self.scroll = int(clamp(self.scroll, 0, max(0, len(lines) - avail)))
        budget = (now - self.arrive) * 260.0
        shown = []
        typing = False
        for kind, segs in lines:
            cost = 0 if kind == 'hdr' else 6 if kind in ('rule', 'fact') else sum(len(s[0]) for s in segs)
            if cost > budget:
                if kind == 'text' and budget > 0:
                    cut, out = int(budget), []
                    for txt, c, bo in segs:
                        out.append((txt[:cut], c, bo))
                        cut -= len(txt)
                        if cut <= 0:
                            break
                    shown.append(out)
                typing = True
                break
            budget -= cost
            shown.append(segs)
        if self.scroll == 0 and typing and len(shown) > avail:
            self.scroll = len(shown) - avail                 # auto-scroll while typing
        view = shown[self.scroll:self.scroll + avail]
        for k, segs in enumerate(view):
            x = x0 + 2
            for txt, c, bo in segs:
                self.vput(1 + k, x, txt, A(c) | (curses.A_BOLD if bo else 0))
                x += len(txt)
            if typing and k == len(view) - 1 and int(now * 3) % 2 == 0:
                self.vput(1 + k, x, '▌', A(80))
        if self.scroll > 0:
            self.vput(0, x0 + pw - 2, '▲', A(80))
        if not typing and self.scroll + avail < len(lines):
            self.vput(ch - 1, x0 + pw - 2, '▼', A(80))

    def draw_hud(self, now):
        A = self.pal.attr
        tr = self.trans
        avail = self.cw - (self.panel_w if self.show_panel() else 0)
        if self.mode != 'detail':
            names = [self.name(b) for b in self.bodies]
            if sum(len(n) + 3 for n in names) > self.cw - 4:
                names = [n[:3] for n in names]
            total = sum(len(n) + 3 for n in names)
            x = max(0, (self.cw - total) // 2)
            for i, n in enumerate(names):
                if i == self.sel:
                    self.vput(self.ch - 1, x, '▸' + n + '◂', A(80) | curses.A_BOLD)
                else:
                    self.vput(self.ch - 1, x + 1, n, A(241))
                x += len(n) + 3
        if tr:
            f = clamp((now - tr['t0']) / tr['dur'], 0.0, 1.0)
            if tr['dest'] == 'detail':
                b = self.bodies[tr['idx']]
                bar = '█' * int(f * 16) + '░' * (16 - int(f * 16))
                tx = self.T(b)
                msg = f"{self.U('course').format(tx.get('to', tx['name']).upper())}   {bar}  {int(f * 100):3d}%"
            else:
                msg = self.U('back')
            self.vput(self.ch - 3, max(0, (avail - len(msg)) // 2), msg, A(80))

    def draw_chrome(self, now):
        A = self.pal.attr
        B = curses.A_BOLD
        W, H = self.W, self.H
        fr = A(240)
        hl = '─' * (W - 2)
        self.put(0, 0, '┌' + hl + '┐', fr)
        for y in (2, H - 5, H - 3):
            self.put(y, 0, '├' + hl + '┤', fr)
        self.put(H - 1, 0, '└' + hl + '┘', fr)
        for y in list(range(3, H - 5)) + [1, H - 4, H - 2]:
            self.put(y, 0, '│', fr)
            self.put(y, W - 1, '│', fr)
        inner = ' ' * (W - 2)
        for y in (1, H - 4, H - 2):
            self.put(y, 1, inner)
        # header
        self.put(1, 3, 'ORBIT / TERMINAL UNIVERSE', A(253) | B)
        if self.paused:
            st, sc = 'SIMULATION PAUSED', A(214 if int(now * 2) % 2 else 250)
        else:
            st, sc = 'SIMULATION ACTIVE', A(250)
        fps = f'{self.fps:3.0f} FPS'
        self.put(1, W - 3 - len(fps), fps, A(250))
        self.put(1, W - 3 - len(fps) - 4 - len(st), st, sc)
        # status line
        zoom = self.cam[4] / self.base_ppu * 100
        segs = [('OBJECTS', str(self.n_objects)), ('TIME', f'{SPEEDS[self.speed_i]:.2f}x'),
                ('ZOOM', f'{zoom:.0f}%'), ('SECTOR', f'SOL-{self.sel:02d}')]
        x = 3
        for k, (lab, val) in enumerate(segs):
            if k:
                self.put(H - 4, x + 2, '│', A(80))
                x += 6
            self.put(H - 4, x, lab, A(246))
            self.put(H - 4, x + len(lab) + 2, val, A(253))
            x += len(lab) + 2 + len(val)
        tgt = f'TARGET  {self.name(self.bodies[self.sel])}'
        if x + 8 + len(tgt) < W - 2:
            self.put(H - 4, W - 3 - len(tgt), 'TARGET', A(246))
            self.put(H - 4, W - 3 - len(tgt) + 8, self.name(self.bodies[self.sel]), A(80) | B)
        # key hints
        hints = list(self.U('hints_body' if self.heading_to_planet() else 'hints_view'))
        qk, qd = hints.pop()
        qx = W - 3 - (len(qk) + 3 + len(qd))
        self.put(H - 2, qx, f'[{qk}]', A(253))
        self.put(H - 2, qx + len(qk) + 3, qd, A(246))
        x = 3
        for key, desc in hints:
            w = len(key) + 3 + len(desc)
            if x + w > qx - 3:
                break
            self.put(H - 2, x, f'[{key}]', A(253))
            self.put(H - 2, x + len(key) + 3, desc, A(246))
            x += w + 4

    def draw_clean_hint(self, now):
        """In clean view: a short reminder of how to get the interface back, fading out."""
        age = now - self.clean_t
        if age > 3.0:
            return
        msg = self.U('clean_hint')
        c = 248 if age < 2.0 else 243 if age < 2.5 else 239
        self.vput(self.ch - 2, (self.cw - len(msg)) // 2, msg, self.pal.attr(c))

    def draw(self, now):
        if self.too_small:
            self.scr.erase()
            msg = self.U('too_small')
            self.put(self.H // 2, max(0, (self.W - len(msg)) // 2), msg[:self.W], self.pal.attr(250))
            self.flush()
            return
        self.labels = []
        self.render_scene()
        self.compose(now)
        self.flush_labels()
        if self.clean:
            self.draw_clean_hint(now)
        else:
            if self.show_panel():
                self.draw_panel(now)
            self.draw_hud(now)
            self.draw_chrome(now)
        self.flush()

    # ─────────────────────────── main loop ────────────────────────────

    def run(self):
        frame = 1.0 / FPS_TARGET
        last = time.perf_counter()
        while True:
            now = time.perf_counter()
            dt = min(0.1, now - last)
            last = now
            if dt > 0:
                self.fps += (1.0 / dt - self.fps) * 0.08
            while True:
                try:
                    k = self.scr.get_wch()
                except curses.error:
                    break
                if self.handle_key(k, now) is False:
                    return
            self.update(dt, now)
            self.draw(now)
            spent = time.perf_counter() - now
            self.work.append((self.trans is not None, spent))
            if spent < frame:
                time.sleep(frame - spent)


def main(scr, lang):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    try:
        curses.set_escdelay(25)
    except AttributeError:
        pass
    scr.nodelay(True)
    scr.keypad(True)
    curses.mousemask(curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED
                     | getattr(curses, 'BUTTON4_PRESSED', 0) | getattr(curses, 'BUTTON5_PRESSED', 0))
    curses.mouseinterval(0)
    pal = Palette()

    def flush():
        scr.noutrefresh()
        curses.doupdate()

    app = App(scr, pal, flush, lang)
    app.boot()
    app.run()
    return app


def cli():
    """Entry point of the `orbit` command."""
    import argparse
    ap = argparse.ArgumentParser(description='ORBIT / TERMINAL UNIVERSE — '
                                 'an interactive Solar System in your terminal.')
    ap.add_argument('--lang', choices=LANGS, default='en',
                    help='interface language (default: en; press L to switch at runtime)')
    args = ap.parse_args()
    os.environ.setdefault('ESCDELAY', '25')
    locale.setlocale(locale.LC_ALL, '')
    try:
        app = curses.wrapper(main, args.lang)
    except KeyboardInterrupt:
        app = None
    if app and os.environ.get('ORBIT_BENCH'):
        for flag, name in ((True, 'flight'), (False, 'frame')):
            w = sorted(t for f, t in app.work[30:] if f == flag)
            if w:
                print(f'{name}: avg {sum(w) / len(w) * 1000:.1f} ms, '
                      f'p95 {w[int(len(w) * 0.95)] * 1000:.1f} ms, max {w[-1] * 1000:.1f} ms')


if __name__ == '__main__':
    cli()
