/* Общее для экранов веб-приложения: API, форматирование, мелкие хуки.

   Клиент API, уведомления, модалки и форматирование берутся из core.js —
   того же, на котором работают панели сотрудников. Второй копии логики
   обновления токена или формата ошибок здесь нет намеренно. */

import { html, render, useCallback, useEffect, useRef, useState } from "preact";

export { html, render, useCallback, useEffect, useRef, useState };

const App = window.App;

export const CONFIG = JSON.parse(document.getElementById("app-config").textContent);
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
    try { return localStorage.getItem(INVITE_KEY) || ""; } catch (e) { return ""; }
  },
  /** Код обработан (принят или отклонён) — больше не предлагаем. */
  done() {
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

/** Пустое состояние экрана с кнопкой повтора при ошибке. */
export function LoadError({ error, onRetry }) {
  return html`<div class="empty-state">
    <b>Не удалось загрузить</b>
    <p>${errorText(error)}</p>
    <button class="btn" type="button" style="margin-top:12px" onClick=${onRetry}>Повторить</button>
  </div>`;
}
