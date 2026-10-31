import { ComponentFixture, TestBed } from '@angular/core/testing';
import { QuestionSnippet } from './question-snippet';
import { QuestionBounds } from '../../models/exam.model';

describe('QuestionSnippet', () => {
  let component: QuestionSnippet;
  let fixture: ComponentFixture<QuestionSnippet>;

  const setBounds = (bounds: QuestionBounds, boxWidth: number, boxHeight: number) => {
    fixture.componentRef.setInput('imageUrl', 'blob:page');
    fixture.componentRef.setInput('bounds', bounds);
    fixture.componentRef.setInput('boxWidth', boxWidth);
    fixture.componentRef.setInput('boxHeight', boxHeight);
    fixture.detectChanges();
  };

  const loadImage = (naturalWidth: number, naturalHeight: number) => {
    const img: HTMLImageElement = fixture.nativeElement.querySelector('img');
    Object.defineProperty(img, 'naturalWidth', { value: naturalWidth, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: naturalHeight, configurable: true });
    img.dispatchEvent(new Event('load'));
    fixture.detectChanges();
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [QuestionSnippet],
    }).compileComponents();

    fixture = TestBed.createComponent(QuestionSnippet);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should size the host to boxWidth/boxHeight', () => {
    setBounds({ x: 0, y: 0, width: 100, height: 100 }, 96, 64);
    expect(component.hostStyle()).toEqual({ width: '96px', height: '64px' });
  });

  it('should hide the image before imageUrl is set', () => {
    fixture.componentRef.setInput('bounds', { x: 0, y: 0, width: 100, height: 100 });
    fixture.detectChanges();
    expect(component.imageStyle()['visibility']).toBe('hidden');
  });

  it('should hide the image before bounds is set', () => {
    fixture.componentRef.setInput('imageUrl', 'blob:page');
    fixture.detectChanges();
    expect(component.imageStyle()['visibility']).toBe('hidden');
  });

  it('should hide the image until it has loaded (natural size unknown)', () => {
    setBounds({ x: 0, y: 0, width: 100, height: 100 }, 96, 64);
    expect(component.imageStyle()['visibility']).toBe('hidden');
  });

  it('should ignore a load event that reports no natural size', () => {
    setBounds({ x: 0, y: 0, width: 100, height: 100 }, 96, 64);
    loadImage(0, 0);
    expect(component.imageStyle()['visibility']).toBe('hidden');
  });

  it('should expand bounds by a margin before scaling it into a square box with no cropping', () => {
    // bounds is 100x100, so the shorter-dimension margin is 100 * 0.3 = 30,
    // giving a padded rect of 160x160 at (70,70). A 160x160 box then needs no
    // further scaling (scale = 1), so the numbers come out exact.
    setBounds({ x: 100, y: 100, width: 100, height: 100 }, 160, 160);
    loadImage(1000, 1000);

    expect(component.imageStyle()).toEqual({
      visibility: 'visible',
      width: '1000px',
      height: '1000px',
      left: '-70px',
      top: '-70px',
    });
  });

  it('should scale the image up to fill a box larger than the padded bounds', () => {
    // Same padded rect as above (160x160), but a 320x320 box needs scale = 2.
    setBounds({ x: 100, y: 100, width: 100, height: 100 }, 320, 320);
    loadImage(1000, 1000);

    expect(component.imageStyle()).toEqual({
      visibility: 'visible',
      width: '2000px',
      height: '2000px',
      left: '-140px',
      top: '-140px',
    });
  });

  it('should use the larger of the two axis scales, like object-fit: cover, when the box aspect ratio does not match', () => {
    const bounds: QuestionBounds = { x: 40, y: 10, width: 100, height: 50 };
    const boxWidth = 100;
    const boxHeight = 100;
    setBounds(bounds, boxWidth, boxHeight);
    loadImage(1000, 1000);

    const margin = Math.min(bounds.width, bounds.height) * 0.3;
    const padded = {
      x: bounds.x - margin,
      y: bounds.y - margin,
      width: bounds.width + margin * 2,
      height: bounds.height + margin * 2,
    };
    const scale = Math.max(boxWidth / padded.width, boxHeight / padded.height);
    const croppedWidth = padded.width * scale;
    const croppedHeight = padded.height * scale;

    expect(component.imageStyle()).toEqual({
      visibility: 'visible',
      width: `${1000 * scale}px`,
      height: `${1000 * scale}px`,
      left: `${-(padded.x * scale) - (croppedWidth - boxWidth) / 2}px`,
      top: `${-(padded.y * scale) - (croppedHeight - boxHeight) / 2}px`,
    });
    // Confirms scaleY is really the larger of the two here, so the equality
    // above is exercising the mismatched-aspect branch, not a coincidence.
    expect(scale).toBe(boxHeight / padded.height);
  });

  it('should base the margin on the shorter dimension for a wide, many-option question rather than an inflated average', () => {
    // bounds is 900x30 (a question with many options in one short row).
    // Averaging width and height would inflate the margin to (900+30)/2*0.3
    // = 139.5, pulling in far more of the surrounding page (e.g. the
    // question's own printed number) than a normal question's margin ever
    // would. Basing it on the shorter dimension keeps it proportionate: 30
    // * 0.3 = 9, the same margin a same-height A-E question would get.
    const bounds: QuestionBounds = { x: 200, y: 100, width: 900, height: 30 };
    setBounds(bounds, 300, 45);
    loadImage(1000, 1000);

    const margin = 9;
    const paddedX = bounds.x - margin;
    const scale = Math.max(300 / (900 + margin * 2), 45 / (30 + margin * 2));
    const croppedWidth = (900 + margin * 2) * scale;

    expect(component.imageStyle()['left']).toBe(`${-(paddedX * scale) - (croppedWidth - 300) / 2}px`);
  });
});
