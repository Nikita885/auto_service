/* Общий слой для всех трёх страниц: запросы к API, хранение токенов,
   уведомления, тема и форматирование.

   Клиентская и служебная страницы держат токены под разными ключами
   (`scope`): администратор и клиент — разные люди за одним браузером, и
   вход в панель не должен выкидывать клиента из его записи. */

(function (global) {
  "use strict";

  const API = "/api/v1";

  /* ------------------------------------------------------------ токены */

  function createStore(scope) {
    const k = (name) => scope + "." + name;
    return {
      get access() { return localStorage.getItem(k("access")); },
      get refresh() { return localStorage.getItem(k("refresh")); },
      save(access, refresh) {
        localStorage.setItem(k("access"), access);
        if (refresh) localStorage.setItem(k("refresh"), refresh);
      },
      clear() {
        localStorage.removeItem(k("access"));
        localStorage.removeItem(k("refresh"));
      },
    };
  }

  /* -------------------------------------------------------------- ошибки */

  class ApiError extends Error {
    constructor(code, message, details, status) {
      super(message);
      this.code = code;
      this.details = details || {};
      this.status = status;
    }
  }

  /* ------------------------------------------------------------- клиент */

  function createClient(scope, options) {
    const store = createStore(scope);
    const opts = options || {};
    let refreshing = null;

    async function raw(path, { method = "GET", body = null, auth = true } = {}) {
      const headers = { "Content-Type": "application/json" };
      if (auth && store.access) headers["Authorization"] = "Bearer " + store.access;

      const res = await fetch(API + path, {
        method,
        headers,
        body: body === null ? null : JSON.stringify(body),
      });

      if (res.status === 204) return null;

      const data = await res.json().catch(() => null);
      if (res.ok) return data;

      const err = (data && data.error) || {};
      throw new ApiError(
        err.code || String(res.status),
        err.message || res.statusText,
        err.details,
        res.status
      );
    }

    // Access живёт час: молча обновляем его по refresh и повторяем запрос,
    // иначе вкладка, открытая с утра, начнёт сыпать 401 на ровном месте.
    async function renew() {
      if (!store.refresh) return false;
      if (!refreshing) {
        refreshing = raw("/auth/token/refresh/", {
          method: "POST",
          body: { refresh: store.refresh },
          auth: false,
        })
          .then((data) => {
            store.save(data.access, data.refresh);
            return true;
          })
          .catch(() => {
            store.clear();
            return false;
          })
          .finally(() => { refreshing = null; });
      }
      return refreshing;
    }

    async function request(path, config) {
      try {
        return await raw(path, config);
      } catch (err) {
        if (err.status !== 401 || (config && config.auth === false)) throw err;
        if (!(await renew())) {
          if (opts.onSignedOut) opts.onSignedOut();
          throw err;
        }
        return raw(path, config);
      }
    }

    return {
      store,
      request,
      get: (path) => request(path),
      post: (path, body) => request(path, { method: "POST", body: body || {} }),
      patch: (path, body) => request(path, { method: "PATCH", body: body || {} }),
      get isAuthorized() { return Boolean(store.access); },
      signOut() { store.clear(); },
    };
  }

  /* --------------------------------------------------------- уведомления */

  function toast(text, kind, title) {
    let box = document.querySelector(".toasts");
    if (!box) {
      box = document.createElement("div");
      box.className = "toasts";
      document.body.append(box);
    }

    const el = document.createElement("div");
    el.className = "toast toast-" + (kind || "info");
    el.innerHTML =
      '<div style="flex:1;min-width:0">' +
      (title ? '<div class="toast-title"></div>' : "") +
      '<div class="toast-text"></div></div>' +
      '<button class="icon-btn toast-close" type="button" aria-label="Закрыть" ' +
      'style="width:24px;height:24px;border:none;background:none">' + icon("x") + "</button>";

    if (title) el.querySelector(".toast-title").textContent = title;
    el.querySelector(".toast-text").textContent = text;

    const remove = () => el.remove();
    el.querySelector(".toast-close").onclick = remove;
    box.append(el);
    setTimeout(remove, kind === "error" ? 8000 : 4500);
  }

  /** Единая обёртка вокруг действий: показывает ошибку API по-человечески. */
  async function guard(fn, fallback) {
    try {
      return await fn();
    } catch (err) {
      if (err instanceof ApiError) {
        toast(err.message, "error", "Не получилось");
      } else {
        toast(fallback || "Что-то пошло не так. Попробуйте ещё раз.", "error");
        console.error(err);
      }
      return undefined;
    }
  }

  /* --------------------------------------------------------------- тема */

  const theme = {
    apply(value) {
      document.documentElement.dataset.theme = value;
      localStorage.setItem("theme", value);
      const btn = document.getElementById("theme-toggle");
      if (btn) {
        btn.innerHTML = icon(value === "dark" ? "sun" : "moon");
        btn.title = value === "dark" ? "Светлая тема" : "Тёмная тема";
      }
    },
    init() {
      const saved = localStorage.getItem("theme");
      const prefersDark = matchMedia("(prefers-color-scheme: dark)").matches;
      this.apply(saved || (prefersDark ? "dark" : "light"));

      const btn = document.getElementById("theme-toggle");
      if (btn) {
        btn.onclick = () =>
          this.apply(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
      }
    },
  };

  /* --------------------------------------------------------- форматирование */

  const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  const DOW = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

  const fmt = {
    money(value) {
      const n = Number(value || 0);
      return n.toLocaleString("ru-RU", { maximumFractionDigits: 0 }) + " ₽";
    },
    number(value) {
      return Number(value || 0).toLocaleString("ru-RU");
    },
    percent(value) {
      return (Math.round(Number(value || 0) * 10) / 10).toLocaleString("ru-RU") + " %";
    },
    time(iso) {
      return new Date(iso).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    },
    date(iso) {
      const d = new Date(iso);
      return d.getDate() + " " + MONTHS[d.getMonth()];
    },
    dateFull(iso) {
      const d = new Date(iso);
      return d.getDate() + " " + MONTHS[d.getMonth()] + " " + d.getFullYear();
    },
    dateTime(iso) {
      return fmt.date(iso) + ", " + fmt.time(iso);
    },
    dow(iso) {
      return DOW[new Date(iso).getDay()];
    },
    /** Секунды в mm:ss — для таймера черновика. */
    clock(seconds) {
      const s = Math.max(0, Math.floor(seconds));
      return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
    },
    /** Дата в YYYY-MM-DD по локальному времени браузера, без сдвига в UTC. */
    isoDate(date) {
      const d = date || new Date();
      return [
        d.getFullYear(),
        String(d.getMonth() + 1).padStart(2, "0"),
        String(d.getDate()).padStart(2, "0"),
      ].join("-");
    },
    plural(n, one, few, many) {
      const abs = Math.abs(n) % 100;
      const last = abs % 10;
      if (abs > 10 && abs < 20) return many;
      if (last > 1 && last < 5) return few;
      if (last === 1) return one;
      return many;
    },
  };

  /* ------------------------------------------------------------- иконки */

  const ICONS = {
    drop: '<path d="M12 3s6 6.3 6 10.2A6 6 0 0 1 6 13.2C6 9.3 12 3 12 3z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 1.9"/>',
    pin: '<path d="M12 21s7-5.4 7-11a7 7 0 1 0-14 0c0 5.6 7 11 7 11z"/><circle cx="12" cy="10" r="2.6"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.2-4 4.3-6 8-6s6.8 2 8 6"/>',
    phone: '<path d="M5 3h4l2 5-2.5 1.5a12 12 0 0 0 6 6L16 13l5 2v4a2 2 0 0 1-2.2 2A17 17 0 0 1 3 5.2 2 2 0 0 1 5 3z"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    box: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    warn: '<path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4M12 17h.01"/>',
    inbox: '<path d="M3 13h5l1.5 3h5L16 13h5"/><path d="M4.5 5h15l1.5 8v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5z"/>',
    play: '<path d="M7 4v16l13-8z"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2 20c1-3.4 3.6-5.2 7-5.2s6 1.8 7 5.2"/><path d="M17 4.5a3.5 3.5 0 0 1 0 7M18.5 20c-.3-1.6-.9-3-1.8-4"/>',
    wallet: '<path d="M3 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M16 12h5v-3h-5a1.5 1.5 0 0 0 0 3z"/>',
  };

  function icon(name, size) {
    const path = ICONS[name] || "";
    const s = size || 24;
    return (
      '<svg viewBox="0 0 24 24" width="' + s + '" height="' + s + '" fill="none" ' +
      'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" ' +
      'aria-hidden="true">' + path + "</svg>"
    );
  }

  /* -------------------------------------------------------------- DOM */

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (value === null || value === undefined || value === false) return;
      if (key === "class") node.className = value;
      else if (key === "html") node.innerHTML = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on")) node[key.toLowerCase()] = value;
      else node.setAttribute(key, value === true ? "" : value);
    });
    (Array.isArray(children) ? children : children ? [children] : [])
      .filter(Boolean)
      .forEach((child) => node.append(child));
    return node;
  }

  function empty(text, iconName) {
    return el("div", { class: "empty", html: icon(iconName || "inbox", 30) + "<div>" + text + "</div>" });
  }

  /** Подтверждение в стиле сайта вместо системного confirm/prompt. */
  function ask({ title, text, placeholder, confirmLabel, danger, withInput, required }) {
    return new Promise((resolve) => {
      const input = withInput
        ? el("input", { type: "text", placeholder: placeholder || "", id: "ask-input" })
        : null;

      const backdrop = el("div", { class: "modal-backdrop" });
      const cancel = el("button", { class: "btn", type: "button", text: "Отмена" });
      const ok = el("button", {
        class: "btn " + (danger ? "btn-danger" : "btn-primary"),
        type: "button",
        text: confirmLabel || "Подтвердить",
      });

      const modal = el("div", { class: "modal" }, [
        el("div", { class: "modal-head" }, [
          el("div", {}, [
            el("div", { class: "modal-title", text: title }),
            text ? el("div", { class: "modal-sub", text: text }) : null,
          ]),
        ]),
        input ? el("div", { class: "field" }, [input]) : null,
        el("div", { class: "modal-actions" }, [cancel, ok]),
      ]);

      const close = (value) => { backdrop.remove(); document.removeEventListener("keydown", onKey); resolve(value); };
      const onKey = (e) => {
        if (e.key === "Escape") close(null);
        if (e.key === "Enter" && withInput) submit();
      };
      const submit = () => {
        if (!withInput) return close(true);
        const value = input.value.trim();
        if (required && !value) { input.focus(); return; }
        close(value);
      };

      cancel.onclick = () => close(null);
      ok.onclick = submit;
      backdrop.onclick = (e) => { if (e.target === backdrop) close(null); };
      document.addEventListener("keydown", onKey);

      backdrop.append(modal);
      document.body.append(backdrop);
      (input || ok).focus();
    });
  }

  global.App = { API, ApiError, createClient, toast, guard, theme, fmt, icon, $, $$, el, empty, ask };
})(window);
