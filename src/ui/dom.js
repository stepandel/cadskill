// Two helpers every page module uses.
export const $ = (id) => document.getElementById(id);
export const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
