const DEFAULT_USER_MESSAGE = 'Something went wrong. Please try again later.'

function isJsonResponse(response) {
  const type = response.headers.get('content-type') || ''
  return type.includes('application/json')
}

async function parseBody(response) {
  if (isJsonResponse(response)) {
    try {
      return await response.json()
    } catch {
      return null
    }
  }
  const text = await response.text()
  return text ? { message: text } : null
}

function getErrorMessage(response, body) {
  if (body) {
    if (typeof body.error === 'string' && body.error.trim()) {
      return body.error
    }
    if (typeof body.message === 'string' && body.message.trim()) {
      return body.message
    }
    if (typeof body.response === 'string' && body.response.trim()) {
      return body.response
    }
  }
  if (response.status >= 500) {
    return 'Server error. Please try again later.'
  }
  if (response.status === 401) {
    return 'Please log in to continue.'
  }
  if (response.status === 403) {
    return 'You do not have permission to perform this action.'
  }
  if (response.status === 413) {
    return 'File is too large. Please upload a smaller file.'
  }
  if (response.status === 429) {
    return 'Too many requests. Please wait a moment.'
  }
  if (response.status >= 400) {
    return 'Request failed. Please check your input and try again.'
  }
  return DEFAULT_USER_MESSAGE
}

export async function apiFetch(path, options = {}) {
  let response
  try {
    response = await fetch(path, options)
  } catch (error) {
    throw new Error(
      error?.name === 'AbortError'
        ? 'Request was cancelled.'
        : 'Network error. Please check your connection and try again.'
    )
  }

  const body = await parseBody(response)

  if (!response.ok) {
    throw new Error(getErrorMessage(response, body))
  }

  return body ?? {}
}

export async function apiPost(path, payload, options = {}) {
  const isFormData = payload instanceof FormData
  return apiFetch(path, {
    method: 'POST',
    headers: isFormData ? {} : { 'Content-Type': 'application/json' },
    body: isFormData ? payload : JSON.stringify(payload),
    ...options,
  })
}

export async function apiGet(path, options = {}) {
  return apiFetch(path, { method: 'GET', ...options })
}

export async function apiPut(path, payload, options = {}) {
  return apiFetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    ...options,
  })
}

export async function apiDelete(path, options = {}) {
  return apiFetch(path, { method: 'DELETE', ...options })
}
