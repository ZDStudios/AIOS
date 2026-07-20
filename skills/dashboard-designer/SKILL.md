---
name: dashboard-designer
description: >
  Restyle and extend The AI OS Control Room live — colours, sizes, spacing, density,
  which nav items show, and custom OpenUI panels — by calling the hub's dashboard API.
  Use whenever the user asks to change how the dashboard looks or is laid out:
  "make it blue", "bigger text", "more compact", "hide Automations", "add a panel
  showing X", "put a chart on the dashboard", "reset the theme".
---

# Dashboard Designer

You can change how the Control Room looks **without editing any code**. All styling
lives server-side in one JSON document that the dashboard applies on top of the active
theme. That means you can never break the dashboard by editing a file — if something
looks wrong, one `reset` call puts it back.

**Never edit `docs/dashboard.html` to restyle things.** Use this API. Editing the file
risks breaking the whole UI and needs a restart; the API applies within ~4 seconds live.

## The endpoint

```
POST http://127.0.0.1:8787/api/dashboard
Content-Type: application/json
Authorization: Bearer $AIOS_HUB_TOKEN     # only needed off-loopback
```

`GET` the same URL to read the current config before changing it.

## Colours, sizes, spacing

Set any CSS variable the theme uses. Keys must start with `--`.

```sh
curl -s -X POST http://127.0.0.1:8787/api/dashboard \
  -H 'Content-Type: application/json' -d '{
    "op": "set",
    "vars": {"--accent": "#4f9dff", "--accent-strong": "#7ab6ff", "--radius": "14px"},
    "scale": 1.1,
    "density": "comfortable"
  }'
```

- `vars` — CSS variables. The useful ones: `--bg`, `--surface`, `--elevated`, `--sunk`,
  `--text`, `--text2`, `--text3`, `--accent`, `--accent-strong`, `--border`,
  `--border-strong`, `--success`, `--danger`, `--alert`.
- `scale` — global font scale, `0.7`–`1.6` (clamped). `1.1` = 10% bigger text.
- `density` — `compact` | `normal` | `comfortable`. Controls padding on cards/rows/nav.
- `css` — raw CSS appended last, for anything variables can't express:
  `{"op":"set","css":".card{border-radius:20px} .vhead h2{letter-spacing:.02em}"}`

Rejected silently and reported back in `rejected`: variable names that aren't `--foo`,
values containing `{ } < > ;`, and CSS containing `@import`, `</style>`, or a remote
`url(http…)` (those could beacon out).

## Show/hide and reorder the sidebar

Nav ids: `chat canvas status opencode hermes openclaw crewai claudecode openclawos
memory channels tasks flows skills patterns updates security automations settings`

```sh
curl -s -X POST http://127.0.0.1:8787/api/dashboard -H 'Content-Type: application/json' \
  -d '{"op":"nav","hidden":["automations","openclawos"],"order":["chat","patterns","status"]}'
```

`order` floats those ids to the top in the order given; everything else keeps its place.

## OpenUI panels — put live UI on the dashboard

Panels are self-contained HTML rendered in a sandboxed iframe, exactly like the
generative-UI blocks in chat. Use them for dashboards, charts, tables, forms, counters.

```sh
curl -s -X POST http://127.0.0.1:8787/api/dashboard -H 'Content-Type: application/json' -d '{
  "op":"panel","action":"add","id":"deploys","title":"Deploy status","slot":"top","height":180,
  "by":"opencode",
  "html":"<div style=\"display:flex;gap:10px\"><b style=\"color:var(--accent)\">3</b> passing</div>"
}'
```

- `slot` — `top` (strip above the main view), `chat` (under the chat chips), `sidebar`.
- `height` — pixels, 60–1200.
- `id` — reuse the same id to **replace** a panel (that's how you update one live).
- Remove: `{"op":"panel","action":"del","id":"deploys"}` · clear all:
  `{"op":"panel","action":"clear"}`

**Style panels with the theme**, so they match whatever the user picked:
`var(--accent)`, `var(--bg)`, `var(--surface)`, `var(--text)`, `var(--border)`.
Keep panels self-contained: inline CSS/JS only, no external URLs (they're blocked).

## Undo

```sh
curl -s -X POST http://127.0.0.1:8787/api/dashboard -d '{"op":"reset","what":"all"}'
```

`what`: `all` | `vars` | `css` | `panels` | `nav`. Always offer this if the user
dislikes a change — it is instant and total.

## How to work

1. `GET /api/dashboard` first so you're editing from the current state, not guessing.
2. Make the smallest change that satisfies the request.
3. Tell the user what you changed and that `reset` undoes it.
4. Check `rejected` in the response — if non-empty, say which parts were refused and why.
