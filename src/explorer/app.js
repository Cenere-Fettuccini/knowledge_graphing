/**
 * ═══════════════════════════════════════════════════════════════════════════
 *  AIManager SPA — Router, Drum Navigator & Theme Engine
 * ─────────────────────────────────────────────────────────────────────────
 *  This module provides:
 *    1. DrumNavigator — Physics-based "number lock barrel" page selector
 *    2. PageRouter    — SPA view manager with transition animations
 *    3. ThemeEngine   — Dark/light toggle with persistence
 *  
 *  Architecture: Inheritance-based — every page module registers itself
 *  with the router and inherits the shell layout + theme.
 * ═══════════════════════════════════════════════════════════════════════════
 */

// ── Page Registry ───────────────────────────────────────────────────────────
// Each page module calls PageRouter.register() to add itself.
// The registry drives the drum navigator and the view switching.

const PageRouter = {
    _pages: [],        // { id, label, init(), destroy() }
    _activeId: null,
    _activeModule: null,

    register(pageDef) {
        this._pages.push(pageDef);
    },

    getPages() { return this._pages; },
    getActive() { return this._activeId; },
    getActiveModule() { return this._activeModule; },

    /** Navigate to a page by id */
    async navigateTo(id) {
        if (id === this._activeId) return;

        const prev = this._pages.find(p => p.id === this._activeId);
        const next = this._pages.find(p => p.id === id);
        if (!next) {
            console.warn(`[Router] Unknown page: ${id}`);
            return;
        }

        // Tear down previous
        if (prev && typeof prev.destroy === 'function') {
            try { prev.destroy(); } catch (e) { console.error('[Router] destroy error', e); }
        }
        document.querySelectorAll('.page-view').forEach(el => {
            el.classList.remove('is-active', 'is-entering');
        });

        // Activate next
        const container = document.getElementById(`page-${id}`);
        if (container) {
            container.classList.add('is-active', 'is-entering');
            // Remove entering class after animation
            container.addEventListener('animationend', () => {
                container.classList.remove('is-entering');
            }, { once: true });
        }

        this._activeId = id;
        this._activeModule = next;

        // Initialize the page
        if (typeof next.init === 'function') {
            try { await next.init(); } catch (e) { console.error('[Router] init error', e); }
        }

        // Update URL hash silently
        history.replaceState(null, '', `#${id}`);
        document.title = `AIManager | ${next.label}`;
    },

    /** Boot from URL hash or default to first page */
    boot() {
        const hash = location.hash.slice(1);
        const target = this._pages.find(p => p.id === hash) || this._pages[0];
        if (target) this.navigateTo(target.id);
    }
};


// ═══════════════════════════════════════════════════════════════════════════
//  DRUM NAVIGATOR — Physics-based number lock barrel
// ═══════════════════════════════════════════════════════════════════════════
// 
//  The drum uses a continuous position value (in pixels) that maps to items.
//  Physics simulation: velocity + friction + snap-to-slot with spring force.
//  Interaction: mouse/touch drag, wheel, or click-to-snap.

const DrumNavigator = {
    _track: null,
    _items: [],
    _itemH: 28,           // matches --drum-item-h
    _position: 0,         // current scroll position (px)
    _velocity: 0,         // current velocity (px/frame)
    _targetIndex: 0,      // which slot we're snapping toward
    _isDragging: false,
    _lastY: 0,
    _lastTime: 0,
    _dragVelocities: [],   // recent drag deltas for inertia
    _raf: null,
    _settled: true,
    _onNavigate: null,     // callback(index)
    _lastWheelTime: 0,

    // Physics tuning
    FRICTION: 0.85,    // velocity decay per frame (lower = more resistance)
    SNAP_SPRING: 0.12,    // spring stiffness toward snap point
    SNAP_DAMPING: 0.65,    // damping on the spring
    SETTLE_THRESHOLD: 0.3, // velocity below which we consider settled
    DRAG_SENSITIVITY: 0.40, // multiplier on drag deltas

    init(containerEl, items, onNavigate) {
        this._items = items;
        this._onNavigate = onNavigate;
        this._itemH = parseInt(getComputedStyle(document.documentElement)
            .getPropertyValue('--drum-item-h')) || 28;

        // Build DOM
        containerEl.innerHTML = '';

        const indicator = document.createElement('div');
        indicator.className = 'drum-nav__indicator';
        containerEl.appendChild(indicator);

        this._track = document.createElement('div');
        this._track.className = 'drum-nav__track';
        containerEl.appendChild(this._track);

        items.forEach((item, i) => {
            const el = document.createElement('div');
            el.className = 'drum-nav__item';
            el.textContent = item.label;
            el.dataset.index = i;
            el.addEventListener('click', () => this._snapTo(i));
            this._track.appendChild(el);
        });

        // Bind input events
        containerEl.addEventListener('mousedown', e => this._onPointerDown(e));
        containerEl.addEventListener('touchstart', e => this._onPointerDown(e), { passive: false });
        window.addEventListener('mousemove', e => this._onPointerMove(e));
        window.addEventListener('touchmove', e => this._onPointerMove(e), { passive: false });
        window.addEventListener('mouseup', e => this._onPointerUp(e));
        window.addEventListener('touchend', e => this._onPointerUp(e));
        containerEl.addEventListener('wheel', e => this._onWheel(e), { passive: false });

        // Start at first page
        this._position = 0;
        this._targetIndex = 0;
        this._applyTransform();
        this._updateClasses();
    },

    /** Set position to a specific index (no animation) */
    setIndex(index) {
        index = Math.max(0, Math.min(this._items.length - 1, index));
        this._position = index * this._itemH;
        this._targetIndex = index;
        this._velocity = 0;
        this._applyTransform();
        this._updateClasses();
    },

    /** Smooth snap to an index */
    _snapTo(index) {
        index = Math.max(0, Math.min(this._items.length - 1, index));
        this._targetIndex = index;
        this._settled = false;
        this._startPhysics();
    },

    // ── Input Handlers ────────────────────────────────────────────────────
    _getY(e) {
        if (e.touches && e.touches.length > 0) return e.touches[0].clientY;
        return e.clientY;
    },

    _onPointerDown(e) {
        // If it's a click (not drag), let the click handler on the item fire
        this._isDragging = true;
        this._settled = false;
        this._velocity = 0;
        this._lastY = this._getY(e);
        this._lastTime = performance.now();
        this._dragVelocities = [];

        // Stop existing physics
        if (this._raf) cancelAnimationFrame(this._raf);
        this._raf = null;

        const nav = e.currentTarget || e.target.closest('.drum-nav');
        if (nav) nav.classList.add('active');

        e.preventDefault();
    },

    _onPointerMove(e) {
        if (!this._isDragging) return;
        const y = this._getY(e);
        const now = performance.now();
        const dy = (this._lastY - y) * this.DRAG_SENSITIVITY;
        const dt = now - this._lastTime;

        // Clamp to valid range with rubber-band effect
        const maxPos = (this._items.length - 1) * this._itemH;
        const overscroll = 0.3; // rubber-band factor

        if (this._position + dy < 0) {
            this._position += dy * overscroll;
        } else if (this._position + dy > maxPos) {
            this._position += dy * overscroll;
        } else {
            this._position += dy;
        }

        // Track velocity for inertia
        if (dt > 0) {
            this._dragVelocities.push({ dy, dt });
            if (this._dragVelocities.length > 5) this._dragVelocities.shift();
        }

        this._lastY = y;
        this._lastTime = now;
        this._applyTransform();
        this._updateClasses();
        e.preventDefault();
    },

    _onPointerUp(e) {
        if (!this._isDragging) return;
        this._isDragging = false;

        document.querySelectorAll('.drum-nav').forEach(n => n.classList.remove('active'));

        let rawIndex = this._targetIndex;

        // Calculate drag momentum to snap to next/prev exactly one slot
        if (this._dragVelocities.length > 0) {
            let totalDy = 0, totalDt = 0;
            this._dragVelocities.forEach(v => { totalDy += v.dy; totalDt += v.dt; });
            const avgVel = (totalDy / totalDt) * 16;

            if (avgVel > 2) {
                rawIndex = this._targetIndex + 1;
            } else if (avgVel < -2) {
                rawIndex = this._targetIndex - 1;
            } else {
                rawIndex = Math.round(this._position / this._itemH);
            }
        } else {
            rawIndex = Math.round(this._position / this._itemH);
        }

        this._velocity = 0; // Disable inertial rolling, snap rigidly
        this._targetIndex = Math.max(0, Math.min(this._items.length - 1, rawIndex));

        this._settled = false;
        this._startPhysics();
    },

    _onWheel(e) {
        e.preventDefault();
        const now = performance.now();
        if (now - this._lastWheelTime < 500) return; // Cooldown for discrete clicks
        this._lastWheelTime = now;

        const delta = e.deltaY > 0 ? 1 : -1;
        const nextIndex = Math.max(0, Math.min(
            this._items.length - 1,
            this._targetIndex + delta
        ));
        this._snapTo(nextIndex);
    },

    // ── Physics Loop ──────────────────────────────────────────────────────
    _startPhysics() {
        if (this._raf) return; // already running
        const loop = () => {
            this._physicsStep();
            if (!this._settled) {
                this._raf = requestAnimationFrame(loop);
            } else {
                this._raf = null;
            }
        };
        this._raf = requestAnimationFrame(loop);
    },

    _physicsStep() {
        const targetPos = this._targetIndex * this._itemH;
        const maxPos = (this._items.length - 1) * this._itemH;

        // Clamp position with spring when out of bounds
        if (this._position < 0) {
            this._velocity += (-this._position) * 0.2;
            this._velocity *= 0.7;
        } else if (this._position > maxPos) {
            this._velocity += (maxPos - this._position) * 0.2;
            this._velocity *= 0.7;
        }

        // Apply friction
        this._velocity *= this.FRICTION;

        // When velocity is low enough, engage snap spring
        if (Math.abs(this._velocity) < 3) {
            const springForce = (targetPos - this._position) * this.SNAP_SPRING;
            this._velocity += springForce;
            this._velocity *= this.SNAP_DAMPING;
        }

        // Update position
        this._position += this._velocity;

        // Check if settled
        if (Math.abs(this._velocity) < this.SETTLE_THRESHOLD &&
            Math.abs(this._position - targetPos) < 0.5) {
            this._position = targetPos;
            this._velocity = 0;
            this._settled = true;

            // Fire navigation callback
            if (this._onNavigate) {
                this._onNavigate(this._targetIndex);
            }
        }

        this._applyTransform();
        this._updateClasses();
    },

    // ── DOM Updates ───────────────────────────────────────────────────────
    _applyTransform() {
        if (this._track) {
            this._track.style.transform = `translateY(${-this._position}px)`;
        }
    },

    _updateClasses() {
        const currentIndex = this._position / this._itemH;
        const children = this._track ? this._track.children : [];

        for (let i = 0; i < children.length; i++) {
            const dist = Math.abs(i - currentIndex);
            const el = children[i];

            el.classList.toggle('is-active', dist < 0.4);
            el.classList.toggle('is-near', dist >= 0.4 && dist < 1.2);

            // Continuous 3D transform for barrel feel
            const angle = (i - currentIndex) * 18; // degrees of tilt
            const opacity = Math.max(0.15, 1 - dist * 0.45);
            const scale = Math.max(0.82, 1 - dist * 0.08);

            el.style.opacity = opacity;
            el.style.transform = `scale(${scale}) perspective(200px) rotateX(${angle}deg)`;
        }
    }
};


// ═══════════════════════════════════════════════════════════════════════════
//  THEME ENGINE
// ═══════════════════════════════════════════════════════════════════════════

const ThemeEngine = {
    _btn: null,
    _icon: null,

    init() {
        this._btn = document.getElementById('themeToggle');
        this._icon = this._btn ? this._btn.querySelector('svg') : null;

        const saved = localStorage.getItem('theme') || 'dark';
        this._apply(saved);

        if (this._btn) {
            this._btn.addEventListener('click', () => {
                const next = document.body.classList.contains('light-theme') ? 'dark' : 'light';
                localStorage.setItem('theme', next);
                this._apply(next);
            });
        }
    },

    _apply(theme) {
        document.body.classList.toggle('light-theme', theme === 'light');
        if (this._icon) {
            this._icon.innerHTML = theme === 'light'
                ? '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>'
                : '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>';
        }
    }
};


// ═══════════════════════════════════════════════════════════════════════════
//  BOOT
// ═══════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    ThemeEngine.init();

    // Build drum navigator from registered pages
    const drumEl = document.getElementById('drumNav');
    const pages = PageRouter.getPages();

    if (drumEl && pages.length > 0) {
        DrumNavigator.init(drumEl, pages, (index) => {
            const page = pages[index];
            if (page) PageRouter.navigateTo(page.id);
        });

        // Determine initial page from hash
        const hash = location.hash.slice(1);
        const initialIndex = pages.findIndex(p => p.id === hash);
        const startIndex = initialIndex >= 0 ? initialIndex : 0;

        DrumNavigator.setIndex(startIndex);
        PageRouter.navigateTo(pages[startIndex].id);
    }
});
