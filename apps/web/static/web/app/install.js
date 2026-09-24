/* Установка веб-приложения на главный экран — под устройство.

   iPhone: Safari не умеет предлагать установку сам, поэтому кнопка
   открывает пошаговую инструкцию. Android (Chrome): браузер присылает
   событие `beforeinstallprompt`, и кнопка вызывает системное окно
   установки. Уже установленному приложению (запущенному с главного экрана)
   кнопка не показывается вовсе — ставить нечего. */

import { html, isIos, isStandalone, render, useEffect, useState } from "app/lib";

let deferredPrompt = null;
const waiters = new Set();

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  deferredPrompt = event;
  waiters.forEach((fn) => fn());
});
window.addEventListener("appinstalled", () => {
  deferredPrompt = null;
  waiters.forEach((fn) => fn());
});

/** Можно ли что-то предложить: iPhone в Safari или Android с готовым окном. */
function installable() {
  if (isStandalone()) return false;
  return isIos() || Boolean(deferredPrompt);
}

function ShareIcon() {
  return html`<svg class="share-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M12 3v12M8 7l4-4 4 4"/><path d="M6 11H5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-8a1 1 0 0 0-1-1h-1"/>
  </svg>`;
}

function Sheet({ onClose }) {
  return html`<div class="modal-backdrop" onClick=${(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <div class="modal install-sheet" role="dialog" aria-modal="true" aria-labelledby="install-title">
      <div class="modal-title" id="install-title">Установите приложение на iPhone</div>
      <p class="modal-sub">Три касания — и оно будет на главном экране, как обычное приложение.</p>
      <ol class="install-steps">
        <li><span class="step-n">1</span><span>Нажмите «Поделиться» <${ShareIcon} /> внизу экрана Safari</span></li>
        <li><span class="step-n">2</span><span>Прокрутите и выберите <b>«На экран „Домой“»</b></span></li>
        <li><span class="step-n">3</span><span>Нажмите <b>«Добавить»</b> в правом верхнем углу</span></li>
      </ol>
      <p class="hint">Открывайте приложение с главного экрана — так приходят уведомления, а вход сохраняется.</p>
      <div class="modal-actions"><button class="btn btn-primary" type="button" onClick=${onClose}>Понятно</button></div>
      <div class="install-arrow" aria-hidden="true">↓</div>
    </div>
  </div>`;
}

/** Показать инструкцию для iPhone. */
export function openInstallSheet() {
  const host = document.createElement("div");
  document.body.append(host);
  const close = () => { render(null, host); host.remove(); };
  render(html`<${Sheet} onClose=${close} />`, host);
}

/** Кнопка «Установить приложение» — только там, где установка возможна. */
export function InstallButton({ block }) {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((n) => n + 1);
    waiters.add(fn);
    return () => waiters.delete(fn);
  }, []);

  if (!installable()) return null;

  async function install() {
    if (deferredPrompt) {
      const prompt = deferredPrompt;
      deferredPrompt = null;
      prompt.prompt();
      await prompt.userChoice.catch(() => null);
      waiters.forEach((fn) => fn());
      return;
    }
    openInstallSheet();
  }

  return html`<button class=${"btn btn-primary install-btn" + (block ? " btn-block" : "")} type="button" onClick=${install}>
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg>
    Установить приложение
  </button>`;
}

/** Открыли по ссылке «Установить» с сайта — сразу показываем инструкцию. */
export function autoOpenFromLink() {
  const params = new URLSearchParams(location.search);
  if (params.get("install") === "1" && isIos() && !isStandalone()) {
    setTimeout(openInstallSheet, 400);
  }
}
