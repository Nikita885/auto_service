/* Каркас веб-приложения: вход, знакомство и четыре вкладки — как на Android. */

import { Auth, Onboarding } from "app/auth";
import { Booking } from "app/booking";
import { Bookings } from "app/bookings";
import { Bonus } from "app/bonus";
import { autoOpenFromLink } from "app/install";
import { CONFIG, api, bus, errorText, html, invite, render, toast, useEffect, useState } from "app/lib";
import { Profile } from "app/profile";

invite.capture();
autoOpenFromLink();

if ("serviceWorker" in navigator) {
  // Ошибка регистрации не мешает работе — приложение просто не будет
  // открываться без сети.
  navigator.serviceWorker.register(CONFIG.swUrl, { scope: "/app/" }).catch(() => {});
}

const TABS = [
  ["booking", "Запись", "drop", Booking],
  ["bookings", "Мои записи", "list", Bookings],
  ["bonus", "Бонусы", "wallet", Bonus],
  ["profile", "Профиль", "user", Profile],
];

const tabFromHash = () => {
  const name = location.hash.replace("#", "");
  return TABS.some(([key]) => key === name) ? name : "booking";
};

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
        setUser(me);
        attachPendingInvite();
      })
      .catch((err) => {
        if (err.status === 401) { setUser(null); return; }
        // Нет сети — не выкидываем из аккаунта: токен цел, покажем экраны.
        toast(errorText(err), "error");
        setUser({ full_name: "—", role: "client", offline: true });
      });
  }, [user]);

  useEffect(() => bus.on("signout", () => setUser(null)), []);
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
    return html`<${Onboarding} user=${user} onDone=${(me) => { setWelcome(false); setUser(me); go("booking"); }} />`;
  }

  const Screen = (TABS.find(([key]) => key === tab) || TABS[0])[3];
  return html`
    <${Screen} key=${tab} />
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
render(html`<${Root} />`, root);
