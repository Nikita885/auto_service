/* Вход по номеру и знакомство — те же шаги, что в приложении под Android. */

import {
  CONFIG, api, call, errorText, formatPhone, html, invite, isIos, isStandalone,
  phoneComplete, toast, useEffect, useRef, useState,
} from "app/lib";

/** Подсказка «добавьте на экран „Домой“» — только Safari на iPhone.

    Safari не умеет сам предлагать установку, а push-уведомления и запуск
    без рамки браузера на iPhone работают только у установленного
    приложения. Показываем до входа: у установленного приложения своё
    хранилище, и вход из Safari туда не переедет. */
export function InstallHint() {
  if (!isIos() || isStandalone()) return null;
  return html`<div class="install">
    <span dangerouslySetInnerHTML=${{ __html: window.App.icon("info", 22) }}></span>
    <div>
      <b>Установите приложение на iPhone.</b> Нажмите «Поделиться» (квадрат
      со стрелкой вверх) внизу Safari и выберите «На экран „Домой“».
      Войдите уже из приложения — так уведомления будут приходить.
    </div>
  </div>`;
}

export function Auth({ onSignedIn }) {
  const [step, setStep] = useState("phone");
  const [phone, setPhone] = useState("+7");
  const [code, setCode] = useState("");
  const [hint, setHint] = useState("");
  const [busy, setBusy] = useState(false);
  const [resendIn, setResendIn] = useState(0);
  const codeRef = useRef(null);

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
      const data = await api.request("/auth/otp/verify/", {
        method: "POST", body: { phone, code: code.trim() }, auth: false,
      });
      if (data.user.role !== "client") {
        toast("Этот номер принадлежит сотруднику. Рабочее место мастера — на сайте, в разделе /master/.", "error");
        return;
      }
      api.store.save(data.access, data.refresh);
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
        <${InstallHint} />
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
        invite.clear();
        toast("Приглашение принято", "ok");
      } catch (err) {
        toast("Код приглашения не подошёл: " + errorText(err) + " Профиль сохранён.", "error");
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
        <input id="invite" autocapitalize="characters" placeholder="Код приглашения" value=${code}
          onInput=${(e) => setCode(e.target.value.toUpperCase())} />
        <span class="hint">Если вас пригласил знакомый — введите его код. Позже это можно сделать в «Бонусах».</span>
      </div>
      <button class="btn btn-primary btn-block" type="submit" disabled=${busy}>Готово</button>
      <button class="btn btn-ghost btn-block" type="button" disabled=${busy} onClick=${() => save(true)}>Заполнить позже</button>
    </form>
  </main>`;
}
