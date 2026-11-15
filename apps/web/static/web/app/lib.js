/* Общее для экранов веб-приложения: API, форматирование, мелкие хуки.

   Клиент API, уведомления, модалки и форматирование берутся из core.js —
   того же, на котором работают панели сотрудников. Второй копии логики
   обновления токена или формата ошибок здесь нет намеренно. */

import { html, render, useCallback, useEffect, useRef, useState } from "preact";

export { html, render, useCallback, useEffect, useRef, useState };

const App = window.App;

export const CONFIG = JSON.parse(document.getElementById("app-config").textContent);

/* ------------------------------------------------------ Android-оболочка */

/** Мост к Android-приложению (`MoiServisNative`), или null — мы не в нём.

    На Android это же веб-приложение открывается в оболочке: экраны пишутся
    один раз и совпадают с iPhone по построению. Оболочка добавляет то, чего
    нет у страницы: хранилище токенов в Keystore, системное «Поделиться»,
    буфер обмена, код приглашения из ссылки и из Google Play, отступы под
    системные панели. */
export const native = window.MoiServisNative || null;
export const isAndroidShell = () => Boolean(native);

/* Отступы под строку состояния и навигацию. В WebView `env(safe-area-*)`
   всегда ноль, а оболочка рисует страницу под системными панелями, как
   iPhone: отступы присылает она, app.css берёт их раньше `env()`. */
function applyNativeInsets() {
  if (!native || !native.insets) return;
  try {
    const inset = JSON.parse(native.insets());
    const style = document.documentElement.style;
    style.setProperty("--native-safe-top", inset.top + "px");
    style.setProperty("--native-safe-bottom", inset.bottom + "px");
  } catch (e) { /* без отступов страница всё равно рабочая */ }
}
applyNativeInsets();
window.addEventListener("nativeinsets", applyNativeInsets);

/** «Поделиться»: системное меню телефона; где его нет — копируем текст. */
export async function shareText(text) {
  if (native && native.share) { native.share(text); return "shared"; }
  if (navigator.share) {
    try { await navigator.share({ text }); } catch (e) { /* закрыли меню */ }
    return "shared";
  }
  return (await copyText(text)) ? "copied" : "failed";
}

/** Текст из буфера обмена — для «Вставить код»; пусто, если нельзя.

    iPhone покажет системное «Вставить» над кнопкой: читать буфер без
    касания человека браузер не даёт, и это правильно. */
export async function pasteText() {
  if (native && native.paste) return native.paste() || "";
  try {
    return await navigator.clipboard.readText();
  } catch (e) {
    return "";
  }
}

export const canPaste = () => Boolean((native && native.paste) || (navigator.clipboard && navigator.clipboard.readText));

/** В буфер обмена. В WebView `navigator.clipboard` есть не везде — через мост. */
export async function copyText(text) {
  if (native && native.copy) return Boolean(native.copy(text));
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    return false;
  }
}
export const fmt = App.fmt;
export const toast = App.toast;
export const ask = App.ask;

/* ------------------------------------------------------------ события */

const listeners = {};
let sessionEpoch = 0;
export const bus = {
  on(name, fn) {
    (listeners[name] = listeners[name] || []).push(fn);
    return () => { listeners[name] = listeners[name].filter((f) => f !== fn); };
  },
  emit(name, payload) {
    if (name === "signout") sessionEpoch += 1;
    (listeners[name] || []).forEach((fn) => fn(payload));
  },
};

// Отдельная «область» токенов: клиентская сессия не должна пересекаться
// с сессией сотрудника в том же браузере.
export const api = App.createClient("client", { onSignedOut: () => bus.emit("signout") });

/** Сеть пропала, а не сервер отказал: у `ApiError` есть ответ сервера. */
export const isNetworkError = (err) => !(err instanceof App.ApiError);

/** Текст ошибки для человека: сеть — отдельно, остальное — как сказал сервер. */
export function errorText(err) {
  if (!isNetworkError(err)) return err.message || "Что-то пошло не так.";
  return "Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.";
}

/** Выполнить запрос; ошибку показать уведомлением и вернуть undefined. */
export async function call(fn) {
  try {
    return await fn();
  } catch (err) {
    toast(errorText(err), "error");
    return undefined;
  }
}

/* -------------------------------------------- последние известные данные */

/** Последние ответы сервера по экранам — чтобы без сети показать то, что
    человек видел, а не пустой экран с ошибкой (`DESIGN_PROMPT.md`:
    «показываем последнее известное и честно говорим, что оно не свежее»).

    Service worker ответы API не кеширует намеренно: устаревшие данные
    допустимы только с подписью «данные на 21:40», а её может поставить
    только экран. Хранилище общее с токенами и чистится при выходе: на
    телефоне после выхода чужие записи не должны оставаться. */
const CACHE_PREFIX = "client.cache.";
const cacheBox = native && native.clearCache ? native : localStorage;
if (native && native.clearCache) {
  try {
    Object.keys(localStorage).filter((k) => k.startsWith(CACHE_PREFIX)).forEach((k) => localStorage.removeItem(k));
  } catch (e) { /* Старый незашифрованный кеш необязателен. */ }
}
export const cache = {
  read(key) {
    try {
      const raw = cacheBox.getItem(CACHE_PREFIX + key);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  },
  write(key, data) {
    try { cacheBox.setItem(CACHE_PREFIX + key, JSON.stringify({ data, at: Date.now() })); } catch (e) { /* место кончилось — просто без кеша */ }
  },
  remove(key) {
    try { cacheBox.removeItem(CACHE_PREFIX + key); } catch (e) { /* необязательный кеш */ }
  },
  clear() {
    try {
      if (native && native.clearCache) native.clearCache();
      Object.keys(localStorage).filter((k) => k.startsWith(CACHE_PREFIX)).forEach((k) => localStorage.removeItem(k));
    } catch (e) { /* приватный режим */ }
  },
};

/** Состояние связи для всего приложения: `{ offline, at }`, где `at` —
    время самых старых показанных данных. Ставят его загрузки экранов:
    `navigator.onLine` на Android в WebView и на iPhone с главного экрана
    врёт в обе стороны, верить стоит только ответу сервера. */
const net = { offline: false, at: null };
const offlineSources = new Map();
function setNet(source, failed, at) {
  if (failed) offlineSources.set(source, at || Date.now());
  else offlineSources.delete(source);
  const offline = offlineSources.size > 0;
  at = offline ? Math.min(...offlineSources.values()) : null;
  if (net.offline === offline && (!offline || net.at === at)) return;
  net.offline = offline;
  net.at = at;
  bus.emit("net", { ...net });
}
export function useNet() {
  const [state, setState] = useState({ ...net });
  useEffect(() => bus.on("net", setState), []);
  return state;
}

/** Загрузка данных для экрана: `{ data, error, loading, stale, reload }`.

    `key` — имя для кеша: экран сразу рисуется с последними данными, а
    свежие приходят следом. Без сети остаются последние, и `stale` говорит,
    от какого они времени. */
export function useLoad(loader, deps, key) {
  const initial = key ? cache.read(key) : null;
  const [state, setState] = useState({
    data: initial ? initial.data : undefined, error: null, loading: true, stale: null,
  });
  const seq = useRef(0);
  const netSource = useRef(Symbol("load"));

  const reload = useCallback(async () => {
    const my = ++seq.current;
    const epoch = sessionEpoch;
    setState((s) => ({ ...s, loading: true }));
    try {
      const data = await loader();
      if (my !== seq.current || epoch !== sessionEpoch) return;
      if (key) cache.write(key, data);
      setNet(netSource.current, false);
      setState({ data, error: null, loading: false, stale: null });
    } catch (err) {
      if (my !== seq.current || epoch !== sessionEpoch) return;
      const saved = key && isNetworkError(err) ? cache.read(key) : null;
      setNet(netSource.current, isNetworkError(err), saved && saved.at);
      setState((s) => ({
        data: saved ? saved.data : s.data, error: err, loading: false, stale: saved ? saved.at : null,
      }));
    }
  }, deps || []);

  useEffect(() => {
    reload();
    return () => { seq.current += 1; setNet(netSource.current, false); };
  }, [reload]);
  return { ...state, reload };
}

/** «Записаться» с любого экрана: открыть «Главную» и мастер на ней.

    Флаг, а не только событие: «Главная» может быть ещё не открыта,
    и её слушатель появится уже после того, как событие прозвучало. */
let bookingRequested = false;
export function startBooking() {
  bookingRequested = true;
  bus.emit("goto", "home");
  bus.emit("booking:start");
}
export function takeBookingRequest() {
  const requested = bookingRequested;
  bookingRequested = false;
  return requested;
}

/* ------------------------------------------------------------ телефон */

/** «+7 (900) 123-45-67» из того, что человек набрал. Сервер всё равно
    нормализует номер — здесь только удобство чтения при вводе. */
export function formatPhone(raw) {
  let digits = String(raw || "").replace(/\D/g, "");
  if (digits.startsWith("8")) digits = "7" + digits.slice(1);
  if (digits && !digits.startsWith("7")) digits = "7" + digits;
  digits = digits.slice(0, 11);
  const d = digits.slice(1);
  let out = "+7";
  if (d.length) out += " (" + d.slice(0, 3);
  if (d.length >= 3) out += ")";
  if (d.length > 3) out += " " + d.slice(3, 6);
  if (d.length > 6) out += "-" + d.slice(6, 8);
  if (d.length > 8) out += "-" + d.slice(8, 10);
  return out;
}

export const phoneComplete = (value) => String(value || "").replace(/\D/g, "").length === 11;

/* ---------------------------------------------------- код приглашения */

const INVITE_KEY = "client.invite";
// Код, который уже применили или который сервер отклонил. Приложение с
// главного экрана iPhone каждый раз стартует с `?invite=` в адресе — без
// этой отметки оно пыталось бы привязать человека при каждом запуске.
const INVITE_DONE_KEY = "client.invite.done";

/** Код из ссылки `/app/?invite=КОД` запоминаем до регистрации.

    На iPhone у приложения с главного экрана своё хранилище, отдельное от
    Safari, поэтому код ещё и подставляется в поле при знакомстве — клиент
    увидит его и сможет поправить руками. */
export const invite = {
  capture() {
    const code = (new URLSearchParams(location.search).get("invite") || "").trim().toUpperCase();
    if (!code) return;
    try {
      if (localStorage.getItem(INVITE_DONE_KEY) === code) return;
      localStorage.setItem(INVITE_KEY, code);
    } catch (e) { /* приватный режим */ }
  },
  /** Код отсканировали в приложении — запоминаем как из ссылки. */
  set(code) {
    try { localStorage.setItem(INVITE_KEY, code); } catch (e) { /* приватный режим */ }
  },
  get() {
    let code = "";
    try { code = localStorage.getItem(INVITE_KEY) || ""; } catch (e) { /* приватный режим */ }
    // Android: код из ссылки `/i/<код>` и из Google Play забирает оболочка —
    // в том числе после загрузки страницы (ответ магазина приходит не сразу).
    if (!code && native && native.pendingInvite) code = native.pendingInvite() || "";
    return code;
  },
  /** Код обработан (принят или отклонён) — больше не предлагаем. */
  done() {
    if (native && native.clearInvite) native.clearInvite();
    try {
      const code = localStorage.getItem(INVITE_KEY);
      if (code) localStorage.setItem(INVITE_DONE_KEY, code);
      localStorage.removeItem(INVITE_KEY);
    } catch (e) { /* приватный режим */ }
  },
};

/* ------------------------------------------------------------ разное */

export function Icon({ name, size }) {
  return html`<span class="tab-glyph" aria-hidden="true"
    dangerouslySetInnerHTML=${{ __html: App.icon(name, size || 22) }}></span>`;
}

export function money(value) {
  return fmt.money(value);
}

/** Дата визита в поясе адреса: «24 сен, 12:30». Время приходит в UTC. */
export function visitTime(iso, zone) {
  const d = new Date(iso);
  const opts = { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: zone || undefined };
  try {
    return d.toLocaleString("ru-RU", opts).replace(".", "");
  } catch (e) {
    return fmt.dateTime(iso);
  }
}

/** «Сегодня», «Завтра», «Через 3 дня» — сколько осталось до визита по
    календарю точки. Подсказка над датой, как «In 7 days» у Fresha: дату
    ещё надо сопоставить с сегодняшней, а это читается сразу. */
export function daysUntil(iso, zone) {
  const day = (d) => {
    const parts = localDay(d, zone).split("-").map(Number);
    return Date.UTC(parts[0], parts[1] - 1, parts[2]);
  };
  const n = Math.round((day(new Date(iso)) - day(new Date())) / 86400000);
  if (n < 0) return "";
  if (n === 0) return "Сегодня";
  if (n === 1) return "Завтра";
  if (n === 2) return "Послезавтра";
  const mod10 = n % 10, mod100 = n % 100;
  const word = mod10 === 1 && mod100 !== 11 ? "день"
    : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? "дня" : "дней";
  return "Через " + n + " " + word;
}

/** ISO-дата точки без зависимости от разделителей локали Safari/Chrome. */
export function localDay(value, zone) {
  const date = new Date(value);
  try {
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en", {
      timeZone: zone || undefined, year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(date).map((p) => [p.type, p.value]));
    return [parts.year, parts.month, parts.day].join("-");
  } catch (e) { return fmt.isoDate(date); }
}

/** Строка сводки: иконка, подпись сверху, значение снизу — как в
    «Review» у Walmart Auto Service и Grab. Подпись над значением, а не
    слева: длинное название масла не ломается в узкую правую колонку. */
export function InfoRow({ icon, label, children }) {
  return html`<div class="info-row">
    <span class="info-ico" dangerouslySetInnerHTML=${{ __html: window.App.icon(icon, 18) }}></span>
    <span class="info-body">
      ${label && html`<small>${label}</small>`}
      <span>${children}</span>
    </span>
  </div>`;
}

export const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent) ||
  (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
export const isStandalone = () =>
  window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;

const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
// Длительность выезда — `--dur-sheet` из шкалы; здесь только чтобы снять
// окно со страницы, когда анимация закрытия доиграла.
const SHEET_MS = 320;
// Насколько смахнуть вниз, чтобы окно закрылось, — как в системных листах
// iOS: меньше четверти высоты отпускание возвращает окно на место.
const SWIPE_CLOSE = 0.25;
// Сколько окон открыто: окно поверх окна (форма машины поверх записи)
// не должно вернуть прокрутку странице, закрывшись первым.
let openSheets = 0;
const sheetStack = [];
const inertBefore = new Map();
function syncSheetAccess() {
  for (const [el, value] of inertBefore) el.inert = value;
  inertBefore.clear();
  const top = sheetStack[sheetStack.length - 1];
  if (!top) return;
  let node = top;
  while (node && node !== document.body) {
    const parent = node.parentElement;
    if (!parent) break;
    for (const sibling of parent.children) {
      if (sibling !== node) {
        if (!inertBefore.has(sibling)) inertBefore.set(sibling, sibling.inert);
        sibling.inert = true;
      }
    }
    node = parent;
  }
}

/** Окно снизу поверх вкладки: мастер записи, перенос, формы гаража.

    Своё, а не `App.dialog` панелей: сценарию из нескольких шагов нужен
    почти весь экран. Выезжает снизу и закрывается так, как привыкли на
    телефоне: смахиванием вниз за ручку или шапку, крестиком, Escape и
    системной «Назад» на Android (`data-close` — её ищет main.js).

    `onClose` вызывается после анимации закрытия; `guard` — необязательная
    проверка перед закрытием (вернула false — окно остаётся). `actions` —
    кнопки, прибитые к низу окна над полоской «Домой». */
export function Sheet({ title, onClose, guard, actions, children, tall }) {
  const [phase, setPhaseState] = useState("in"); // in → open → out
  const phaseRef = useRef("in");
  const setPhase = (value) => { phaseRef.current = value; setPhaseState(value); };
  const [drag, setDrag] = useState(0);
  const panel = useRef(null);
  const body = useRef(null);
  const start = useRef(null);

  async function close() {
    if (phaseRef.current === "out") return;
    if (guard && !(await guard())) { setDrag(0); return; }
    setPhase("out");
    setTimeout(onClose, reduceMotion() ? 0 : SHEET_MS);
  }

  useEffect(() => {
    const previousFocus = document.activeElement;
    const currentPanel = panel.current;
    sheetStack.push(currentPanel);
    // Effects дочернего компонента могут выполниться раньше родителя.
    // Вершину определяет вложенность DOM, а не порядок effects.
    sheetStack.sort((a, b) => {
      if (a.contains(b)) return -1;
      if (b.contains(a)) return 1;
      return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
    });
    syncSheetAccess();
    const focusable = () => [...currentPanel.querySelectorAll('button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]')]
      .filter((el) => !el.inert && el.getClientRects().length);
    const t = requestAnimationFrame(() => setPhase("open"));
    const focusFrame = requestAnimationFrame(() => (focusable()[0] || currentPanel).focus());
    const onKey = (e) => {
      if (sheetStack[sheetStack.length - 1] !== currentPanel || document.querySelector(".modal-backdrop")) return;
      if (e.key === "Escape") { e.preventDefault(); close(); }
      if (e.key === "Tab") {
        const items = focusable();
        const first = items[0], last = items[items.length - 1];
        if (!first) { e.preventDefault(); currentPanel.focus(); }
        else if (e.shiftKey && (document.activeElement === first || !currentPanel.contains(document.activeElement))) {
          e.preventDefault(); last.focus();
        } else if (!e.shiftKey && (document.activeElement === last || !currentPanel.contains(document.activeElement))) {
          e.preventDefault(); first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    // Под окном страница не должна прокручиваться вместе с ним.
    openSheets += 1;
    document.body.classList.add("sheet-open");
    return () => {
      cancelAnimationFrame(t);
      cancelAnimationFrame(focusFrame);
      sheetStack.splice(sheetStack.indexOf(currentPanel), 1);
      syncSheetAccess();
      if (previousFocus && previousFocus.isConnected && !previousFocus.inert) previousFocus.focus();
      document.removeEventListener("keydown", onKey);
      openSheets -= 1;
      if (!openSheets) document.body.classList.remove("sheet-open");
    };
  }, []);

  // Смахивание: тянем за шапку всегда, за содержимое — только когда оно
  // прокручено к началу, иначе жест принадлежит прокрутке списка.
  function onDown(e) {
    const fromBody = body.current && body.current.contains(e.target);
    if (fromBody && body.current.scrollTop > 0) return;
    if (e.target.closest("input, textarea, select, button, a")) return;
    start.current = { y: e.clientY, t: Date.now() };
  }
  function onMove(e) {
    if (!start.current) return;
    setDrag(Math.max(0, e.clientY - start.current.y));
  }
  function onUp(e) {
    if (!start.current) return;
    const dy = Math.max(0, e.clientY - start.current.y);
    const speed = dy / Math.max(1, Date.now() - start.current.t);
    start.current = null;
    const height = panel.current ? panel.current.offsetHeight : 600;
    if (dy > height * SWIPE_CLOSE || speed > 0.8) close();
    else setDrag(0);
  }

  const style = drag ? `transform:translateY(${drag}px);transition:none` : "";
  return html`<div class=${"sheet-layer is-" + phase} onClick=${(e) => { if (e.target === e.currentTarget) close(); }}>
    <div class=${"sheet" + (tall ? " sheet-tall" : "")} role="dialog" aria-modal="true" aria-label=${title} tabindex="-1" ref=${panel} style=${style}
      onPointerDown=${onDown} onPointerMove=${onMove} onPointerUp=${onUp} onPointerCancel=${onUp}>
      <span class="sheet-grab" aria-hidden="true"></span>
      <div class="sheet-bar">
        <b>${title}</b>
        <button class="sheet-x" type="button" data-close aria-label="Закрыть" onClick=${close}
          dangerouslySetInnerHTML=${{ __html: App.icon("x", 18) }}></button>
      </div>
      <div class="sheet-body" ref=${body}>${children}</div>
      ${actions && html`<div class="sheet-actions">${actions}</div>`}
    </div>
  </div>`;
}

/** Заглушка на время загрузки: повторяет форму будущего блока, а не
    пишет «Загружаем…» — экран не прыгает, когда данные приходят. */
export function Skel({ w, h, r, style }) {
  const css = ["width:" + (w || "100%"), "height:" + (h || "var(--space-4)"), r ? "border-radius:" + r : "", style || ""]
    .filter(Boolean).join(";");
  return html`<span class="skel" aria-hidden="true" style=${css}></span>`;
}

/** Строка «нет сети» над экраном: что показано и от какого оно времени. */
export function OfflineBanner() {
  const state = useNet();
  if (!state.offline) return null;
  const at = state.at ? new Date(state.at) : null;
  const when = at
    ? (at.toDateString() === new Date().toDateString() ? "" : fmt.date(at.toISOString()) + ", ")
      + at.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
    : "";
  return html`<div class="offline" role="status">
    <span dangerouslySetInnerHTML=${{ __html: App.icon("wifi-off", 16) }}></span>
    <span>${when ? "Нет сети · данные на " + when : "Нет сети"}</span>
  </div>`;
}

/** Пустое состояние экрана с кнопкой повтора при ошибке. */
export function LoadError({ error, onRetry }) {
  return html`<div class="empty-state">
    <span class="empty-ico" dangerouslySetInnerHTML=${{ __html: App.icon(isNetworkError(error) ? "wifi-off" : "warn", 28) }}></span>
    <b>${isNetworkError(error) ? "Нет связи с сервером" : "Не получилось загрузить"}</b>
    <p>${isNetworkError(error) ? "Проверьте интернет — экран обновится, как только связь вернётся." : errorText(error)}</p>
    <button class="btn" type="button" onClick=${onRetry}>Повторить</button>
  </div>`;
}
