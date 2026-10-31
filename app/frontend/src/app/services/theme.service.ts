import { Injectable, signal } from '@angular/core';

export interface ColourScheme {
  id: string;
  label: string;
  /** Class applied to <body> for this scheme, '' for none. */
  bodyClass: string;
  /** Stub palette: shown in the list but not selectable yet. */
  disabled?: boolean;
}

// Kept in sync by hand with the SCHEME_CLASSES map in index.html's bootstrap
// script, which must apply the same classes before Angular/this file exists.
// Each scheme (including its --tag-* status colours) is defined entirely in
// CSS, keyed off bodyClass — there is no per-scheme override layer here.
export const COLOUR_SCHEMES: ColourScheme[] = [
  { id: 'ubc', label: 'UBC', bodyClass: '' },
  { id: 'ugly', label: 'Ugly', bodyClass: 'scheme-ugly' },
  { id: 'dark', label: 'Dark', bodyClass: 'dark-mode' },
  { id: 'ocean', label: 'Ocean', bodyClass: 'scheme-ocean' },
  { id: 'slate', label: 'Slate', bodyClass: 'scheme-slate' },
  { id: 'amethyst', label: 'Amethyst', bodyClass: 'scheme-amethyst' },
];

const DEFAULT_SCHEME_ID = 'ubc';
const ACTIVE_SCHEME_KEY = 'theme:activeScheme';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  private schemesById = new Map(COLOUR_SCHEMES.map((s) => [s.id, s]));

  readonly schemes = COLOUR_SCHEMES;

  private _activeSchemeId = signal<string>(this.readInitialSchemeId());
  readonly activeSchemeId = this._activeSchemeId.asReadonly();

  constructor() {
    // Defensive re-apply: index.html's inline bootstrap script already
    // applied the correct class before Angular booted. This just
    // guarantees the DOM matches service state in contexts without that
    // script (e.g. unit tests that construct the service directly).
    this.applySchemeToDom(this._activeSchemeId());
  }

  selectScheme(id: string): void {
    const scheme = this.schemesById.get(id);
    if (!scheme || scheme.disabled) return;
    this._activeSchemeId.set(id);
    localStorage.setItem(ACTIVE_SCHEME_KEY, id);
    this.applySchemeToDom(id);
  }

  private applySchemeToDom(id: string): void {
    const body = document.body;
    COLOUR_SCHEMES.forEach((s) => {
      if (s.bodyClass) body.classList.remove(s.bodyClass);
    });
    const scheme = this.schemesById.get(id);
    if (scheme?.bodyClass) body.classList.add(scheme.bodyClass);
  }

  private readInitialSchemeId(): string {
    const stored = localStorage.getItem(ACTIVE_SCHEME_KEY);
    return stored && this.schemesById.has(stored) ? stored : DEFAULT_SCHEME_ID;
  }
}
