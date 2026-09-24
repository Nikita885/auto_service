/* Профиль: имя и машина, которые видит мастер, и выход. */

import { CarField } from "app/auth";
import { InstallButton } from "app/install";
import { CONFIG, LoadError, api, ask, bus, call, html, toast, useEffect, useLoad, useState } from "app/lib";

export function Profile() {
  const me = useLoad(() => api.get("/auth/me/"));
  const [name, setName] = useState("");
  const [car, setCar] = useState("");
  const [plate, setPlate] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!me.data) return;
    setName(me.data.full_name || "");
    setCar(me.data.car_model || "");
    setPlate(me.data.car_plate || "");
  }, [me.data]);

  async function save() {
    setBusy(true);
    const ok = await call(() => api.patch("/auth/me/", {
      full_name: name.trim(), car_model: car.trim(), car_plate: plate.trim().toUpperCase(),
    }));
    setBusy(false);
    if (ok) toast("Профиль сохранён", "ok");
  }

  async function signOut() {
    const yes = await ask({
      title: "Выйти из аккаунта?",
      text: "Войти обратно можно по коду из SMS.",
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
      <p>Имя и автомобиль видит мастер — так он понимает, что заезжаете именно вы.</p>
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
        <${CarField} value=${car} onChange=${setCar} />
        <div class="field">
          <label for="p-plate">Госномер</label>
          <input id="p-plate" autocapitalize="characters" value=${plate} onInput=${(e) => setPlate(e.target.value)} />
        </div>
        <button class="btn btn-primary btn-block" type="submit" disabled=${busy || !me.data}>Сохранить</button>
      </form>
      <${InstallButton} block=${true} />
      <a class="btn btn-block" href=${"tel:" + CONFIG.phone.replace(/[^\d+]/g, "")}>Позвонить в сервис · ${CONFIG.phone}</a>
      <button class="btn btn-ghost btn-danger btn-block" type="button" onClick=${signOut}>Выйти</button>
    </div>
  </main>`;
}
