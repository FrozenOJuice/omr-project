import { Component, ElementRef, computed, effect, inject, viewChild } from '@angular/core';
import { Router, RouterOutlet, NavigationEnd } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { filter, map } from 'rxjs/operators';
import { LeftMenu } from './sub-components/left-menu/left-menu';
import { NotificationToast } from './sub-components/notification-toast/notification-toast';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, LeftMenu, NotificationToast],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  private router = inject(Router);

  // The router-outlet lives inside one persistent scrollable element (see
  // .page-content in app.css) that's never destroyed between navigations --
  // unlike a full page load, its scroll position carries over from whatever
  // route you were previously on, which can land a shorter page part way
  // down or at its very end. Reset it on every navigation instead.
  private readonly pageContent = viewChild<ElementRef<HTMLElement>>('pageContent');

  private currentUrl = toSignal(
    this.router.events.pipe(
      filter(e => e instanceof NavigationEnd),
      map(e => (e as NavigationEnd).url)
    ),
    { initialValue: this.router.url }
  );

  private readonly menuRoutes = ['/admin', '/courses', '/grades', '/regrade', '/notifications', '/account'];

  showMenu = computed(() => this.menuRoutes.some(route => this.currentUrl().startsWith(route)));

  constructor() {
    effect(() => {
      this.currentUrl();
      this.pageContent()?.nativeElement.scrollTo({ top: 0 });
    });
  }
}
