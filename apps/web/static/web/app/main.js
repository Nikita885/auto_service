/* Каркас веб-приложения: вход, знакомство и четыре вкладки — как на Android. */

import { Auth, Onboarding } from "app/auth";
import { Bonus } from "app/bonus";
import { Garage } from "app/garage";
import { Home } from "app/home";
import { InstallGate, NotIphoneGate, gate } from "app/install";
import {
  CONFIG, OfflineBanner, api, bus, cache, errorText, html, invite, isNetworkError, render, toast, useEffect, useState,
} from "app/lib";
import { Profile } from "app/profile";

invite.capture();

if ("serviceWorker" in navigator) {
  // Ошибка регистрации не мешает работе — приложение просто не будет
  // открываться без сети.
  navigator.serviceWorker.register(CONFIG.swUrl, { scope: "/app/" }).catch(() => {});
}

// «Главная» (выбор заказчика, редизайн октябрь 2026): ближайшая запись,
// масло из гаража, баллы и история на одном экране, мастер записи — окном
// снизу.
const TABS = [
  ["home", "Главная", "home", Home],
  ["garage", "Гараж", "car", Garage],
  ["bonus", "Бонусы", "wallet", Bonus],
  ["profile", "Профиль", "user", Profile],
];

// Старые ссылки и закладки на вкладку «Записи» ведут на «Главную».
const ALIASES = { bookings: "home" };

const tabFromHash = () => {
  const raw = location.hash.replace("#", "");
  const name = ALIASES[raw] || raw;
  return TABS.some(([key]) => key === name) ? name : TABS[0][0];
};

function App() {
  // Не iPhone или Safari вместо установленного приложения — дальше не пускаем.
  const blocked = gate();
  if (blocked === "not-iphone") return html`<${NotIphoneGate} />`;
  if (blocked === "install") return html`<${InstallGate} />`;
  return html`<${Root} />`;
}

function Root() {
  // undefined — проверяем сессию, null — не вошли, объект — вошли.
  const [user, setUser] = useState(api.isAuthorized ? undefined : null);
  const [welcome, setWelcome] = useState(false);
  const [tab, setTab] = useState(tabFromHash());

  useEffect(() => {
    if (user !== undefined) return;
    api.get("/auth/me/")
      .then((me) => {
        if (me.role !== "client") {
          // Сотрудник вошёл не туда: его место — на сайте, а бонусы и
          // запись здесь сервер ему всё равно не отдаст.
          api.signOut();
          toast("Этот номер принадлежит сотруднику. Рабочее место мастера — на сайте, /master/.", "error");
          setUser(null);
          return;
        }
        cache.write("me", me);
        setUser(me);
        attachPendingInvite();
      })
      .catch((err) => {
        if (err.status === 401) { setUser(null); return; }
        // Нет сети — не выкидываем из аккаунта: токен цел, покажем экраны
        // с последними данными, а строка «нет сети» скажет, от какого они
        // времени. Уведомление здесь лишнее — та же новость дважды.
        const saved = cache.read("me");
        if (!isNetworkError(err)) toast(errorText(err), "error");
        setUser({ ...(saved ? saved.data : { full_name: "", role: "client" }), offline: true });
      });
  }, [user]);

  // Выход — сам или по протухшему refresh: последние данные экранов
  // чистим вместе с токенами, чужие записи на телефоне не остаются.
  useEffect(() => bus.on("signout", () => { cache.clear(); setUser(null); }), []);

  // Android: ссылку-приглашение открыли, пока приложение уже работало, —
  // оболочка отложила код и сообщает об этом. Вошедшего привязываем сразу,
  // невошедшему код уйдёт вместе со входом (invite.get()).
  useEffect(() => {
    const onInvite = () => { if (user && !user.offline) attachPendingInvite(); };
    window.addEventListener("nativeinvite", onInvite);
    return () => window.removeEventListener("nativeinvite", onInvite);
  }, [user]);

  // Системная кнопка «Назад» на Android: закрыть окно, сканер, вернуться на
  // первую вкладку — и только с неё выйти из приложения. Ответ `false`
  // оболочка понимает как «выходи».
  useEffect(() => {
    window.__nativeBack = () => {
      if (document.querySelector(".modal-backdrop")) {
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
        return true;
      }
      const sheetClose = [...document.querySelectorAll(".sheet [data-close]")].pop();
      if (sheetClose) { sheetClose.click(); return true; }
      const scannerClose = [...document.querySelectorAll(".scanner .btn")].pop();
      if (scannerClose) { scannerClose.click(); return true; }
      if (user && tab !== TABS[0][0]) { go(TABS[0][0]); return true; }
      return false;
    };
  }, [tab, user]);
  useEffect(() => bus.on("goto", (name) => go(name)), []);
  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function go(name) {
    if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
    setTab(name);
    window.scrollTo(0, 0);
  }

  if (user === undefined) {
    return html`<div class="pwa-splash" aria-busy="true"><img src=${CONFIG.icon} alt="" width="96" height="96" /></div>`;
  }
  if (user === null) {
    return html`<${Auth} onSignedIn=${(me, isNew) => { setWelcome(isNew || !me.full_name); setUser(me); }} />`;
  }
  if (welcome) {
    return html`<${Onboarding} user=${user} onDone=${(me) => { setWelcome(false); setUser(me); go(TABS[0][0]); }} />`;
  }

  const Screen = (TABS.find(([key]) => key === tab) || TABS[0])[3];
  return html`
    <${OfflineBanner} />
    <${Screen} key=${tab} user=${user} />
    <nav class="tabbar" aria-label="Разделы">
      ${TABS.map(([key, label, iconName]) => html`<button type="button" key=${key}
        aria-current=${key === tab ? "page" : null} onClick=${() => go(key)}>
        <span class="tab-ico" dangerouslySetInnerHTML=${{ __html: window.App.icon(iconName, 22) }}></span>
        ${label}
      </button>`)}
    </nav>`;
}

/** Вошедший клиент открыл ссылку-приглашение — привязываем без вопросов.

    Сервер сам откажет, если приглашение уже принято: такой отказ молчит,
    остальные объясняем. */
async function attachPendingInvite() {
  const code = invite.get();
  if (!code) return;
  try {
    await api.post("/referral/attach/", { code });
    toast("Вы приняли приглашение по коду " + code + ".", "ok", "Приглашение принято");
  } catch (err) {
    if (err.code !== "referral_already_attached") toast(errorText(err), "error");
  }
  invite.done();
}

// Заставка из HTML видна, пока грузятся модули. Preact рисует рядом, а не
// поверх неё, — без очистки она оставалась внизу страницы.
const root = document.getElementById("root");
root.replaceChildren();
render(html`<${App} />`, root);
