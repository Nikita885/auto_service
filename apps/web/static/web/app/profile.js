/* Профиль: имя, машины, которые видит мастер, и выход. */

import { CONFIG, LoadError, api, ask, bus, call, html, toast, useEffect, useLoad, useState } from "app/lib";

export function Profile() {
  const me = useLoad(() => api.get("/auth/me/"));
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (me.data) setName(me.data.full_name || "");
  }, [me.data]);

  async function save() {
    setBusy(true);
    const ok = await call(() => api.patch("/auth/me/", { full_name: name.trim() }));
    setBusy(false);
    if (ok) toast("Имя сохранено", "ok");
  }

  async function signOut() {
    const yes = await ask({
      title: "Выйти из аккаунта?",
      text: "Войти обратно можно по номеру телефона.",
      confirmLabel: "Выйти", danger: true,
    });
    if (!yes) return;
    api.signOut();
    bus.emit("signout");
  }

  if (me.error && !me.data) {
    return html`<main class="screen"><${LoadError} error=${me.error} onRetry=${me.reload} /></main>`;
  }

  return html`<main class="screen">
    <div class="screen-head">
      <h1>Профиль</h1>
      <p>Имя видит мастер — так он понимает, что заезжаете именно вы.</p>
    </div>
    <div class="stack-lg">
      <form class="card pad stack" onSubmit=${(e) => { e.preventDefault(); save(); }}>
        <div class="field">
          <label>Телефон</label>
          <input value=${me.data ? me.data.phone : ""} disabled />
        </div>
        <div class="field">
          <label for="p-name">Имя</label>
          <input id="p-name" autocomplete="name" value=${name} onInput=${(e) => setName(e.target.value)} />
        </div>
        <button class="btn btn-primary btn-block" type="submit" disabled=${busy || !me.data}>Сохранить</button>
      </form>
      <button class="btn btn-block" type="button" onClick=${() => bus.emit("goto", "garage")}>
        Мои машины — в Гараже</button>
      <a class="btn btn-block" href=${"tel:" + CONFIG.phone.replace(/[^\d+]/g, "")}>Позвонить в сервис · ${CONFIG.phone}</a>
      <button class="btn btn-ghost btn-danger btn-block" type="button" onClick=${signOut}>Выйти</button>
    </div>
  </main>`;
}
