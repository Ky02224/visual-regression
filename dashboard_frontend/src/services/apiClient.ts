/**
 * Centralized API client with error handling and logging
 */

interface ApiError {
  status: number;
  message: string;
  timestamp: string;
}

export class ApiClientError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiClientError';
  }
}

class ApiClient {
  private static instance: ApiClient;
  private baseUrl = (import.meta.env.VITE_API_BASE_URL as string) || '';

  private constructor() {}

  static getInstance(): ApiClient {
    if (!ApiClient.instance) {
      ApiClient.instance = new ApiClient();
    }
    return ApiClient.instance;
  }

  private logError(method: string, url: string, error: unknown, status?: number): void {
    const timestamp = new Date().toISOString();
    const errorMsg = error instanceof Error ? error.message : String(error);
    console.error(`[API Error ${timestamp}] ${method} ${url} (${status || 'unknown'})`, errorMsg);
  }

  private async handleResponse<T>(res: Response): Promise<T> {
    if (!res.ok) {
      const error: ApiError = {
        status: res.status,
        message: `${res.status}: ${res.statusText}`,
        timestamp: new Date().toISOString(),
      };

      try {
        const body = await res.json();
        error.message = body.error || error.message;
      } catch {
        // Response is not JSON, use status text
      }

      throw new ApiClientError(res.status, error.message);
    }

    // A 204 No Content (the normal REST convention for DELETE, and valid for
    // PUT/POST too) has no body — res.json() throws on it, which used to be
    // indistinguishable from a real parse failure.
    if (res.status === 204) {
      return undefined as T;
    }

    try {
      return await res.json() as T;
    } catch (error) {
      this.logError('JSON Parse', res.url, error);
      throw new Error('Failed to parse response');
    }
  }

  // Builds the final fetch config with `options` spread first, so method/
  // headers/body/credentials always win over anything in `options` instead
  // of `...options` (previously spread last) silently clobbering the
  // carefully merged headers or JSON-stringified body.
  private buildInit(method: string, options: RequestInit | undefined, body?: unknown): RequestInit {
    return {
      credentials: 'include',
      ...options,
      method,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    };
  }

  async get<T>(url: string, options?: RequestInit): Promise<T> {
    try {
      const res = await fetch(`${this.baseUrl}${url}`, this.buildInit('GET', options));
      return this.handleResponse<T>(res);
    } catch (error) {
      if (error instanceof ApiClientError) {
        this.logError('GET', url, error, error.status);
      } else {
        this.logError('GET', url, error);
      }
      throw error;
    }
  }

  async post<T>(url: string, body?: unknown, options?: RequestInit): Promise<T> {
    try {
      const res = await fetch(`${this.baseUrl}${url}`, this.buildInit('POST', options, body));
      return this.handleResponse<T>(res);
    } catch (error) {
      if (error instanceof ApiClientError) {
        this.logError('POST', url, error, error.status);
      } else {
        this.logError('POST', url, error);
      }
      throw error;
    }
  }

  async put<T>(url: string, body?: unknown, options?: RequestInit): Promise<T> {
    try {
      const res = await fetch(`${this.baseUrl}${url}`, this.buildInit('PUT', options, body));
      return this.handleResponse<T>(res);
    } catch (error) {
      if (error instanceof ApiClientError) {
        this.logError('PUT', url, error, error.status);
      } else {
        this.logError('PUT', url, error);
      }
      throw error;
    }
  }

  async delete<T>(url: string, options?: RequestInit): Promise<T> {
    try {
      const res = await fetch(`${this.baseUrl}${url}`, this.buildInit('DELETE', options));
      return this.handleResponse<T>(res);
    } catch (error) {
      if (error instanceof ApiClientError) {
        this.logError('DELETE', url, error, error.status);
      } else {
        this.logError('DELETE', url, error);
      }
      throw error;
    }
  }
}

export const api = ApiClient.getInstance();
