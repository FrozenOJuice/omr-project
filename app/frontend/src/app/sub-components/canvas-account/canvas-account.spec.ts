import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { CanvasConnection } from '../../models/canvas.model';
import { CanvasService } from '../../services/canvas.service';
import { CanvasAccount } from './canvas-account';

const connected: CanvasConnection = {
  connected: true,
  user_name: 'Professor Example',
  login_id: 'professor@example.com',
  connected_at: null,
  last_verified_at: null,
};

const disconnected: CanvasConnection = {
  connected: false,
  user_name: null,
  login_id: null,
  connected_at: null,
  last_verified_at: null,
};

describe('CanvasAccount', () => {
  let fixture: ComponentFixture<CanvasAccount>;
  let component: CanvasAccount;
  const canvasService = {
    getConnection: vi.fn(() => of(connected)),
    connect: vi.fn(() => of(connected)),
    disconnect: vi.fn(() => of(undefined)),
  };

  beforeEach(async () => {
    vi.clearAllMocks();
    canvasService.getConnection.mockReturnValue(of(connected));
    canvasService.connect.mockReturnValue(of(connected));
    canvasService.disconnect.mockReturnValue(of(undefined));
    await TestBed.configureTestingModule({
      imports: [CanvasAccount],
      providers: [{ provide: CanvasService, useValue: canvasService }],
    }).compileComponents();
    fixture = TestBed.createComponent(CanvasAccount);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('shows only the connected Canvas identity and connection controls', () => {
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Professor Example');
    expect(text).toContain('Replace token');
    expect(text).toContain('Disconnect');
    expect(text).not.toContain('Import course');
    expect(text).not.toContain('View students');
  });

  it('keeps token instructions in an accessible tooltip and masks the input', () => {
    canvasService.getConnection.mockReturnValue(of(disconnected));
    const disconnectedFixture = TestBed.createComponent(CanvasAccount);
    disconnectedFixture.componentRef.setInput(
      'settingsUrl',
      'http://localhost:6700/profile/settings',
    );
    disconnectedFixture.detectChanges();

    const input: HTMLInputElement =
      disconnectedFixture.nativeElement.querySelector('#canvas-access-token');
    const helpButton: HTMLAnchorElement =
      disconnectedFixture.nativeElement.querySelector('.canvas-info-button');
    const tooltip: HTMLElement = disconnectedFixture.nativeElement.querySelector(
      '#canvas-token-instructions',
    );
    expect(helpButton.getAttribute('aria-describedby')).toBe(tooltip.id);
    expect(tooltip.textContent).toContain('Account → Settings');
    expect(tooltip.textContent).toContain('+ New Access Token');
    expect(input.type).toBe('password');
    expect(input.autocomplete).toBe('off');
    expect(helpButton.href).toBe('http://localhost:6700/profile/settings');
    expect(helpButton.target).toBe('_blank');
  });

  it('validates, submits, and immediately clears a personal access token', () => {
    canvasService.getConnection.mockReturnValue(of(disconnected));
    const request = new Subject<CanvasConnection>();
    canvasService.connect.mockReturnValue(request);
    const disconnectedFixture = TestBed.createComponent(CanvasAccount);
    const disconnectedComponent = disconnectedFixture.componentInstance;
    disconnectedFixture.detectChanges();

    disconnectedComponent.accessToken = '  secret-token  ';
    disconnectedComponent.connect();

    expect(canvasService.connect).toHaveBeenCalledWith('secret-token');
    expect(disconnectedComponent.actionPending).toBe(true);

    request.next(connected);
    request.complete();

    expect(disconnectedComponent.accessToken).toBe('');
    expect(disconnectedComponent.connection).toEqual(connected);
    expect(disconnectedComponent.notice).toBe('Canvas connected successfully.');
  });

  it('does not submit an empty token', () => {
    component.accessToken = '   ';
    component.connect();

    expect(canvasService.connect).not.toHaveBeenCalled();
    expect(component.error).toBe('Enter a Canvas access token.');
  });

  it('clears a rejected token without exposing it in the error', () => {
    canvasService.getConnection.mockReturnValue(of(disconnected));
    canvasService.connect.mockReturnValue(
      throwError(() => ({ error: { error: { message: 'Canvas rejected this access token.' } } })),
    );
    const disconnectedFixture = TestBed.createComponent(CanvasAccount);
    const disconnectedComponent = disconnectedFixture.componentInstance;
    disconnectedFixture.detectChanges();

    disconnectedComponent.accessToken = 'rejected-secret';
    disconnectedComponent.connect();

    expect(disconnectedComponent.accessToken).toBe('');
    expect(disconnectedComponent.error).toBe('Canvas rejected this access token.');
    disconnectedFixture.detectChanges();
    expect(disconnectedFixture.nativeElement.textContent).not.toContain('rejected-secret');
  });

  it('replaces a connected token without showing or retaining the new token', () => {
    component.replaceToken();
    component.accessToken = 'replacement-secret';
    component.connect();

    expect(canvasService.connect).toHaveBeenCalledWith('replacement-secret');
    expect(component.accessToken).toBe('');
    expect(component.replacingToken).toBe(false);
    expect(component.notice).toBe('Canvas access token replaced.');
  });

  it('keeps replacement controls open but clears a rejected replacement token', () => {
    canvasService.connect.mockReturnValue(throwError(() => ({ status: 401 })));
    component.replaceToken();
    component.accessToken = 'bad-replacement';
    component.connect();

    expect(component.connection).toEqual(connected);
    expect(component.replacingToken).toBe(true);
    expect(component.accessToken).toBe('');
  });

  it('disconnects without loading course data', () => {
    component.disconnect();

    expect(canvasService.disconnect).toHaveBeenCalled();
    expect(component.connection?.connected).toBe(false);
    expect(component.notice).toContain('Revoke the token in Canvas');
  });
});
