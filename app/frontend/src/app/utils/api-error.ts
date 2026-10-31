interface ApiValidationDetail {
  loc?: (string | number)[];
  msg?: string;
}

interface ApiErrorBody {
  code?: string;
  message?: string;
  details?: ApiValidationDetail[] | unknown;
}

// Backend error responses look like { error: { code, message, details } }.
export function extractApiErrorMessage(err: unknown, fallback: string): string {
  const body = (err as { error?: { error?: ApiErrorBody } } | null | undefined)?.error?.error;

  if (!body) return fallback;

  if (body.code === 'validation_error' && Array.isArray(body.details) && body.details.length > 0) {
    const detail = body.details[0] as ApiValidationDetail;
    const field = detail.loc?.filter(part => part !== 'body').join('.');
    if (detail.msg) return field ? `${field}: ${detail.msg}` : detail.msg;
  }

  return body.message || fallback;
}
