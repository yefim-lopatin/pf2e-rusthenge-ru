const MODULE_ID = "pf2e-rusthenge-ru";
const SOURCE_MODULE_ID = "pf2e-rusthenge";
const TESTED_SOURCE_VERSION = "14.1.0";

Hooks.once("babele.init", (babele) => {
  // Babele фиксирует сопоставление в момент регистрации переводимого
  // компендиума. Поэтому описания PF2e и вложенные предметы задаются здесь
  // явно: модуль не должен зависеть от того, успел ли pf2e-ru зарегистрировать
  // своё глобальное сопоставление раньше нас.
  babele.registerMapping({
    Actor: {
      blurb: "system.details.blurb",
      description: "system.details.publicNotes",
      descriptionGM: "system.details.privateNotes",
      language: "system.details.languages.details",
      senses: "system.perception.details",
      descriptionHazard: "system.details.description",
      disable: "system.details.disable",
      reset: "system.details.reset",
      routine: "system.details.routine",
      stealth: "system.attributes.stealth.details",
      hp: "system.attributes.hp.details",
      ac: "system.attributes.ac.details",
      allSaves: "system.attributes.allSaves.value",
      speed: "system.attributes.speed.details",
      willSave: "system.saves.will.saveDetail",
      skillAcrobatics: "system.skills.acrobatics.special.0.label",
      skillAthletics: "system.skills.athletics.special.0.label",
      skillCrafting: "system.skills.crafting.special.0.label",
      skillStealth: "system.skills.stealth.special.0.label",
      skillThievery: "system.skills.thievery.special.0.label",
      items: {
        path: "items",
        converter: "document",
        documentType: "Item",
        cardinality: "many"
      }
    },
    Item: {
      gm: "system.description.gm",
      unidentifiedName: "system.identification.unidentified.name",
      unidentifiedDescription: "system.identification.unidentified.data.description.value",
      ruleLabel0: "system.rules.0.label"
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
