/* Машины клиента: список в профиле и выбор машины при записи.

   Правила — первая машина основная, основная ровно одна, номер приводится
   к одной форме — живут на сервере (`garage`). Здесь только показ и ввод:
   вторая копия правил однажды разошлась бы с первой. */

import { CarField } from "app/auth";
import { api, ask, call, html, toast, useEffect, useState } from "app/lib";

export const carLabel = (car) => [car.title, car.plate].filter(Boolean).join(" · ") || "Автомобиль";

function carMeta(car) {
  return [
    car.year ? car.year + " г." : "",
    car.mileage != null ? new Intl.NumberFormat("ru-RU").format(car.mileage) + " км" : "",
  ].filter(Boolean).join(" · ");
}

/** Список машин с перезагрузкой. `null` — ещё грузим. */
export function useCars() {
  const [cars, setCars] = useState(null);
  async function reload() {
    const rows = await call(() => api.get("/garage/cars/"));
    setCars(rows || []);
    return rows || [];
  }
  useEffect(() => { reload(); }, []);
  return { cars, reload };
}

const toNumber = (value) => (String(value).trim() === "" ? null : Number(String(value).replace(/\s/g, "")));

/** Добавить или поправить машину. `full` — с годом, пробегом и VIN. */
export function CarForm({ car, full, onSaved, onCancel, submitLabel }) {
  const [title, setTitle] = useState(car ? car.title : "");
  const [modelId, setModelId] = useState(car ? car.model_id : null);
  const [plate, setPlate] = useState(car ? car.plate : "");
  const [year, setYear] = useState(car && car.year ? String(car.year) : "");
  const [mileage, setMileage] = useState(car && car.mileage != null ? String(car.mileage) : "");
  const [vin, setVin] = useState(car ? car.vin : "");
  const [busy, setBusy] = useState(false);
  const prefix = car ? "car-" + car.id : "car-new";

  async function save() {
    if (!title.trim() && !plate.trim()) {
      toast("Укажите марку или госномер.", "error");
      return;
    }
    const body = { title: title.trim(), plate: plate.trim(), model_id: modelId || null };
    if (full) Object.assign(body, { year: toNumber(year), mileage: toNumber(mileage), vin: vin.trim() });
    setBusy(true);
    const saved = await call(() => (car
      ? api.patch("/garage/cars/" + car.id + "/", body)
      : api.post("/garage/cars/", body)));
    setBusy(false);
    if (saved) onSaved(saved);
  }

  return html`<form class="stack" onSubmit=${(e) => { e.preventDefault(); save(); }}>
    <${CarField} id=${prefix + "-title"} value=${title}
      onChange=${(value, id) => { setTitle(value); setModelId(id || null); }} />
    <div class="field">
      <label for=${prefix + "-plate"}>Госномер</label>
      <input id=${prefix + "-plate"} autocapitalize="characters" placeholder="А123ВС174" value=${plate}
        onInput=${(e) => setPlate(e.target.value)} />
    </div>
    ${full && html`<div class="row" style="flex-wrap:nowrap">
      <div class="field" style="flex:1">
        <label for=${prefix + "-year"}>Год</label>
        <input id=${prefix + "-year"} inputmode="numeric" placeholder="2018" value=${year}
          onInput=${(e) => setYear(e.target.value)} />
      </div>
      <div class="field" style="flex:1">
        <label for=${prefix + "-mileage"}>Пробег, км</label>
        <input id=${prefix + "-mileage"} inputmode="numeric" placeholder="84 300" value=${mileage}
          onInput=${(e) => setMileage(e.target.value)} />
      </div>
    </div>
    <div class="field">
      <label for=${prefix + "-vin"}>VIN, если хотите</label>
      <input id=${prefix + "-vin"} autocapitalize="characters" maxlength="24" value=${vin}
        onInput=${(e) => setVin(e.target.value)} />
    </div>`}
    <div class="row" style="flex-wrap:nowrap">
      ${onCancel && html`<button class="btn btn-ghost" style="flex:1" type="button" onClick=${onCancel}>Отмена</button>`}
      <button class="btn btn-primary" style="flex:1" type="submit" disabled=${busy}>
        ${busy ? "Сохраняем…" : submitLabel || "Сохранить"}
      </button>
    </div>
  </form>`;
}

/** Какую машину везём: на шаге подтверждения записи.

    Основная выбрана сразу — чаще всего везут её, и лишнее касание не нужно.
    Машины нет — форма добавления сразу на месте, без перехода в профиль. */
export function CarPicker({ value, onChange }) {
  const { cars, reload } = useCars();
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    if (!cars || value) return;
    const primary = cars.find((c) => c.is_primary) || cars[0];
    if (primary) onChange(primary.id);
  }, [cars]);

  if (cars === null) return html`<p class="muted">Загружаем ваши машины…</p>`;

  async function added(car) {
    setAdding(false);
    await reload();
    onChange(car.id);
  }

  if (!cars.length || adding) {
    return html`<div class="card pad stack">
      <b>${cars.length ? "Другая машина" : "Какую машину привезёте?"}</b>
      <p class="muted">Мастер будет знать, что заезжает. Машина сохранится в профиле.</p>
      <${CarForm} onSaved=${added} submitLabel="Добавить"
        onCancel=${cars.length ? () => setAdding(false) : null} />
    </div>`;
  }

  return html`<div class="stack-sm" role="group" aria-label="Автомобиль">
    ${cars.map((car) => html`<button class="choice" type="button" key=${car.id}
      aria-pressed=${String(car.id === value)} onClick=${() => onChange(car.id)}>
      <span class="choice-body">
        <span class="choice-title">${car.title || "Автомобиль"}</span>
        <span class="choice-meta">${[car.plate, car.is_primary ? "основная" : ""].filter(Boolean).join(" · ")}</span>
      </span>
    </button>`)}
    <button class="btn btn-ghost btn-block" type="button" onClick=${() => setAdding(true)}>+ Другая машина</button>
  </div>`;
}

/** Мои машины: в профиле. */
export function Garage() {
  const { cars, reload } = useCars();
  const [editing, setEditing] = useState(null); // id машины, "new" или null

  async function makePrimary(car) {
    if (await call(() => api.post("/garage/cars/" + car.id + "/make-primary/", {}))) reload();
  }

  async function remove(car) {
    const yes = await ask({
      title: "Удалить " + carLabel(car) + "?",
      text: "Прошлые записи на эту машину останутся в истории.",
      confirmLabel: "Удалить", danger: true,
    });
    if (!yes) return;
    if (await call(() => api.del("/garage/cars/" + car.id + "/"))) {
      toast("Машина удалена", "ok");
      reload();
    }
  }

  function saved() {
    setEditing(null);
    reload();
  }

  if (cars === null) return html`<p class="muted">Загружаем…</p>`;

  return html`<div class="stack-lg">
    ${!cars.length && editing !== "new" && html`<div class="empty-state">
      <b>Добавьте машину</b>
      <p>Мастер будет знать, что заезжает, а запись подставит её сама.</p>
    </div>`}
    ${cars.map((car) => editing === car.id
      ? html`<div class="card pad" key=${car.id}>
          <${CarForm} car=${car} full onSaved=${saved} onCancel=${() => setEditing(null)} />
        </div>`
      : html`<article class="card pad" key=${car.id}>
          <div class="booking-head">
            <span class="booking-when">${car.title || "Автомобиль"}</span>
            ${car.is_primary && html`<span class="badge badge-accent">Основная</span>`}
          </div>
          <div class="booking-lines">
            ${car.plate && html`<span class="mono">${car.plate}</span>`}
            ${carMeta(car) && html`<span>${carMeta(car)}</span>`}
          </div>
          <div class="row" style="margin-top:12px">
            <button class="btn btn-sm" type="button" onClick=${() => setEditing(car.id)}>Изменить</button>
            ${!car.is_primary && html`<button class="btn btn-sm" type="button" onClick=${() => makePrimary(car)}>Сделать основной</button>`}
            <span class="spacer"></span>
            <button class="btn btn-sm btn-ghost btn-danger" type="button" onClick=${() => remove(car)}>Удалить</button>
          </div>
        </article>`)}
    ${editing === "new"
      ? html`<div class="card pad">
          <${CarForm} full onSaved=${saved} onCancel=${() => setEditing(null)} submitLabel="Добавить" />
        </div>`
      : html`<button class="btn btn-block" type="button" onClick=${() => setEditing("new")}>+ Добавить машину</button>`}
  </div>`;
}
