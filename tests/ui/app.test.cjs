const { test } = require("node:test");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const fs = require("node:fs/promises");
const base = process.env.UI_BASE_URL;

const point = { id: "p1", name: "Сервис на Ленина", address: "ул. Ленина, 10", phone: "+73519481212", timezone: "Asia/Yekaterinburg", opens_at: "09:00:00", closes_at: "20:00:00", workdays: [0,1,2,3,4,5,6] };
const car = { id: "c1", title: "Kia Rio", plate: "А123ВС174", mileage: 65000, is_primary: true };
const service = { id: "s1", name: "Проверка автомобиля", description: "Осмотр и консультация мастера" };
const category = { id: "k1", name: "Обслуживание", services: [service], allow_on_site: true, journal_kind: "service" };
const user = { id: "u1", full_name: "Алексей", phone: "+79000000123", role: "client" };
const day = "2026-11-18";
const slot = { start_at: day + "T07:30:00Z", local_time: "12:30" };

test("mobile layouts, garage and booking flow", { skip: !base, timeout: 90000 }, async (t) => {
  const browser = await chromium.launch({ headless: true, ...(process.env.PW_EXECUTABLE ? { executablePath: process.env.PW_EXECUTABLE } : {}) });
  await fs.mkdir("test-results", { recursive: true });
  try {
    for (const width of [320, 390, 430]) {
      await t.test(`${width}px`, async () => {
        const context = await browser.newContext({ viewport: { width, height: 844 }, serviceWorkers: "block" });
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", e => errors.push(e.message));
        await page.addInitScript(() => { localStorage.setItem("client.access", "ui-test"); localStorage.setItem("client.refresh", "ui-test"); });
        let draft = null;
        let showBooking = false;
        await page.route("**/api/v1/**", async route => {
          const req = route.request();
          const url = new URL(req.url());
          const p = url.pathname.replace("/api/v1", "");
          let data = null;
          if (p === "/auth/me/") data = user;
          else if (p === "/garage/cars/") data = [car];
          else if (p === "/garage/cars/c1/summary/") data = { car, mileage: 65000, reminders: [], recent: [], month: { total: 0, by_kind: {} }, year: { total: 0, by_kind: {} }, fuel: {} };
          else if (p === "/referral/") data = { enabled: false };
          else if (p === "/service-points/") data = [point];
          else if (p.endsWith("/categories/")) data = [category];
          else if (p.endsWith("/services/")) data = [service];
          else if (p.endsWith("/slots/")) data = { available_days: [day], slots: [slot] };
          else if (p === "/assistant/") data = { available: false };
          else if (p === "/bookings/") data = { results: showBooking && url.searchParams.get("scope") === "upcoming" ? [{
            id: "b1", code: "AB1234", status: "pending", start_at: slot.start_at,
            service_point: point, service_title: service.name, category_title: category.name,
            category_kind: "service", car_model: car.title, car_plate: car.plate,
            can_reschedule: true, can_cancel: true,
          }] : [] };
          else if (p === "/bookings/drafts/current/") data = draft;
          else if (p === "/bookings/drafts/" && req.method() === "POST") data = draft = { id: "d1", step: "started", seconds_left: 300, is_alive: true, next_action: "select_point" };
          else if (p.endsWith("/select-point/")) data = draft = { ...draft, service_point: point, next_action: "select_category" };
          else if (p.endsWith("/select-category/")) data = draft = { ...draft, service_category: category, next_action: "select_service" };
          else if (p.endsWith("/select-service/")) data = draft = { ...draft, service, next_action: "select_slot" };
          else if (p.endsWith("/select-slot/")) data = draft = { ...draft, slot_start: slot.start_at, next_action: "confirm" };
          else throw new Error(`Unexpected UI request ${req.method()} ${p}`);
          await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
        });
        await page.goto(base + "/app/");
        await page.getByRole("button", { name: "Записаться в сервис", exact: true }).waitFor();
        await page.screenshot({ path: `test-results/home-${width}.png` });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.getByRole("button", { name: "Гараж", exact: true }).click();
        await page.getByRole("button", { name: /Добавить запись/ }).waitFor();
        assert.equal(await page.getByText("Расходы автомобиля", { exact: true }).count(), 0);
        await page.screenshot({ path: `test-results/garage-${width}.png` });
        showBooking = true;
        await page.getByRole("button", { name: "Главная", exact: true }).click();
        await page.getByRole("link", { name: "Построить маршрут" }).waitFor();
        await page.screenshot({ path: `test-results/booking-${width}.png` });
        showBooking = false;
        await page.reload();
        await page.getByRole("button", { name: "Записаться в сервис", exact: true }).click();
        await page.getByRole("button", { name: /Сервис на Ленина/ }).click();
        await page.getByRole("button", { name: /Обслуживание/ }).last().click();
        await page.screenshot({ path: `test-results/service-${width}.png` });
        await page.getByRole("button", { name: /Проверка автомобиля/ }).click();
        await page.getByRole("button", { name: "12:30", exact: true }).click();
        await page.screenshot({ path: `test-results/time-${width}.png` });
        await page.getByRole("button", { name: /Проверить запись/ }).click();
        await page.getByRole("button", { name: "Подтвердить запись", exact: true }).waitFor();
        await page.screenshot({ path: `test-results/confirm-${width}.png` });
        // Nested sheet must close first and keep the booking form open.
        await page.evaluate(async () => {
          const { Sheet, html, render, useState } = await import("/static/web/app/lib.js");
          const host = document.createElement("div");
          document.body.append(host);
          function Nested() {
            const [open, setOpen] = useState(true);
            return html`<${Sheet} title="Внешнее окно" onClose=${() => render(null, host)}>
              ${open && html`<${Sheet} title="Внутреннее окно" onClose=${() => setOpen(false)}>Проверка</${Sheet}>`}
            </${Sheet}>`;
          }
          render(html`<${Nested} />`, host);
        });
        await page.getByRole("dialog", { name: "Внутреннее окно" }).waitFor();
        await page.keyboard.press("Escape");
        await page.getByRole("dialog", { name: "Внутреннее окно" }).waitFor({ state: "detached" });
        assert.equal(await page.locator('[role="dialog"]').count(), 2);
        assert.deepEqual(errors, []);
        await context.close();
      });
    }
    await t.test("landing and public privacy on mobile and desktop", async () => {
      for (const width of [375, 1440]) {
        const page = await browser.newPage({ viewport: { width, height: 1000 }, reducedMotion: "reduce" });
        await page.goto(base + "/");
        await page.locator("#services").waitFor();
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.screenshot({ path: `test-results/landing-${width}.png`, fullPage: true });
        await page.locator("#services").screenshot({ path: `test-results/services-${width}.png` });
        await page.goto(base + "/delete-account/");
        await page.getByRole("heading", { name: "Удаление аккаунта и данных" }).waitFor();
        await page.close();
      }
    });
  } finally { await browser.close(); }
});
