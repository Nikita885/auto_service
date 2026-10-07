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
export const bus = {
  on(name, fn) {
    (listeners[name] = listeners[name] || []).push(fn);
    return () => { listeners[name] = listeners[name].filter((f) => f !== fn); };
  },
  emit(name, payload) { (listeners[name] || []).forEach((fn) => fn(payload)); },
};

// Отдельная «область» токенов: клиентская сессия не должна пересекаться
// с сессией сотрудника в том же браузере.
export const api = App.createClient("client", { onSignedOut: () => bus.emit("signout") });

/** Текст ошибки для человека: сеть — отдельно, остальное — как сказал сервер. */
export function errorText(err) {
  if (err instanceof App.ApiError) return err.message || "Что-то пошло не так.";
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

/** Загрузка данных для экрана: `{ data, error, loading, reload }`. */
export function useLoad(loader, deps) {
  const [state, setState] = useState({ data: undefined, error: null, loading: true });
  const seq = useRef(0);

  const reload = useCallback(async () => {
    const my = ++seq.current;
    setState((s) => ({ ...s, loading: true }));
    try {
      const data = await loader();
      if (my === seq.current) setState({ data, error: null, loading: false });
    } catch (err) {
      if (my === seq.current) setState((s) => ({ ...s, error: err, loading: false }));
    }
  }, deps || []);

  useEffect(() => { reload(); }, [reload]);
  return { ...state, reload };
}

/** «Записаться» с любого экрана: открыть вкладку «Записи» и мастер на ней.

    Флаг, а не только событие: вкладка «Записи» может быть ещё не открыта,
    и её слушатель появится уже после того, как событие прозвучало. */
let bookingRequested = false;
export function startBooking() {
  bookingRequested = true;
  bus.emit("goto", "bookings");
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

export const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent) ||
  (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
export const isStandalone = () =>
  window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;

/** Окно во весь экран поверх вкладки: мастер записи, перенос.

    Своё, а не `App.dialog` панелей: на телефоне сценарию из нескольких
    шагов нужен весь экран, а не карточка посередине. Закрывается крестиком,
    Escape и системной кнопкой «Назад» на Android (`data-close`). */
export function Sheet({ title, onClose, children }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape" && !document.querySelector(".modal-backdrop")) onClose(); };
    document.addEventListener("keydown", onKey);
    // Под окном страница не должна прокручиваться вместе с ним.
    document.body.classList.add("sheet-open");
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.classList.remove("sheet-open");
    };
  }, [onClose]);
  return html`<div class="sheet" role="dialog" aria-modal="true" aria-label=${title}>
    <div class="sheet-bar">
      <b>${title}</b>
      <button class="icon-btn" type="button" data-close aria-label="Закрыть" onClick=${onClose}
        dangerouslySetInnerHTML=${{ __html: App.icon("x", 22) }}></button>
    </div>
    <div class="sheet-body">${children}</div>
  </div>`;
}

/** Пустое состояние экрана с кнопкой повтора при ошибке. */
export function LoadError({ error, onRetry }) {
  return html`<div class="empty-state">
    <b>Не удалось загрузить</b>
    <p>${errorText(error)}</p>
    <button class="btn" type="button" style="margin-top:12px" onClick=${onRetry}>Повторить</button>
  </div>`;
}
