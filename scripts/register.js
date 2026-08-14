const MODULE_ID = "pf2e-rusthenge-ru";
const SOURCE_MODULE_ID = "pf2e-rusthenge";
const TESTED_SOURCE_VERSION = "14.1.0";

Hooks.once("babele.init", (babele) => {
  // PF2e хранит отдельные заметки ведущего вне стандартного поля Babele.
  // Регистрируем только недостающие текстовые пути; команды макросов и другие
  // технические данные официального приключения это сопоставление не затрагивает.
  babele.registerMapping({
    Actor: {
      descriptionGM: "system.details.privateNotes"
    },
    Item: {
      gm: "system.description.gm"
    }
  });

  babele.register({
    module: MODULE_ID,
    lang: "ru",
    dir: "translations"
  });
});

Hooks.once("ready", () => {
  const module = game.modules.get(MODULE_ID);
  if (module) {
    module.api = Object.freeze({
      sourceModule: SOURCE_MODULE_ID,
      testedSourceVersion: TESTED_SOURCE_VERSION
    });
  }

  if (!game.user?.isGM) return;

  const source = game.modules.get(SOURCE_MODULE_ID);
  if (!source?.active) {
    ui.notifications.error(
      "Перевод «Растхендж» не загружен: включите официальный модуль pf2e-rusthenge."
    );
    return;
  }

  if (source.version !== TESTED_SOURCE_VERSION) {
    ui.notifications.warn(
      `Перевод «Растхендж» проверен с версией ${TESTED_SOURCE_VERSION}; установлена ${source.version}. Перед импортом проверьте журнал и ссылки.`
    );
  }
});
