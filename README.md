# ORBIT / TERMINAL UNIVERSE

An interactive Solar System that lives in your terminal. Fly from planet to planet, zoom in
close and read a short story about every world — all drawn with Unicode Braille dots and
256 colors.

**Pure Python 3 · zero dependencies · a single file**

![Flying to Saturn and back](screenshots/flight.gif)

## Screenshots

| | |
|:---:|:---:|
| ![System overview](screenshots/overview.png) | ![Saturn](screenshots/saturn.png) |
| System overview with real planet positions | Saturn: rings with the Cassini Division |
| ![Earth](screenshots/earth.png) | ![Jupiter](screenshots/jupiter.png) |
| Earth: continents, mountains, clouds, city lights | Jupiter: belts, zones and festoons |
| ![The Sun](screenshots/sun.png) | ![Mars with the Russian interface](screenshots/mars_ru.png) |
| The Sun: granulation, sunspots, prominences | Mars, with the interface switched to Russian |

## Features

- **The whole Solar System** — the Sun, eight planets, 14 moons, the asteroid belt, a comet
  with ion and dust tails, and a lonely probe.
- **Real positions** — at launch every planet sits where it actually is today (computed from
  mean orbital longitudes); after that, time runs faster.
- **Cinematic camera** — smooth zoom-and-pan flights (the van Wijk–Nuij optimal path) between
  the system view and any planet, and from planet to planet.
- **Detailed procedural worlds**
  - **Earth** — continents with mountains, snowy peaks, deserts, forests and jungle, shallow
    seas, polar ice, spiral cyclones and city lights on the night side;
  - **Mars** — Olympus Mons and the Tharsis volcanoes, Valles Marineris, Hellas, Syrtis Major,
    spiral polar caps and hundreds of craters;
  - **Jupiter** — over twenty belts and zones, the Great Red Spot, white ovals, blue-gray
    festoons and polar vortices;
  - **Saturn** — rings drawn dot by dot from a real radial profile (C ring, B ring, Cassini
    Division, A ring with the Encke gap, F ring), the planet's shadow on the rings, the rings'
    shadow on the globe and the north polar hexagon;
  - **Uranus** lying on its side, **Neptune** with its Great Dark Spot and methane clouds,
    cratered **Mercury**, **Venus** with its cloud chevrons, a **Sun** with sunspots and
    prominences, plus moons with their own surfaces: volcanic Io, cracked icy Europa, hazy Titan.
- **Info panel** — key facts and a short story for every body, typed out like a ship's computer.
- **Clean view** — press `H` to hide the whole interface and enjoy the planets full-screen.
- **English and Russian** — English by default, press `L` to switch at any time.
- **Mouse support** — click a planet to fly to it, use the wheel to zoom.

## Requirements

- Python 3.8 or newer (standard library only).
- A terminal with Unicode and 256-color support — Alacritty, Ghostty, Kitty, WezTerm,
  GNOME Terminal, Konsole, iTerm2, Windows Terminal… — and a monospace font that has Braille
  glyphs (JetBrains Mono, Cascadia Code, DejaVu Sans Mono and most modern fonts do).
- A window of at least 64×20. The bigger the window, the more detail; around 200×55 is ideal.
- On Windows, `curses` is not built in: `pip install windows-curses` should make it work
  (not tested).

## Run

```sh
git clone https://github.com/diaszulatov-arch/orbit-terminal-universe.git
cd orbit-terminal-universe
python3 orbit.py              # English
python3 orbit.py --lang ru    # Russian
```

## Controls

| Key | Action |
|---|---|
| `←` `→` (or `A` `D`) | select a body; in planet view, fly to the neighbouring one |
| `Enter` / `↓` | approach the selected body |
| `Esc` / `Backspace` | return to the system view |
| `0` – `8` | jump straight to a body: 0 — Sun, 1 — Mercury … 8 — Neptune |
| `↑` `↓` | scroll the story (planet view) |
| `+` `-` | zoom |
| `<` `>` (or `[` `]`) | simulation speed |
| `Space` | pause |
| `I` | hide / show the info panel |
| `H` / `Tab` | clean view: hide every panel, frame and label — only the planets remain |
| `L` | switch language: English ↔ Russian |
| `Q` | quit |
| Mouse | click a planet to fly to it, scroll to zoom |

Keys also work with a Russian keyboard layout.

## How it works

- **Braille canvas.** Every terminal cell is a 2×4 grid of Braille dots, so the effective
  resolution is twice the width and four times the height of the terminal.
- **Per-dot shading.** For every dot of a planet the renderer finds the surface normal, turns it
  into latitude and longitude, samples a procedural 256×128 texture (fractal value noise,
  craters, storms, bands), applies lighting and decides whether the dot is lit using ordered
  dithering — Bayer 8×8 for rocky worlds, horizontal "line" dithering for banded giants.
- **Hue-preserving shading.** One color per cell is all a terminal allows, so each cell takes the
  surface color darkened along a ramp of the xterm-256 palette that keeps the hue: rusty
  red turns brown, not gray.
- **Rings.** Saturn's rings are computed per dot from a radial density profile, with the planet's
  shadow on the rings and the rings' shadow on the globe.
- **Speed.** Planet geometry is cached while the camera is still and computed per cell during
  flights, which keeps the animation at about 30 FPS in a 200×55 terminal on a modern CPU.
  Run with `ORBIT_BENCH=1` to print frame times on exit.
- **Scale.** Sizes and distances are not to scale — otherwise the inner planets would be
  invisible — but every number in the info panel is real.

The screenshots above are real frames of the program rendered with JetBrains Mono.

## License

[MIT](LICENSE)
