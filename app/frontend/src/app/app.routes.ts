import { Routes } from '@angular/router';
import { Component, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { Login } from './components/login/login';
import { Registration } from './components/registration/registration';
import { ForgotPassword } from './components/forgot-password/forgot-password';
import { ResetPassword } from './components/reset-password/reset-password';
import { Notifications } from './components/notifications/notifications';
import { authGuard } from './guards/auth.guard';
import { roleGuard } from './guards/role.guard';
import { guestGuard } from './guards/guest.guard';
import { Courses } from './components/courses/courses';
import { CourseDetail } from './components/course-detail/course-detail';
import { JoinCourse } from './components/join-course/join-course';
import { RegradeRequests } from './components/regrade-requests/regrade-requests';
import { AnnotatedExamView } from './components/annotated-exam-view/annotated-exam-view';
import { StudentExamView } from './components/student-exam-view/student-exam-view';
import { CanvasStudentExamView } from './components/canvas-student-exam-view/canvas-student-exam-view';

// Single placeholder used for all pages that haven't been built yet.
// Reads the page title from the route's data property.
@Component({
  imports: [],
  template: `<div style="padding: 2em; color: var(--secondary)"><h1>{{ title }}</h1></div>`,
})
class Page {
  title = inject(ActivatedRoute).snapshot.data['title'] ?? '';
}

export const routes: Routes = [
  { path: '',               redirectTo: 'login', pathMatch: 'full' },
  { path: 'login',          component: Login,          canActivate: [guestGuard] },
  { path: 'registration',   component: Registration },
  { path: 'forgot-password', component: ForgotPassword },
  { path: 'reset-password', component: ResetPassword },
  { path: 'dashboard',     redirectTo: 'courses' },
  {
    path: 'admin',
    loadComponent: () => import('./components/admin-dashboard/admin-dashboard')
      .then(module => module.AdminDashboard),
    canActivate: [authGuard, roleGuard(['admin'])],
  },
  { path: 'courses',       component: Courses,        canActivate: [authGuard] },
  { path: 'courses/:id',   component: CourseDetail,   canActivate: [authGuard] },
  { path: 'grades/:gradeId/annotations', component: AnnotatedExamView, canActivate: [authGuard, roleGuard(['professor', 'admin'])] },
  { path: 'grades/:gradeId/results', component: StudentExamView, canActivate: [authGuard, roleGuard(['student'])] },
  { path: 'canvas/results', component: CanvasStudentExamView },
  { path: 'regrade',       component: RegradeRequests, canActivate: [authGuard] },
  { path: 'notifications', component: Notifications,  canActivate: [authGuard] },
  {
    path: 'account',
    loadComponent: () => import('./components/account/account').then(module => module.Account),
    canActivate: [authGuard],
  },
  { path: 'join/:inviteLink', component: JoinCourse,  canActivate: [authGuard] },
];
