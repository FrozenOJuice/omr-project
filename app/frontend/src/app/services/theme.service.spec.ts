import { TestBed } from '@angular/core/testing';
import { ThemeService } from './theme.service';

describe('ThemeService', () => {
  let service: ThemeService;

  beforeEach(() => {
    localStorage.removeItem('theme:activeScheme');
    document.body.classList.remove('dark-mode', 'scheme-ugly');

    TestBed.configureTestingModule({});
    service = TestBed.inject(ThemeService);
  });

  afterEach(() => {
    localStorage.removeItem('theme:activeScheme');
    document.body.classList.remove('dark-mode', 'scheme-ugly');
  });

  it('should default to the ubc scheme when nothing is stored', () => {
    expect(service.activeSchemeId()).toBe('ubc');
    // ubc is now the :root default (bodyClass ''), so no scheme-* class is added.
    expect(document.body.classList.contains('scheme-ubc')).toBe(false);
  });

  it('should fall back to the ubc scheme when the stored id is unrecognized', () => {
    localStorage.setItem('theme:activeScheme', 'not-a-real-scheme');
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({});
    const fresh = TestBed.inject(ThemeService);
    expect(fresh.activeSchemeId()).toBe('ubc');
  });

  it('should apply the dark-mode body class when selecting the dark scheme', () => {
    service.selectScheme('dark');
    expect(service.activeSchemeId()).toBe('dark');
    expect(document.body.classList.contains('dark-mode')).toBe(true);
    expect(localStorage.getItem('theme:activeScheme')).toBe('dark');
  });

  it('should remove the dark-mode body class and apply scheme-ugly when switching back to ugly', () => {
    service.selectScheme('dark');
    service.selectScheme('ugly');
    expect(document.body.classList.contains('dark-mode')).toBe(false);
    expect(document.body.classList.contains('scheme-ugly')).toBe(true);
  });

  it('should apply the scheme-ocean body class when selecting the ocean scheme', () => {
    service.selectScheme('ocean');
    expect(service.activeSchemeId()).toBe('ocean');
    expect(document.body.classList.contains('scheme-ocean')).toBe(true);
  });

  it('should apply the scheme-amethyst body class when selecting the amethyst scheme', () => {
    service.selectScheme('amethyst');
    expect(service.activeSchemeId()).toBe('amethyst');
    expect(document.body.classList.contains('scheme-amethyst')).toBe(true);
  });

  it('should reject selecting an unknown scheme id', () => {
    service.selectScheme('not-a-real-scheme');
    expect(service.activeSchemeId()).toBe('ubc');
  });
});
