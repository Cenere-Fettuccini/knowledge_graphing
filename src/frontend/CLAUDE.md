# aimanager.frontend

Shared application shell. Hosts every app's view in a single HTML page
served by the platform. Apps bring their own page-specific assets in
`apps/<name>/static/`; the shell provides the shared chrome.

**Status:** shell — planned implementation. Stable layout established.

## Folder shape

```
frontend/
  index.html        Shell entry — sole HTML page served at /
  base.css          Design tokens: colours, typography, spacing, primitives
  app.js            Page router + bootstrap
  drum-nav.js       Global navigation widget (optional, post-chat-MVP)
  color-manager.js  Theme toggle (optional, post-chat-MVP)
```

## What lives here vs. in `apps/<name>/static/`

| `frontend/` | `apps/<name>/static/` |
|---|---|
| The single HTML page (`index.html`) | Per-app page JS (`<name>-page.js`) |
| Design tokens shared by all apps (`base.css`) | Per-app stylesheet (`<name>.css`) |
| Page router & shell mechanics (`app.js`) | Per-app event handlers, DOM templates |
| Cross-app utilities (theme, nav, modal manager) | App-specific UI logic |

Rule: if a file is used by only one app, it belongs in that app's
`static/` directory, not here.

## HTML structure (`index.html`)

The shell renders all app views in a stacked layout. Only the active
view is visible at a time.

```html
<body>
  <header class="app-header">
    <span class="app-brand">AIManager //</span>
    <nav class="drum-nav" id="drumNav" aria-label="Page navigator"></nav>
    <div class="app-header__right" id="headerRight"></div>
  </header>

  <main class="page-container">
    <section class="page-view" id="page-chat" hidden>...</section>
    <section class="page-view" id="page-flows" hidden>...</section>
    <!-- one <section> per registered app -->
  </main>

  <script src="/shell-assets/base.css"></script>
  <script src="/shell-assets/app.js"></script>
  <!-- per-app scripts mounted under the app's route_prefix -->
  <script src="/apps/chat/static/chat-page.js"></script>
  <script src="/apps/flows/static/flows-page.js"></script>
</body>
```

App page sections are populated by their respective JS files when the
shell shows that page.

## Public JavaScript API (window-scoped)

The shell exposes a small surface that app page JS may call:

```js
window.showPage(name)         // Switch the active app view; takes the app id (e.g. "chat")
window.activePage              // (string) The currently-visible app id
window.theme.toggle()          // Toggle light/dark
window.theme.current           // (string) "light" | "dark"
window.shell.onReady(fn)       // Register a callback invoked once the shell has bootstrapped
```

App page JS should attach event listeners in a `window.shell.onReady`
callback or on `DOMContentLoaded`. App JS reads/writes only within its
own `<section id="page-<name>">` element.

## Routing

The shell uses URL hash routing: `/#chat` shows the chat view, `/#flows`
shows the flows view. `app.js` listens for `hashchange` and calls
`showPage(name)` accordingly. Apps trigger navigation by setting
`location.hash`.

## Base styles (`base.css`)

Design tokens are CSS custom properties:

```css
:root {
  --bg: #0f1014;
  --panel: #14161c;
  --text: #e6e6e9;
  --dim: #8a8d99;
  --accent: #4d8bff;
  --font: "Inter", system-ui, sans-serif;
}
```

Primitives provided: `.app-shell`, `.app-header`, `.page-container`,
`.page-view`, `.module`, `.btn`, `.btn-ghost`, `.status-badge`.

App stylesheets extend these by composing them — they do not override
tokens.

## Public API stability

The window-scoped JavaScript API is the contract:

- **Non-breaking:** adding new `window.*` helpers, adding new CSS tokens or primitives, adding new layout slots.
- **Breaking:** removing or renaming `window.showPage`, `window.theme.*`, `window.shell.*`; removing CSS tokens; changing the `page-<name>` id convention.

## Backend contract

The frontend has only one contract with the backend: HTTP. Calls are
made via `fetch('/apps/<name>/<endpoint>')`. The frontend never imports
or references Python modules.

## Anti-patterns

- Per-app code in `frontend/` (move it to `apps/<name>/static/`).
- Direct DOM access outside an app's own `<section id="page-<name>">`.
- Cross-app JS imports (apps don't import each other's `<name>-page.js`).
- Setting `window.theme.current = "..."` (use `window.theme.toggle()`).
- Polling backend endpoints from the shell (apps own their own data fetching).
