(() => {
  const storageKey = "onec-hbk-bsl-doc-language";
  const projectRoot = "/1c_hbk_bsl/";

  function currentLanguage() {
    return document.documentElement.lang.toLowerCase().startsWith("en") ? "en" : "ru";
  }

  function translatedPath(targetLanguage) {
    let path = window.location.pathname;
    const rootIndex = path.indexOf(projectRoot);
    const prefix = rootIndex < 0 ? "/" : path.slice(0, rootIndex + projectRoot.length);
    let relative = rootIndex < 0 ? path.slice(1) : path.slice(prefix.length);
    if (relative.startsWith("en/")) {
      relative = relative.slice(3);
    }
    return targetLanguage === "en" ? `${prefix}en/${relative}` : `${prefix}${relative}`;
  }

  function rememberManualChoice() {
    document.querySelectorAll("a[hreflang]").forEach((link) => {
      const language = link.getAttribute("hreflang");
      if (language === "ru" || language === "en") {
        const target = translatedPath(language);
        if (target) {
          link.setAttribute("href", `${target}${window.location.search}${window.location.hash}`);
        }
      }
      link.addEventListener("click", () => {
        if (language === "ru" || language === "en") {
          window.localStorage.setItem(storageKey, language);
        }
      });
    });
  }

  function hideInactiveTableOfContents() {
    const language = currentLanguage();
    document.querySelectorAll('.md-nav--secondary a[href^="#"]').forEach((link) => {
      const rawId = link.getAttribute("href").slice(1);
      const target = document.getElementById(decodeURIComponent(rawId));
      const hiddenLanguage =
        target?.closest(".doc-lang-en") && language === "ru"
          ? "en"
          : target?.closest(".doc-lang-ru") && language === "en"
            ? "ru"
            : null;
      if (hiddenLanguage || target?.closest(".engineering-contract")) {
        const item = link.closest("li");
        if (item) {
          item.hidden = true;
        }
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    rememberManualChoice();
    hideInactiveTableOfContents();

    const stored = window.localStorage.getItem(storageKey);
    const preferred = stored || (navigator.language.toLowerCase().startsWith("ru") ? "ru" : "en");
    if ((preferred === "ru" || preferred === "en") && preferred !== currentLanguage()) {
      const target = translatedPath(preferred);
      if (target) {
        window.location.replace(`${target}${window.location.search}${window.location.hash}`);
      }
    }

    if (window.location.hash) {
      const target = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
      const details = target?.closest("details");
      if (details) {
        details.open = true;
      }
    }
  });
})();
