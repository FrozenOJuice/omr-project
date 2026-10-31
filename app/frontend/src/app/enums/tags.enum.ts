export enum ExamStatus {
  Graded = 'Graded',
  UnGraded = 'Not Graded',
  Processing = 'Grading In Progress',
  ReviewRequired = 'Review-Required',
  ScanFailed = 'Scan Failed'
}

export enum RegradeStatus {
  Pending = 'pending',
  Resolved = 'resolved',
  Rejected = 'rejected',
}

export enum ReleaseStatus {
  Released = 'released',
  Unreleased = 'unreleased',
}

export const ExamStatusClass: Record<ExamStatus, string> = {
  [ExamStatus.Graded]:   'tag-green',
  [ExamStatus.UnGraded]: 'tag-outline',
  [ExamStatus.Processing]: 'tag-blue',
  [ExamStatus.ReviewRequired]: 'tag-orange',
  [ExamStatus.ScanFailed]: 'tag-red',
};

// Keyed as Record<RegradeStatus, string> so the literal below is checked for
// completeness, but exported as Record<string, string> since status often
// arrives as a plain string from the API (e.g. ApiReviewRequest.status).
const regradeStatusClassMap: Record<RegradeStatus, string> = {
  [RegradeStatus.Pending]:  'tag-blue',
  [RegradeStatus.Resolved]: 'tag-teal',
  [RegradeStatus.Rejected]:   'tag-red',
};
export const RegradeStatusClass: Record<string, string> = regradeStatusClassMap;

const regradeStatusLabelMap: Record<RegradeStatus, string> = {
  [RegradeStatus.Pending]:  'Pending',
  [RegradeStatus.Resolved]: 'Resolved',
  [RegradeStatus.Rejected]:   'Rejected',
};
export const RegradeStatusLabel: Record<string, string> = regradeStatusLabelMap;

const releaseStatusClassMap: Record<ReleaseStatus, string> = {
  [ReleaseStatus.Released]:   'tag-green',
  [ReleaseStatus.Unreleased]: 'tag-outline',
};
export const ReleaseStatusClass: Record<string, string> = releaseStatusClassMap;

const releaseStatusLabelMap: Record<ReleaseStatus, string> = {
  [ReleaseStatus.Released]:   'Released',
  [ReleaseStatus.Unreleased]: 'Not Released',
};
export const ReleaseStatusLabel: Record<string, string> = releaseStatusLabelMap;
