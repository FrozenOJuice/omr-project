import { AfterViewInit, Component, ElementRef, OnDestroy, ViewChild, input } from '@angular/core';

@Component({
  selector: 'app-aperture-logo',
  imports: [],
  templateUrl: './aperture-logo.html',
  styleUrl: './aperture-logo.css',
})
export class ApertureLogo implements AfterViewInit, OnDestroy {
  // Roughly determines the logo's height -- see --logo-size in aperture-logo.css.
  size = input('200px');
  // Shows just the spinning aperture badge, without the "mr"/"by Aperture"
  // wordmark -- for spots (favicons, small square badges) where the full
  // lockup's wide aspect ratio doesn't fit.
  iconOnly = input(false);

  @ViewChild('logoRoot') private logoRoot!: ElementRef<HTMLDivElement>;

  // Hover shouldn't fight the startup sequence's own timers, so it's ignored
  // until that sequence finishes.
  private introPlaying = true;
  private introTimers: ReturnType<typeof setTimeout>[] = [];

  ngAfterViewInit(): void {
    // @ViewChild isn't resolved until after this hook fires, so setAperture
    // (which reads logoRoot.nativeElement) can't run any earlier than this.
    // Just a little woo-wah on startup.
    this.setAperture(0);
    this.introTimers.push(setTimeout(() => {
      this.setAperture(1);
      this.introTimers.push(setTimeout(() => {
        this.setAperture(0.65);
        this.introTimers.push(setTimeout(() => {
          this.setAperture(0.9);
          this.introPlaying = false;
        }, 400));
      }, 400));
    }, 400));
  }

  ngOnDestroy(): void {
    this.introTimers.forEach(clearTimeout);
  }

  onMouseEnter(): void {
    if (this.introPlaying) return;
    this.setAperture(0);
  }

  onMouseLeave(): void {
    if (this.introPlaying) return;
    this.setAperture(1);
  }

  /**
   * Set the open-ness of the aperture.
   *
   * @param openness a number from 0 to 1, where 1 is fully open
   *                 and 0 is fully closed.
   */
  private setAperture(openness: number): void {
    let value = openness * -35 + -5;
    value = Math.max(value, -40);
    value = Math.min(value, -5);
    this.logoRoot.nativeElement.style.setProperty('--aperture-size', `${Math.round(value)}deg`);
  }
}
