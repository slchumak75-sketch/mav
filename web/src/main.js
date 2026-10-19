import { mount } from "./app.js";

const root = document.getElementById("app");

mount(root).catch((err) => {
  root.innerHTML = `<section class="crash"><h1>Не удалось открыть ведомость</h1><pre>${String(
    err?.stack || err,
  )}</pre></section>`;
  console.error(err);
});
