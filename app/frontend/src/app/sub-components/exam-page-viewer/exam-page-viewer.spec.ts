import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { vi } from 'vitest';
import { ExamPageViewer, PositionedRegion } from './exam-page-viewer';
import { padQuestionBounds } from '../question-snippet/question-snippet';

function pointerEvent(type: string, props: Partial<PointerEvent> = {}): PointerEvent {
  return Object.assign(new Event(type), { clientX: 0, clientY: 0, button: 0, buttons: 1, ...props }) as PointerEvent;
}

const mkRegion = (overrides: Partial<PositionedRegion> = {}): PositionedRegion => ({
  questionId: 'q1',
  x: 0,
  y: 0,
  width: 100,
  height: 100,
  ...overrides,
});

const mkMouseEvent = (clientX: number, clientY: number): MouseEvent =>
  new MouseEvent('mouseenter', { clientX, clientY });

describe('ExamPageViewer', () => {
  let component: ExamPageViewer;
  let fixture: ComponentFixture<ExamPageViewer>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ExamPageViewer],
    }).compileComponents();

    fixture = TestBed.createComponent(ExamPageViewer);
    component = fixture.componentInstance;
    fixture.componentRef.setInput('zoomable', true);
    fixture.componentRef.setInput('imageUrl', 'blob:fake');
    fixture.detectChanges();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function wrapper(): HTMLDivElement {
    return fixture.debugElement.query(By.css('.page-image-wrapper')).nativeElement;
  }

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should pan the wrapper scroll position while dragging', () => {
    component.onPanStart(pointerEvent('pointerdown', { clientX: 100, clientY: 50, button: 0 }));
    component.onWindowPointerMove(pointerEvent('pointermove', { clientX: 70, clientY: 65, buttons: 1 }));

    expect(wrapper().scrollLeft).toBe(30);
    expect(wrapper().scrollTop).toBe(-15);
  });

  it('should ignore a drag started with a non-primary button', () => {
    component.onPanStart(pointerEvent('pointerdown', { clientX: 100, clientY: 50, button: 2 }));
    component.onWindowPointerMove(pointerEvent('pointermove', { clientX: 0, clientY: 0, buttons: 1 }));

    expect(wrapper().scrollLeft).toBe(0);
  });

  it('should end the drag on pointerup', () => {
    component.onPanStart(pointerEvent('pointerdown', { clientX: 100, clientY: 50, button: 0 }));
    component.onWindowPointerUp();
    component.onWindowPointerMove(pointerEvent('pointermove', { clientX: 0, clientY: 0, buttons: 1 }));

    expect(wrapper().scrollLeft).toBe(0);
  });

  // Regression test: if the button is released outside the browser
  // viewport, no pointerup ever reaches the window listener, so the only
  // signal that the drag ended is event.buttons going to 0 on the next move.
  it('should end a stuck drag once the released button is observed on a later move', () => {
    component.onPanStart(pointerEvent('pointerdown', { clientX: 100, clientY: 50, button: 0 }));
    component.onWindowPointerMove(pointerEvent('pointermove', { clientX: 0, clientY: 0, buttons: 0 }));

    const scrollLeftAfterRelease = wrapper().scrollLeft;
    component.onWindowPointerMove(pointerEvent('pointermove', { clientX: -500, clientY: 0, buttons: 1 }));

    expect(wrapper().scrollLeft).toBe(scrollLeftAfterRelease);
  });

  it('resetZoom should reset both the zoom level and the scroll position', () => {
    component.zoomIn();
    wrapper().scrollLeft = 40;
    wrapper().scrollTop = 20;

    component.resetZoom();

    expect(component.zoomPercent()).toBe(100);
    expect(wrapper().scrollLeft).toBe(0);
    expect(wrapper().scrollTop).toBe(0);
  });

  it('should reset zoom when gradeId changes, i.e. a different scan is selected', async () => {
    fixture.componentRef.setInput('gradeId', 'g1');
    fixture.detectChanges();
    await fixture.whenStable();

    component.zoomIn();
    expect(component.zoomPercent()).toBe(125);

    fixture.componentRef.setInput('gradeId', 'g2');
    fixture.detectChanges();
    await fixture.whenStable();

    expect(component.zoomPercent()).toBe(100);
  });

  it('should not reset zoom when only the page/imageUrl change within the same scan', async () => {
    fixture.componentRef.setInput('gradeId', 'g1');
    fixture.detectChanges();
    await fixture.whenStable();

    component.zoomIn();
    fixture.componentRef.setInput('imageUrl', 'blob:fake-page-2');
    fixture.componentRef.setInput('page', 1);
    fixture.detectChanges();
    await fixture.whenStable();

    expect(component.zoomPercent()).toBe(125);
  });

  it('should not show a preview immediately on entering a region', () => {
    vi.useFakeTimers();
    component.onRegionEnter(mkRegion(), mkMouseEvent(10, 10));
    expect(component.previewRegion()).toBeNull();
  });

  it('should show the preview once the hover delay elapses', () => {
    vi.useFakeTimers();
    const region = mkRegion({ questionId: 'q2' });
    component.onRegionEnter(region, mkMouseEvent(10, 10));
    vi.advanceTimersByTime(250);
    expect(component.previewRegion()).toEqual(region);
  });

  it('should not show the preview if the pointer leaves before the delay elapses', () => {
    vi.useFakeTimers();
    component.onRegionEnter(mkRegion(), mkMouseEvent(10, 10));
    vi.advanceTimersByTime(200);
    component.onRegionLeave();
    vi.advanceTimersByTime(250);
    expect(component.previewRegion()).toBeNull();
  });

  it('should hide an already-shown preview immediately on leave', () => {
    vi.useFakeTimers();
    component.onRegionEnter(mkRegion(), mkMouseEvent(10, 10));
    vi.advanceTimersByTime(250);
    expect(component.previewRegion()).not.toBeNull();

    component.onRegionLeave();
    expect(component.previewRegion()).toBeNull();
  });

  it('should restart the delay for a newly entered region without showing the previous one', () => {
    vi.useFakeTimers();
    component.onRegionEnter(mkRegion({ questionId: 'q1' }), mkMouseEvent(10, 10));
    vi.advanceTimersByTime(200);
    component.onRegionLeave();
    const secondRegion = mkRegion({ questionId: 'q2' });
    component.onRegionEnter(secondRegion, mkMouseEvent(20, 20));
    vi.advanceTimersByTime(200);
    expect(component.previewRegion()).toBeNull();

    vi.advanceTimersByTime(50);
    expect(component.previewRegion()).toEqual(secondRegion);
  });

  it('should clear a pending preview timer on destroy', () => {
    vi.useFakeTimers();
    component.onRegionEnter(mkRegion(), mkMouseEvent(10, 10));
    fixture.destroy();
    vi.advanceTimersByTime(250);
    expect(component.previewRegion()).toBeNull();
  });

  it('should scale the padded preview (not the raw region) by the fixed factor when it comfortably fits the viewport', () => {
    // Sized from the padded region -- the same rect QuestionSnippet
    // actually crops -- not the raw one, so the box's aspect ratio matches
    // what's cropped and none of the padding gets silently cover-cropped
    // back off.
    vi.useFakeTimers();
    component.onRegionEnter(mkRegion({ width: 400, height: 100 }), mkMouseEvent(0, 0));
    vi.advanceTimersByTime(250);

    const padded = padQuestionBounds({ x: 0, y: 0, width: 400, height: 100 });
    const size = component.previewSize();
    expect(size).toEqual({ width: padded.width * 1.5, height: padded.height * 1.5 });
  });

  it('should scale a taller region by the same fixed factor, still preserving its (padded) aspect ratio', () => {
    vi.useFakeTimers();
    component.onRegionEnter(mkRegion({ width: 100, height: 400 }), mkMouseEvent(0, 0));
    vi.advanceTimersByTime(250);

    const padded = padQuestionBounds({ x: 0, y: 0, width: 100, height: 400 });
    const size = component.previewSize();
    expect(size).toEqual({ width: padded.width * 1.5, height: padded.height * 1.5 });
  });

  it('should shrink a region uniformly (never cropping it) when the fixed factor would not fit the viewport', () => {
    // A region wide enough that scaling it by the normal 1.5x factor would
    // overflow the screen -- both axes shrink together to whatever fits,
    // so the whole region is still visible, just smaller, rather than
    // capping width and height independently and cropping the sides off.
    vi.useFakeTimers();
    const hugeWidth = window.innerWidth * 10;
    component.onRegionEnter(mkRegion({ width: hugeWidth, height: 100 }), mkMouseEvent(0, 0));
    vi.advanceTimersByTime(250);

    const padded = padQuestionBounds({ x: 0, y: 0, width: hugeWidth, height: 100 });
    const size = component.previewSize()!;
    expect(size.width).toBeLessThanOrEqual(window.innerWidth - 64);
    expect(size.width / size.height).toBeCloseTo(padded.width / padded.height, 5);
  });

  it('should position the preview offset from the cursor by default', () => {
    vi.useFakeTimers();
    component.onRegionEnter(mkRegion({ width: 100, height: 100 }), mkMouseEvent(100, 100));
    vi.advanceTimersByTime(250);

    expect(component.previewPositionStyle()).toEqual({ left: '120px', top: '120px' });
  });

  it('should flip to the other side of the cursor when the default position would overflow the viewport', () => {
    vi.useFakeTimers();
    const nearRightEdge = window.innerWidth - 10;
    const nearBottomEdge = window.innerHeight - 10;
    component.onRegionEnter(mkRegion({ width: 100, height: 100 }), mkMouseEvent(nearRightEdge, nearBottomEdge));
    vi.advanceTimersByTime(250);

    const size = component.previewSize()!;
    const style = component.previewPositionStyle()!;
    expect(parseFloat(style['left'])).toBeLessThan(nearRightEdge);
    expect(parseFloat(style['top'])).toBeLessThan(nearBottomEdge);
    expect(parseFloat(style['left']) + size.width).toBeLessThanOrEqual(window.innerWidth - 12);
    expect(parseFloat(style['top']) + size.height).toBeLessThanOrEqual(window.innerHeight - 12);
  });

  it('should not show a preview for the identity/version regions, only a plain hover highlight', () => {
    vi.useFakeTimers();
    fixture.componentRef.setInput('imageUrl', 'blob:page');
    fixture.componentRef.setInput('identity', {
      fields: [
        {
          field_type: 'first_name',
          field_index: 0,
          bounds: { x: 0, y: 0, width: 50, height: 50 },
          boxes: [{ label: 'A', selected: true, x: 0, y: 0, width: 10, height: 10 }],
          confidence: 1,
        },
      ],
      last_name: 'Doe',
      first_name: 'Jane',
      student_id: '123',
      page_index: 0,
    });
    fixture.detectChanges();

    const identityRegionEl: HTMLElement = fixture.nativeElement.querySelectorAll('.question-region')[0];
    identityRegionEl.dispatchEvent(new MouseEvent('mouseenter'));
    vi.advanceTimersByTime(250);

    expect(component.previewRegion()).toBeNull();
  });
});
