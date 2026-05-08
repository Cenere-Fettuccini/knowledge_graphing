(function () {
    const ShellEvents = {
        listeners: new Map(),

        on(type, handler) {
            if (!this.listeners.has(type)) {
                this.listeners.set(type, new Set());
            }
            this.listeners.get(type).add(handler);
            return () => this.off(type, handler);
        },

        off(type, handler) {
            this.listeners.get(type)?.delete(handler);
        },

        emit(event) {
            this.listeners.get(event.type)?.forEach((handler) => {
                try {
                    handler(event);
                } catch (error) {
                    console.error(`[ShellEvents] handler failed for ${event.type}`, error);
                }
            });
        },
    };

    const PageRouter = {
        _pages: [],
        _activeId: null,
        _activeModule: null,
        _defaultPageId: 'explorer',
        _preferredOrder: ['credits', 'chat', 'explorer', 'financial', 'routine'],

        register(pageDef) {
            this._pages.push(pageDef);
        },

        getPages() {
            const order = new Map(this._preferredOrder.map((id, index) => [id, index]));
            return [...this._pages].sort((a, b) => {
                const aRank = order.has(a.id) ? order.get(a.id) : Number.MAX_SAFE_INTEGER;
                const bRank = order.has(b.id) ? order.get(b.id) : Number.MAX_SAFE_INTEGER;
                if (aRank !== bRank) return aRank - bRank;
                return a.label.localeCompare(b.label);
            });
        },

        getActive() {
            return this._activeId;
        },

        getActiveModule() {
            return this._activeModule;
        },

        getPage(id) {
            return this._pages.find((page) => page.id === id) || null;
        },

        getPathForPage(id) {
            const page = this.getPage(id);
            return page?.paths?.[0] || `/${id}`;
        },

        getPageIdForPath(pathname) {
            const normalized = (pathname || '/').replace(/\/+$/, '') || '/';
            const page = this._pages.find((entry) =>
                (entry.paths || []).some((path) => path === normalized)
            );
            return page?.id || null;
        },

        async navigateTo(id, contextEvent = null) {
            const next = this.getPage(id);
            if (!next) {
                console.warn(`[Router] Unknown page: ${id}`);
                return;
            }
            if (id === this._activeId && !contextEvent) {
                return;
            }

            const previous = this.getPage(this._activeId);
            if (previous && previous !== next && typeof previous.unmount === 'function') {
                try {
                    previous.unmount();
                } catch (error) {
                    console.error(`[Router] unmount failed for ${previous.id}`, error);
                }
            }

            document.querySelectorAll('.page-view').forEach((el) => {
                el.classList.remove('is-active', 'is-entering');
            });

            const container = document.getElementById(`page-${id}`);
            if (container) {
                container.classList.add('is-active', 'is-entering');
                container.addEventListener('animationend', () => {
                    container.classList.remove('is-entering');
                }, { once: true });
            }

            this._activeId = id;
            this._activeModule = next;

            if (typeof next.mount === 'function') {
                try {
                    await next.mount(container, window.AIManagerShell);
                } catch (error) {
                    console.error(`[Router] mount failed for ${next.id}`, error);
                }
            }

            const searchInput = document.getElementById('searchInput');
            if (searchInput && typeof next.onSearch === 'function') {
                next.onSearch(searchInput.value, window.AIManagerShell);
            }

            history.replaceState(null, '', this.getPathForPage(id));
            document.title = `AIManager | ${next.label}`;

            if (contextEvent) {
                window.AIManagerShell.dispatchContext(id, contextEvent);
            }
        },
    };

    const DrumNavigator = {
        _track: null,
        _items: [],
        _itemH: 28,
        _position: 0,
        _velocity: 0,
        _targetIndex: 0,
        _isDragging: false,
        _lastY: 0,
        _lastTime: 0,
        _dragVelocities: [],
        _raf: null,
        _settled: true,
        _onNavigate: null,
        _lastWheelTime: 0,
        FRICTION: 0.85,
        SNAP_SPRING: 0.12,
        SNAP_DAMPING: 0.65,
        SETTLE_THRESHOLD: 0.3,
        DRAG_SENSITIVITY: 0.40,

        init(containerEl, items, onNavigate) {
            this._items = items;
            this._onNavigate = onNavigate;
            this._itemH = parseInt(
                getComputedStyle(document.documentElement).getPropertyValue('--drum-item-h'),
                10,
            ) || 28;

            containerEl.innerHTML = '';
            const indicator = document.createElement('div');
            indicator.className = 'drum-nav__indicator';
            containerEl.appendChild(indicator);

            this._track = document.createElement('div');
            this._track.className = 'drum-nav__track';
            containerEl.appendChild(this._track);

            items.forEach((item, index) => {
                const el = document.createElement('div');
                el.className = 'drum-nav__item';
                el.textContent = item.label;
                el.dataset.index = index;
                el.addEventListener('click', () => this._snapTo(index));
                this._track.appendChild(el);
            });

            containerEl.addEventListener('mousedown', (event) => this._onPointerDown(event));
            containerEl.addEventListener('touchstart', (event) => this._onPointerDown(event), { passive: false });
            window.addEventListener('mousemove', (event) => this._onPointerMove(event));
            window.addEventListener('touchmove', (event) => this._onPointerMove(event), { passive: false });
            window.addEventListener('mouseup', (event) => this._onPointerUp(event));
            window.addEventListener('touchend', (event) => this._onPointerUp(event));
            containerEl.addEventListener('wheel', (event) => this._onWheel(event), { passive: false });

            this.setIndex(0);
        },

        setIndex(index) {
            index = Math.max(0, Math.min(this._items.length - 1, index));
            this._position = index * this._itemH;
            this._targetIndex = index;
            this._velocity = 0;
            this._applyTransform();
            this._updateClasses();
        },

        _snapTo(index) {
            index = Math.max(0, Math.min(this._items.length - 1, index));
            this._targetIndex = index;
            this._settled = false;
            this._startPhysics();
        },

        _getY(event) {
            if (event.touches && event.touches.length > 0) return event.touches[0].clientY;
            return event.clientY;
        },

        _onPointerDown(event) {
            this._isDragging = true;
            this._settled = false;
            this._velocity = 0;
            this._lastY = this._getY(event);
            this._lastTime = performance.now();
            this._dragVelocities = [];

            if (this._raf) cancelAnimationFrame(this._raf);
            this._raf = null;

            const nav = event.currentTarget || event.target.closest('.drum-nav');
            if (nav) nav.classList.add('active');
            event.preventDefault();
        },

        _onPointerMove(event) {
            if (!this._isDragging) return;
            const y = this._getY(event);
            const now = performance.now();
            const dy = (this._lastY - y) * this.DRAG_SENSITIVITY;
            const dt = now - this._lastTime;
            const maxPos = (this._items.length - 1) * this._itemH;

            if (this._position + dy < 0 || this._position + dy > maxPos) {
                this._position += dy * 0.3;
            } else {
                this._position += dy;
            }

            if (dt > 0) {
                this._dragVelocities.push({ dy, dt });
                if (this._dragVelocities.length > 5) this._dragVelocities.shift();
            }

            this._lastY = y;
            this._lastTime = now;
            this._applyTransform();
            this._updateClasses();
            event.preventDefault();
        },

        _onPointerUp() {
            if (!this._isDragging) return;
            this._isDragging = false;
            document.querySelectorAll('.drum-nav').forEach((el) => el.classList.remove('active'));

            let rawIndex = this._targetIndex;
            if (this._dragVelocities.length > 0) {
                let totalDy = 0;
                let totalDt = 0;
                this._dragVelocities.forEach((entry) => {
                    totalDy += entry.dy;
                    totalDt += entry.dt;
                });
                const avgVel = (totalDy / totalDt) * 16;
                if (avgVel > 2) rawIndex = this._targetIndex + 1;
                else if (avgVel < -2) rawIndex = this._targetIndex - 1;
                else rawIndex = Math.round(this._position / this._itemH);
            } else {
                rawIndex = Math.round(this._position / this._itemH);
            }

            this._velocity = 0;
            this._targetIndex = Math.max(0, Math.min(this._items.length - 1, rawIndex));
            this._settled = false;
            this._startPhysics();
        },

        _onWheel(event) {
            event.preventDefault();
            const now = performance.now();
            if (now - this._lastWheelTime < 500) return;
            this._lastWheelTime = now;
            const delta = event.deltaY > 0 ? 1 : -1;
            const nextIndex = Math.max(0, Math.min(this._items.length - 1, this._targetIndex + delta));
            this._snapTo(nextIndex);
        },

        _startPhysics() {
            if (this._raf) return;
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

            if (this._position < 0) {
                this._velocity += (-this._position) * 0.2;
                this._velocity *= 0.7;
            } else if (this._position > maxPos) {
                this._velocity += (maxPos - this._position) * 0.2;
                this._velocity *= 0.7;
            }

            this._velocity *= this.FRICTION;
            if (Math.abs(this._velocity) < 3) {
                const springForce = (targetPos - this._position) * this.SNAP_SPRING;
                this._velocity += springForce;
                this._velocity *= this.SNAP_DAMPING;
            }

            this._position += this._velocity;
            if (Math.abs(this._velocity) < this.SETTLE_THRESHOLD && Math.abs(this._position - targetPos) < 0.5) {
                this._position = targetPos;
                this._velocity = 0;
                this._settled = true;
                if (this._onNavigate) this._onNavigate(this._targetIndex);
            }

            this._applyTransform();
            this._updateClasses();
        },

        _applyTransform() {
            if (this._track) {
                this._track.style.transform = `translateY(${-this._position}px)`;
            }
        },

        _updateClasses() {
            const currentIndex = this._position / this._itemH;
            const children = this._track ? this._track.children : [];
            for (let index = 0; index < children.length; index += 1) {
                const dist = Math.abs(index - currentIndex);
                const el = children[index];
                el.classList.toggle('is-active', dist < 0.4);
                el.classList.toggle('is-near', dist >= 0.4 && dist < 1.2);
                const angle = (index - currentIndex) * 18;
                const opacity = Math.max(0.15, 1 - dist * 0.45);
                const scale = Math.max(0.82, 1 - dist * 0.08);
                el.style.opacity = opacity;
                el.style.transform = `scale(${scale}) perspective(200px) rotateX(${angle}deg)`;
            }
        },
    };

    const ThemeEngine = {
        init() {
            this.button = document.getElementById('themeToggle');
            this.icon = this.button ? this.button.querySelector('svg') : null;
            const saved = localStorage.getItem('theme') || 'dark';
            this.apply(saved);
            this.button?.addEventListener('click', () => {
                const next = document.body.classList.contains('light-theme') ? 'dark' : 'light';
                localStorage.setItem('theme', next);
                this.apply(next);
            });
        },

        apply(theme) {
            document.body.classList.toggle('light-theme', theme === 'light');
            if (this.icon) {
                this.icon.innerHTML = theme === 'light'
                    ? '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>'
                    : '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>';
            }
        },
    };

    const ShellContext = {
        clients: window.AIManagerClients || {},
        events: ShellEvents,

        on(type, handler) {
            return ShellEvents.on(type, handler);
        },

        emit(type, payload = {}) {
            const event = { type, payload, sectionId: PageRouter.getActive() };
            ShellEvents.emit(event);
            const active = PageRouter.getActiveModule();
            if (active?.onContext) {
                active.onContext(event, this);
            }
        },

        async navigateToSection(id, contextEvent = null) {
            await PageRouter.navigateTo(id, contextEvent);
        },

        dispatchContext(targetId, event) {
            const page = PageRouter.getPage(targetId);
            if (page?.onContext) {
                page.onContext(event, this);
            }
            ShellEvents.emit({ ...event, targetId });
        },

        getCurrentSectionId() {
            return PageRouter.getActive();
        },

        getSectionRoot(id = PageRouter.getActive()) {
            return document.getElementById(`page-${id}`);
        },

        setSearchPlaceholder(text) {
            const searchInput = document.getElementById('searchInput');
            if (searchInput) searchInput.placeholder = text;
        },

        setSearchValue(value) {
            const searchInput = document.getElementById('searchInput');
            if (searchInput) searchInput.value = value;
        },

        setTopStats(text, visible = true) {
            const stats = document.getElementById('topStats');
            if (!stats) return;
            stats.textContent = text;
            stats.style.display = visible ? '' : 'none';
        },
    };

    window.PageRouter = PageRouter;
    window.AIManagerShell = ShellContext;

    document.addEventListener('DOMContentLoaded', () => {
        ThemeEngine.init();

        const searchInput = document.getElementById('searchInput');
        searchInput?.addEventListener('input', (event) => {
            const active = PageRouter.getActiveModule();
            if (active?.onSearch) {
                active.onSearch(event.target.value, ShellContext);
            }
        });

        const drumEl = document.getElementById('drumNav');
        const pages = PageRouter.getPages();
        if (!drumEl || pages.length === 0) {
            return;
        }

        DrumNavigator.init(drumEl, pages, (index) => {
            const page = pages[index];
            if (page) PageRouter.navigateTo(page.id);
        });

        const pathPageId = PageRouter.getPageIdForPath(location.pathname);
        const pathIndex = pages.findIndex((page) => page.id === pathPageId);
        const defaultIndex = pages.findIndex((page) => page.id === PageRouter._defaultPageId);
        const startIndex = pathIndex >= 0 ? pathIndex : (defaultIndex >= 0 ? defaultIndex : 0);

        DrumNavigator.setIndex(startIndex);
        PageRouter.navigateTo(pages[startIndex].id);
    });
})();
