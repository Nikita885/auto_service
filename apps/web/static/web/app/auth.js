/* Вход по номеру и знакомство — те же шаги, что в приложении под Android. */

import { InstallButton } from "app/install";
import {
  CONFIG, api, call, errorText, formatPhone, html, invite, phoneComplete, toast,
  useEffect, useRef, useState,
} from "app/lib";
import { canScan, scanInvite } from "app/scan";

/** Итог кода приглашения, пришедшего вместе со входом. */
export function reportInvite(result) {
  if (!result) return;
  invite.done();
  if (result.status === "attached") {
    toast("Вы в команде: " + result.inviter_name + ". Ваши замены будут приносить баллы пригласившему.", "ok", "Приглашение принято");
  } else if (result.code !== "referral_already_attached") {
    toast(result.message || "Код приглашения не подошёл.", "error");
  }
}

export function Auth({ onSignedIn }) {
  const [step, setStep] = useState("phone");
  const [phone, setPhone] = useState("+7");
  const [code, setCode] = useState("");
  const [hint, setHint] = useState("");
  const [busy, setBusy] = useState(false);
  const [resendIn, setResendIn] = useState(0);
  const [pending, setPending] = useState(invite.get());
  const codeRef = useRef(null);

  async function scan() {
    const code = await scanInvite();
    if (!code) return;
    invite.set(code);
    setPending(code);
    toast("Код " + code + " сохранён — применится при входе.", "ok");
  }

  useEffect(() => {
    if (resendIn <= 0) return undefined;
    const t = setTimeout(() => setResendIn((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [resendIn]);

  useEffect(() => { if (step === "code" && codeRef.current) codeRef.current.focus(); }, [step]);

  async function requestCode() {
    if (!phoneComplete(phone) || busy) return;
    setBusy(true);
    const data = await call(() => api.request("/auth/otp/request/", {
      method: "POST", body: { phone }, auth: false,
    }));
    setBusy(false);
    if (!data) return;
    setStep("code");
    setResendIn(data.resend_after_seconds || 60);
    // Код в ответе приходит только номерам из OTP_DEBUG_PHONES — это
    // временная замена SMS, пока шлюз не заработал.
    if (data.debug_code) {
      setCode(data.debug_code);
      setHint("Код пришёл без SMS (тестовый номер) и уже подставлен.");
    } else {
      setHint("");
    }
  }

  async function verify() {
    if (code.trim().length < 4 || busy) return;
    setBusy(true);
    try {
      // Код приглашения из ссылки или QR уходит вместе со входом — сервер
      // привяжет человека сам, вводить ничего не придётся.
      const data = await api.request("/auth/otp/verify/", {
        method: "POST", body: { phone, code: code.trim(), invite: invite.get() }, auth: false,
      });
      if (data.user.role !== "client") {
        toast("Этот номер принадлежит сотруднику. Рабочее место мастера — на сайте, в разделе /master/.", "error");
        return;
      }
      api.store.save(data.access, data.refresh);
      reportInvite(data.invite);
      onSignedIn(data.user, data.is_new_user);
    } catch (err) {
      toast(errorText(err), "error");
    } finally {
      setBusy(false);
    }
  }

  return html`<main class="screen screen-plain">
    <div class="auth">
      <div class="auth-brand">
        <img src=${CONFIG.icon} alt="" />
        <b>${CONFIG.company}</b>
      </div>

      ${step === "phone" ? html`
        <div>
          <h1>Замена масла<br /><span>без очереди</span></h1>
          <p class="muted" style="margin-top:8px">Вход по номеру телефона. Пароль не нужен — пришлём код в SMS.</p>
        </div>
        <${InstallButton} block=${true} />
        <form class="stack" onSubmit=${(e) => { e.preventDefault(); requestCode(); }}>
          <div class="field">
            <label for="phone">Телефон</label>
            <input id="phone" type="tel" inputmode="tel" autocomplete="tel" value=${phone}
              onInput=${(e) => setPhone(formatPhone(e.target.value))} />
          </div>
          <button class="btn btn-primary btn-block" type="submit" disabled=${!phoneComplete(phone) || busy}>
            ${busy ? "Отправляем…" : "Получить код"}
          </button>
        </form>
        ${pending
          ? html`<p class="invite-note">Код приглашения <b>${pending}</b> применится автоматически при входе.</p>`
          : canScan() && html`<button class="btn btn-ghost btn-block" type="button" onClick=${scan}>
              Меня пригласили — сканировать QR-код</button>`}
      ` : html`
        <div>
          <h1>Введите код</h1>
          <p class="muted" style="margin-top:8px">Отправили SMS на ${phone}</p>
        </div>
        <form class="stack" onSubmit=${(e) => { e.preventDefault(); verify(); }}>
          <div class="field">
            <label for="code">Код из SMS</label>
            <input id="code" ref=${codeRef} class="otp-input" inputmode="numeric" maxlength="8"
              autocomplete="one-time-code" value=${code}
              onInput=${(e) => setCode(e.target.value.replace(/\D/g, ""))} />
          </div>
          ${hint && html`<p class="hint">${hint}</p>`}
          <button class="btn btn-primary btn-block" type="submit" disabled=${code.length < 4 || busy}>
            ${busy ? "Проверяем…" : "Войти"}
          </button>
          <button class="btn btn-ghost btn-block" type="button" disabled=${resendIn > 0 || busy} onClick=${requestCode}>
            ${resendIn > 0 ? "Отправить повторно через " + resendIn + " с" : "Отправить код ещё раз"}
          </button>
          <button class="btn btn-ghost btn-block" type="button" onClick=${() => { setStep("phone"); setCode(""); }}>
            Изменить номер
          </button>
        </form>
      `}
      <p class="legal">Продолжая, вы соглашаетесь с обработкой персональных данных.</p>
    </div>
  </main>`;
}

/* ------------------------------------------------------------ машина */

/** Поле «марка и модель» с подсказками из справочника.

    Подсказка, а не ограничение: свою машину можно вписать как есть —
    справочник полным не бывает, и упираться в него на регистрации значит
    терять клиента. */
export function CarField({ value, onChange }) {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const timer = useRef(null);

  function onInput(e) {
    const q = e.target.value;
    onChange(q);
    clearTimeout(timer.current);
    if (q.trim().length < 2) { setItems([]); return; }
    timer.current = setTimeout(async () => {
      try {
        const found = await api.get("/cars/search/?q=" + encodeURIComponent(q.trim()));
        setItems((found || []).slice(0, 6));
        setOpen(true);
      } catch (err) {
        setItems([]);
      }
    }, 250);
  }

  return html`<div class="field">
    <label for="car">Марка и модель</label>
    <input id="car" autocomplete="off" placeholder="Например, Kia Rio" value=${value}
      onInput=${onInput} onBlur=${() => setTimeout(() => setOpen(false), 150)} />
    ${open && items.length > 0 && html`<div class="suggest">
      ${items.map((item) => html`<button type="button" key=${item.id}
        onMouseDown=${(e) => e.preventDefault()}
        onClick=${() => { onChange(item.title); setOpen(false); }}>${item.title}</button>`)}
    </div>`}
  </div>`;
}

/* ---------------------------------------------------------- знакомство */

export function Onboarding({ user, onDone }) {
  const [name, setName] = useState(user.full_name || "");
  const [car, setCar] = useState(user.car_model || "");
  const [plate, setPlate] = useState(user.car_plate || "");
  const [code, setCode] = useState(invite.get());

  async function scan() {
    const found = await scanInvite();
    if (found) setCode(found);
  }
  const [busy, setBusy] = useState(false);

  async function save(skip) {
    if (!skip && !name.trim()) {
      toast("Без имени мастер не поймёт, кто приехал.", "error");
      return;
    }
    setBusy(true);
    let me = user;
    if (!skip) {
      me = await call(() => api.patch("/auth/me/", {
        full_name: name.trim(), car_model: car.trim(), car_plate: plate.trim().toUpperCase(),
      }));
      if (!me) { setBusy(false); return; }
    }
    if (code.trim()) {
      try {
        await api.post("/referral/attach/", { code: code.trim() });
        invite.done();
        toast("Приглашение принято", "ok");
      } catch (err) {
        invite.done();
        if (err.code !== "referral_already_attached") {
          toast("Код приглашения не подошёл: " + errorText(err) + " Профиль сохранён.", "error");
        }
      }
    }
    setBusy(false);
    onDone(me);
  }

  return html`<main class="screen screen-plain">
    <div class="screen-head">
      <h1>Давайте познакомимся</h1>
      <p>Имя и машину увидит мастер, когда вы приедете. Это займёт полминуты.</p>
    </div>
    <form class="card pad stack" onSubmit=${(e) => { e.preventDefault(); save(false); }}>
      <div class="field">
        <label for="name">Как вас зовут</label>
        <input id="name" autocomplete="name" value=${name} onInput=${(e) => setName(e.target.value)} />
      </div>
      <${CarField} value=${car} onChange=${setCar} />
      <div class="field">
        <label for="plate">Госномер</label>
        <input id="plate" autocapitalize="characters" placeholder="А123ВС174" value=${plate}
          onInput=${(e) => setPlate(e.target.value)} />
      </div>
      <div class="field">
        <label for="invite">Код приглашения, если есть</label>
        <div class="row" style="flex-wrap:nowrap">
          <input id="invite" style="flex:1" autocapitalize="characters" placeholder="Код приглашения" value=${code}
            onInput=${(e) => setCode(e.target.value.toUpperCase())} />
          ${canScan() && html`<button class="btn" type="button" onClick=${scan}>QR</button>`}
        </div>
        <span class="hint">Если вас пригласил знакомый — введите его код. Позже это можно сделать в «Бонусах».</span>
      </div>
      <button class="btn btn-primary btn-block" type="submit" disabled=${busy}>Готово</button>
      <button class="btn btn-ghost btn-block" type="button" disabled=${busy} onClick=${() => save(true)}>Заполнить позже</button>
    </form>
  </main>`;
}
